<#
CI: -ManifestOutput PATH -DownloadDirectory PATH [-Install]
Setup: -ManifestPath PATH -DownloadDirectory PATH -Install [-LogPath PATH]
Only CI creates the manifest. End-user downloads must match its SHA-256 values
and have a valid Windows Authenticode signature before any execution.
#>
[CmdletBinding(DefaultParameterSetName = 'Install')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Prepare')][string]$ManifestOutput,
    [Parameter(Mandatory, ParameterSetName = 'Install')][string]$ManifestPath,
    [Parameter(Mandatory)][string]$DownloadDirectory,
    [switch]$Install,
    [string]$LogPath
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProgressPreference = 'SilentlyContinue'
$restartRequired = $false
$transcribing = $false

function Assert-OfficialUrl([string]$Url, [string]$Id) {
    $uri = [Uri]$Url
    $allowed = if ($Id -eq 'gstreamer') { @('gstreamer.freedesktop.org') } else {
        @('aka.ms', 'download.visualstudio.microsoft.com', 'download.microsoft.com')
    }
    if ($uri.Scheme -ne 'https' -or $uri.Host -notin $allowed) {
        throw "Unexpected $Id prerequisite download origin: $Url"
    }
}

function Receive-OfficialFile([string]$Url, [string]$Destination, [string]$Id) {
    Assert-OfficialUrl $Url $Id
    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromMinutes(30)
    try {
        $response = $client.GetAsync($Url, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        try {
            $null = $response.EnsureSuccessStatusCode()
            $resolved = $response.RequestMessage.RequestUri.AbsoluteUri
            Assert-OfficialUrl $resolved $Id
            $inputStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
            try {
                $outputStream = [System.IO.File]::Create($Destination)
                try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
            } finally { $inputStream.Dispose() }
            return $resolved
        } finally { $response.Dispose() }
    } finally { $client.Dispose() }
}

function Assert-VerifiedInstaller([string]$Path, [string]$ExpectedHash) {
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($ExpectedHash -and $hash -ne $ExpectedHash.ToLowerInvariant()) {
        throw "SHA-256 mismatch for $Path. The prerequisite was not executed."
    }
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid') {
        throw "Authenticode verification failed for ${Path}: $($signature.Status). The prerequisite was not executed."
    }
    return $hash
}

function Find-GStreamer {
    $roots = @(
        "$env:ProgramFiles\gstreamer\1.0\msvc_x86_64",
        "$env:SystemDrive\gstreamer\1.0\msvc_x86_64"
    )
    foreach ($name in @('SCREENMAGNET_GSTREAMER', 'GSTREAMER_1_0_ROOT_MSVC_X86_64', 'GSTREAMER_ROOT_X86_64')) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) { $roots += $value }
    }
    foreach ($root in $roots) {
        $inspect = Join-Path $root 'bin\gst-inspect-1.0.exe'
        if (!(Test-Path -LiteralPath $inspect -PathType Leaf)) { continue }
        $versionText = (& $inspect --version 2>&1 | Out-String)
        if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '(\d+\.\d+\.\d+)') { continue }
        if ([Version]$Matches[1] -lt [Version]'1.28.5') { continue }
        $valid = $true
        foreach ($plugin in @('d3d11screencapturesrc', 'x264enc', 'wasapi2src')) {
            $null = & $inspect $plugin 2>&1
            if ($LASTEXITCODE -ne 0) { $valid = $false; break }
        }
        if ($valid) { return $root }
    }
    return $null
}

function Test-VcRuntime([string]$MinimumVersion) {
    $key = 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64'
    $value = Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
    if (!$value -or $value.Installed -ne 1) { return $false }
    try { return [Version]$value.Version.TrimStart('v') -ge [Version]$MinimumVersion } catch { return $false }
}

try {
    if ($env:OS -ne 'Windows_NT') { throw 'Prerequisite installation requires Windows.' }
    $DownloadDirectory = [System.IO.Path]::GetFullPath($DownloadDirectory)
    $null = New-Item -ItemType Directory -Force -Path $DownloadDirectory
    if ($LogPath) { $null = Start-Transcript -Path $LogPath -Force; $transcribing = $true }
    $preparing = $PSCmdlet.ParameterSetName -eq 'Prepare'
    if ($preparing) {
        $manifest = [ordered]@{
            schema_version = 1
            gstreamer = [ordered]@{
                url = 'https://gstreamer.freedesktop.org/data/pkg/windows/1.28.5/msvc/gstreamer-1.0-msvc-x86_64-1.28.5.exe'
                sha256 = ''; version = '1.28.5'
            }
            vcredist = [ordered]@{ url = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'; sha256 = ''; version = '' }
        }
    } else {
        $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
        if ($manifest.schema_version -ne 1) { throw 'Unsupported prerequisite manifest.' }
    }
    # VC++ first; GStreamer's bundled runtime does not replace this explicit check.
    foreach ($id in @('vcredist', 'gstreamer')) {
        $entry = $manifest.$id
        Assert-OfficialUrl $entry.url $id
        if (!$preparing -and $entry.sha256 -notmatch '^[a-fA-F0-9]{64}$') {
            throw "Missing or invalid pinned SHA-256 for $id."
        }
        $alreadyInstalled = if ($id -eq 'gstreamer') { [bool](Find-GStreamer) } else {
            if ($entry.version) { Test-VcRuntime $entry.version } else { $false }
        }
        if (!$preparing -and $alreadyInstalled) {
            Write-Host "$id is already installed and meets the runtime checks."
            continue
        }
        $path = Join-Path $DownloadDirectory "$id.exe"
        Write-Host "Downloading $id from its official publisher..."
        $resolved = Receive-OfficialFile $entry.url $path $id
        $hash = Assert-VerifiedInstaller $path $entry.sha256
        if ($preparing) {
            $entry.url = $resolved
            $entry.sha256 = $hash
            if ($id -eq 'vcredist') {
                $productVersion = (Get-Item -LiteralPath $path).VersionInfo.ProductVersion
                if ($productVersion -notmatch '\d+\.\d+\.\d+\.\d+') { throw 'VC++ installer has no usable version metadata.' }
                $entry.version = $Matches[0]
                $alreadyInstalled = Test-VcRuntime $entry.version
            }
        }
        if ($Install -and !$alreadyInstalled) {
            if ($id -eq 'gstreamer') {
                $installRoot = "$env:ProgramFiles\gstreamer\1.0\msvc_x86_64"
                $arguments = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ALLUSERS /DIR="' + $installRoot + '"'
            } else { $arguments = '/install /quiet /norestart' }
            Write-Host "Installing verified $id prerequisite..."
            $process = Start-Process -FilePath $path -ArgumentList $arguments -Wait -PassThru
            if ($process.ExitCode -eq 3010) { $restartRequired = $true }
            elseif ($process.ExitCode -ne 0) { throw "$id installer failed with exit code $($process.ExitCode)." }
            $verified = if ($id -eq 'gstreamer') { [bool](Find-GStreamer) } else { Test-VcRuntime $entry.version }
            if (!$verified) { throw "$id installation finished, but runtime checks still fail." }
        }
    }
    if ($preparing) {
        $destination = [System.IO.Path]::GetFullPath($ManifestOutput)
        $null = New-Item -ItemType Directory -Force -Path (Split-Path $destination -Parent)
        $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $destination -Encoding UTF8
        Write-Host "Verified prerequisite manifest written to $destination"
    }
    if ($transcribing) { $null = Stop-Transcript; $transcribing = $false }
    if ($restartRequired) { exit 3010 }
    exit 0
} catch {
    Write-Error -ErrorAction Continue $_
    if ($transcribing) { $null = Stop-Transcript }
    exit 1
}
