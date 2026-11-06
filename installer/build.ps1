# Builds the whole release: the mic plugin DLL, the app (PyInstaller) and dist\Soundboard-Setup-<version>.exe.
#   installer\build.ps1                 version from pyproject.toml
#   installer\build.ps1 -Version 1.2.0  (the GitHub release workflow passes the tag)
# Needs: Visual Studio C++ build tools + Windows SDK, Python with requirements-dev.txt, Inno Setup 6.
param([string]$Version = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

if (-not $Version) {
    $Version = (Select-String -Path "$root\pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
}
$Version = $Version.TrimStart('v')
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version must look like 1.2.3, got '$Version'" }
Write-Host "Building Soundboard $Version"

$python = if (Test-Path "$root\.venv\Scripts\python.exe") { "$root\.venv\Scripts\python.exe" } else { 'python' }

# 1. The mic plugin (also runs its native tests).
& "$root\apo\build.ps1"
if ($LASTEXITCODE) { throw 'Building the mic plugin failed' }

$work = "$root\installer\build"
New-Item -ItemType Directory -Force $work | Out-Null

# 2. Programs the app runs, shipped in tools\ so nothing needs installing separately
#    (soundboard/tools.py finds them). Downloads are cached and checked against published SHA-256 sums.
$DenoVersion = 'v2.9.8'
$FfmpegZip = 'ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip'  # LGPL, ffmpeg + ffprobe sharing one set of DLLs
$ProgressPreference = 'SilentlyContinue'

function Get-Verified([string]$url, [string]$name, [string]$expectedHash) {
    $file = "$work\downloads\$name"
    New-Item -ItemType Directory -Force "$work\downloads" | Out-Null
    if (-not (Test-Path $file) -or (Get-FileHash $file -Algorithm SHA256).Hash -ne $expectedHash.ToUpper()) {
        Write-Host "Downloading $name"
        Invoke-WebRequest $url -OutFile $file -UseBasicParsing
    }
    $actual = (Get-FileHash $file -Algorithm SHA256).Hash
    if ($actual -ne $expectedHash.ToUpper()) { throw "$name failed its checksum ($actual)" }
    return $file
}

function Get-PublishedHash([string]$url, [string]$name) {
    $text = (Invoke-WebRequest $url -UseBasicParsing).Content
    if ($text -is [byte[]]) { $text = [Text.Encoding]::UTF8.GetString($text) }
    foreach ($line in $text -split "`n") {
        if ($line -match '([0-9a-fA-F]{64})' -and ($line -match [regex]::Escape($name) -or $text.Trim() -notmatch "`n")) {
            return $Matches[1]
        }
    }
    throw "No checksum for $name in $url"
}

$tools = "$work\tools"
Remove-Item $tools -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$tools\ffmpeg" | Out-Null

$denoBase = "https://github.com/denoland/deno/releases/download/$DenoVersion"
$denoZip = Get-Verified "$denoBase/deno-x86_64-pc-windows-msvc.zip" "deno-$DenoVersion.zip" `
    (Get-PublishedHash "$denoBase/deno-x86_64-pc-windows-msvc.zip.sha256sum" 'deno-x86_64-pc-windows-msvc.zip')
Expand-Archive $denoZip "$work\deno" -Force
Copy-Item "$work\deno\deno.exe" $tools

$ffBase = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest'
$ffZip = Get-Verified "$ffBase/$FfmpegZip" $FfmpegZip (Get-PublishedHash "$ffBase/checksums.sha256" $FfmpegZip)
Remove-Item "$work\ffmpeg" -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $ffZip "$work\ffmpeg" -Force
$ffDir = Get-ChildItem "$work\ffmpeg" -Directory | Select-Object -First 1
Copy-Item "$($ffDir.FullName)\bin\ffmpeg.exe", "$($ffDir.FullName)\bin\ffprobe.exe" "$tools\ffmpeg"
Copy-Item "$($ffDir.FullName)\bin\*.dll" "$tools\ffmpeg"
Copy-Item "$($ffDir.FullName)\LICENSE.txt" "$tools\ffmpeg\LICENSE.txt"
@"
Programs bundled with Soundboard
================================
deno.exe       deno $DenoVersion, https://github.com/denoland/deno (MIT license).
               The JavaScript runtime yt-dlp uses for YouTube.
ffmpeg\        FFmpeg 8.1, LGPL build from https://github.com/BtbN/FFmpeg-Builds
               ($FfmpegZip). Licence in ffmpeg\LICENSE.txt; source at https://ffmpeg.org.
"@ | Set-Content "$tools\README.txt" -Encoding utf8
& "$tools\ffmpeg\ffmpeg.exe" -hide_banner -loglevel error -version | Select-Object -First 1
& "$tools\deno.exe" --version | Select-Object -First 1

# 3. The app. The exe's file version (shown in Explorer's Details tab) comes from version-info.txt.
$v = $Version.Split('.') + '0'
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($($v -join ', ')), prodvers=($($v -join ', '))),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Ofek Tal'),
    StringStruct('FileDescription', 'Soundboard'),
    StringStruct('FileVersion', '$Version'),
    StringStruct('ProductName', 'Soundboard'),
    StringStruct('ProductVersion', '$Version'),
    StringStruct('OriginalFilename', 'Soundboard.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -Path "$work\version-info.txt" -Encoding utf8
& $python -m PyInstaller "$root\installer\soundboard.spec" --noconfirm --clean --distpath "$root\dist" --workpath "$work\pyinstaller"
if ($LASTEXITCODE) { throw 'PyInstaller failed' }
Copy-Item $tools "$root\dist\Soundboard\tools" -Recurse -Force

# 4. The setup exe.
$iscc = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 not found (winget install JRSoftware.InnoSetup)' }
& $iscc /Q "/DAppVersion=$Version" "$root\installer\soundboard.iss"
if ($LASTEXITCODE) { throw 'Inno Setup failed' }
Write-Host "Built $root\dist\Soundboard-Setup-$Version.exe" -ForegroundColor Green
