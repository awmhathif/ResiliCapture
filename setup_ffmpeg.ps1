[CmdletBinding()]
param([string]$Destination = '')

$ErrorActionPreference = 'Stop'
if (-not $Destination) { $Destination = Join-Path $PSScriptRoot 'bin' }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$version = '8.1.2'
$url = "https://github.com/GyanD/codexffmpeg/releases/download/$version/ffmpeg-$version-essentials_build.zip"
$expectedHash = 'db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec'
$work = Join-Path ([IO.Path]::GetTempPath()) ('ResiliCapture-FFmpeg-' + [guid]::NewGuid())

try {
    New-Item -ItemType Directory -Path $work | Out-Null
    $archive = Join-Path $work 'ffmpeg.zip'
    Write-Host "Downloading FFmpeg $version (about 104 MB)..."
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $url -OutFile $archive -UseBasicParsing -TimeoutSec 180
    $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $expectedHash) {
        throw 'FFmpeg checksum mismatch. Nothing has been installed.'
    }
    Expand-Archive -LiteralPath $archive -DestinationPath (Join-Path $work 'unpacked')
    $upstream = Join-Path $work "unpacked\ffmpeg-$version-essentials_build"
    foreach ($name in @('ffmpeg.exe', 'ffprobe.exe')) {
        $tool = Join-Path $upstream "bin\$name"
        if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) { throw "Missing $name in download." }
        & $tool -version | Select-Object -First 1 | Write-Host
        if ($LASTEXITCODE -ne 0) { throw "$name did not run successfully." }
    }
    $encoders = & (Join-Path $upstream 'bin\ffmpeg.exe') -hide_banner -encoders 2>&1
    if ($LASTEXITCODE -ne 0 -or -not ($encoders -match '\blibx264\b')) {
        throw 'Downloaded FFmpeg does not support software H.264.'
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    foreach ($name in @('ffmpeg.exe', 'ffprobe.exe')) {
        Copy-Item -LiteralPath (Join-Path $upstream "bin\$name") -Destination (Join-Path $Destination $name) -Force
    }
    $notices = Join-Path $Destination 'ffmpeg-notices'
    New-Item -ItemType Directory -Path $notices -Force | Out-Null
    Get-ChildItem -LiteralPath $upstream -File | Copy-Item -Destination $notices -Force
    @"
FFmpeg $version essentials build, downloaded directly from Gyan Doshi.
Upstream: https://www.gyan.dev/ffmpeg/builds/
Archive: $url
SHA256: $expectedHash
These separately downloaded executables are GPLv3, not ResiliCapture's MIT source.
Retain the upstream license/readme. See THIRD_PARTY_NOTICES.md before redistribution.
"@ | Set-Content -LiteralPath (Join-Path $notices 'DOWNLOAD.txt') -Encoding utf8
    Write-Host "Installed FFmpeg and FFprobe in $Destination"
} finally {
    # Only the uniquely created temporary directory is removed.
    $resolvedWork = [IO.Path]::GetFullPath($work)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if (-not $resolvedWork.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing cleanup outside the temporary directory.'
    }
    if (Test-Path -LiteralPath $resolvedWork) { Remove-Item -LiteralPath $resolvedWork -Recurse -Force }
}
