[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PrerequisiteManifest,
    [string]$Sender = 'build/doubletake/bin/doubletake.exe',
    [string]$ReleaseData = 'build/release-data',
    [string]$Iscc
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
Push-Location $root
try {
    $Sender = (Resolve-Path -LiteralPath $Sender).Path
    $ReleaseData = (Resolve-Path -LiteralPath $ReleaseData).Path
    $PrerequisiteManifest = (Resolve-Path -LiteralPath $PrerequisiteManifest).Path
    if ($Sender -like '*\packaging\windows\vendor\*') {
        throw 'The historical vendored sender is not a reproducible release input.'
    }
    foreach ($required in @('source', 'licenses', 'THIRD-PARTY-NOTICES.md')) {
        if (!(Test-Path -LiteralPath (Join-Path $ReleaseData $required))) {
            throw "Release compliance input is missing: $required"
        }
    }
    $manifest = Get-Content -LiteralPath $PrerequisiteManifest -Raw | ConvertFrom-Json
    foreach ($id in @('gstreamer', 'vcredist')) {
        if ($manifest.$id.sha256 -notmatch '^[a-fA-F0-9]{64}$') { throw "No verified SHA-256 for $id." }
    }
    $version = (& python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])").Trim()
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+(\.\d+)?$') { throw 'Invalid application version.' }
    $parts = @($version.Split('.') | ForEach-Object { [int]$_ })
    while ($parts.Count -lt 4) { $parts += 0 }
    $numericVersion = $parts -join '.'
    $versionTuple = $parts -join ', '
    $build = Join-Path $root 'packaging\windows\build'
    $dist = Join-Path $root 'packaging\windows\dist'
    $output = Join-Path $root 'packaging\windows\output'
    $null = New-Item -ItemType Directory -Force -Path $build, $dist, $output
    $versionFile = Join-Path $build 'version-info.txt'
    @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($versionTuple), prodvers=($versionTuple), mask=0x3f, flags=0x2, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'DMoneyManZ'),
    StringStruct('FileDescription', 'ScreenMagnet Windows Preview'),
    StringStruct('FileVersion', '$version'),
    StringStruct('InternalName', 'ScreenMagnet'),
    StringStruct('OriginalFilename', 'ScreenMagnet.exe'),
    StringStruct('ProductName', 'ScreenMagnet'),
    StringStruct('ProductVersion', '$version'),
    StringStruct('LegalCopyright', 'Copyright (C) 2026 DMoneyManZ; GPL-3.0-or-later')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -LiteralPath $versionFile -Encoding UTF8
    & python -m PyInstaller --name ScreenMagnet --windowed --onedir --noconfirm --clean `
        --icon "$root\app\assets\screenmagnet.ico" `
        --version-file $versionFile `
        --add-data "$root\app\assets;assets" `
        --paths "$root\app" --distpath $dist --workpath $build --specpath $PSScriptRoot `
        "$root\packaging\pyinstaller_entry.py"
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    $bundle = Join-Path $dist 'ScreenMagnet'
    $null = New-Item -ItemType Directory -Force -Path "$bundle\doubletake\bin"
    Copy-Item -LiteralPath $Sender -Destination "$bundle\doubletake\bin\doubletake.exe"
    foreach ($item in @('source', 'licenses', 'THIRD-PARTY-NOTICES.md')) {
        Copy-Item -LiteralPath (Join-Path $ReleaseData $item) -Destination $bundle -Recurse -Force
    }
    Copy-Item -LiteralPath "$root\LICENSE" -Destination "$bundle\LICENSE"
    Copy-Item -LiteralPath "$root\CHANGELOG.md" -Destination "$bundle\CHANGELOG.md"
    Copy-Item -LiteralPath $PrerequisiteManifest -Destination "$bundle\windows-prerequisites.json"
    @"
ScreenMagnet $version - Windows Preview

The Windows capture and audio sender was rebuilt from reconstructed source.
Real-TV video, audio synchronisation, and extended-display behavior still need
hardware validation. The self-test uses synthetic video only and never casts.

ScreenMagnet-Setup.exe is an ONLINE installer. It downloads missing prerequisites
directly from GStreamer and Microsoft (about 900 MB on a clean machine), then
checks release-pinned SHA-256 hashes before running them. GStreamer's unsigned
installer must match its reviewed official checksum; the Microsoft runtime must
also have a valid Authenticode signature.
An internet connection and administrator approval are required for setup.
Third-party installers are not included in this archive or installer.

Portable use: keep this entire ScreenMagnet directory together. Run the setup
once to install prerequisites, or install the official GStreamer 1.28.5 MSVC x64
runtime and Visual C++ x64 runtime yourself. ScreenMagnet finds their normal
install locations without changing your global PATH. SCREENMAGNET_GSTREAMER can
override a custom GStreamer root. GStreamer: https://gstreamer.freedesktop.org/download/

Sender pairing state is stored under LOCALAPPDATA\ScreenMagnet\sender-state.
The optional VirtualDrivers display driver is not included or installed by setup.

Verification: ScreenMagnet.exe --self-test --report PATH-TO-REPORT.json
See source/, licenses/, LICENSE, and THIRD-PARTY-NOTICES.md for source and notices.
"@ | Set-Content -LiteralPath "$bundle\WINDOWS-PREVIEW.txt" -Encoding UTF8
    if (!$Iscc) {
        $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        $Iscc = if ($command) { $command.Source } else { "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
    }
    & $Iscc "/DAppVersion=$version" "/DAppNumericVersion=$numericVersion" "$PSScriptRoot\installer.iss"
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }
    $archive = Join-Path $output 'ScreenMagnet-Windows-x64.zip'
    Compress-Archive -LiteralPath $bundle -DestinationPath $archive -Force
    foreach ($artifact in @('ScreenMagnet-Setup.exe', 'ScreenMagnet-Windows-x64.zip')) {
        $path = Join-Path $output $artifact
        if (!(Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing artifact: $artifact" }
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $artifact" | Set-Content -LiteralPath "$path.sha256" -Encoding ASCII
    }
    Write-Host "Windows preview artifacts created at $output"
} finally { Pop-Location }
