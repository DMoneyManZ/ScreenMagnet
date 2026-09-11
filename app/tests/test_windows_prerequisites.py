"""Execute prerequisite verification functions without downloading/installing software."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


POWERSHELL = os.environ.get('SCREENMAGNET_TEST_POWERSHELL') or shutil.which('pwsh') or shutil.which('powershell')
HELPER = Path(__file__).resolve().parents[2] / 'packaging/windows/install-prerequisites.ps1'
PIN = '51ee5eaec33008e8409d8cf6f6884457f22aa3bd515f8856f993a3eaab903530'


@unittest.skipUnless(POWERSHELL, 'PowerShell is required for prerequisite verification tests')
class PrerequisiteVerificationTests(unittest.TestCase):
    def run_ps(self, body):
        # Load only function definitions: never run the installer entry point.
        preamble = r'''
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:TEST_HELPER, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($node in $ast.EndBlock.Statements) {
    if ($node -is [System.Management.Automation.Language.FunctionDefinitionAst]) {
        . ([ScriptBlock]::Create($node.Extent.Text))
    }
}
function Expect-Failure([scriptblock]$Action, [string]$Message) {
    try { & $Action } catch {
        if ($_.Exception.Message -notlike $Message) { throw }
        return
    }
    throw 'Expected verification to reject the prerequisite.'
}
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'test.ps1'
            script.write_text(preamble + body, encoding='utf-8')
            result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive', '-File', str(script)],
                                    env=dict(os.environ, TEST_HELPER=str(HELPER), TEST_DIR=directory,
                                             TEST_PIN=PIN), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unsigned_gstreamer_accepts_only_reviewed_release_hash(self):
        self.run_ps(r'''
function Get-FileHash { [pscustomobject]@{ Hash = $env:TEST_PIN } }
function Get-AuthenticodeSignature { throw 'GStreamer uses a pinned upstream checksum, not Authenticode.' }
$hash = Assert-VerifiedInstaller 'fixture.exe' $env:TEST_PIN 'gstreamer'
if ($hash -ne $env:TEST_PIN) { throw 'Verified checksum was not returned.' }
Expect-Failure { Assert-VerifiedInstaller 'fixture.exe' ('0' * 64) 'gstreamer' } '*pinned GStreamer*'
''')

    def test_tampered_gstreamer_file_is_rejected(self):
        self.run_ps(r'''
$file = Join-Path $env:TEST_DIR 'tampered.exe'
Set-Content -LiteralPath $file -Value 'not the reviewed installer'
Expect-Failure { Assert-VerifiedInstaller $file $env:TEST_PIN 'gstreamer' } '*SHA-256 mismatch*'
''')

    def test_vcredist_still_requires_authenticode_and_manifest_hash(self):
        self.run_ps(r'''
function Get-FileHash { [pscustomobject]@{ Hash = $env:TEST_PIN } }
function Get-AuthenticodeSignature { [pscustomobject]@{ Status = 'NotSigned' } }
Expect-Failure { Assert-VerifiedInstaller 'fixture.exe' $env:TEST_PIN 'vcredist' } '*Authenticode verification failed*'
function Get-AuthenticodeSignature { [pscustomobject]@{ Status = 'Valid' } }
$null = Assert-VerifiedInstaller 'fixture.exe' $env:TEST_PIN 'vcredist'
Expect-Failure { Assert-VerifiedInstaller 'fixture.exe' ('0' * 64) 'vcredist' } '*SHA-256 mismatch*'
''')

    def test_published_checksum_requires_exact_filename_and_reviewed_pin(self):
        self.run_ps(r'''
$file = Join-Path $env:TEST_DIR 'upstream.sha256sum'
Set-Content -LiteralPath $file -Value ($env:TEST_PIN + '  gstreamer-1.0-msvc-x86_64-1.28.5.exe')
$null = Assert-OfficialGStreamerChecksum $file
Set-Content -LiteralPath $file -Value (('0' * 64) + '  gstreamer-1.0-msvc-x86_64-1.28.5.exe')
Expect-Failure { Assert-OfficialGStreamerChecksum $file } '*reviewed GStreamer*'
Set-Content -LiteralPath $file -Value ($env:TEST_PIN + '  unexpected.exe')
Expect-Failure { Assert-OfficialGStreamerChecksum $file } '*checksum format*'
''')
