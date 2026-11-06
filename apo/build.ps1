# Builds SoundboardApo.dll (x64, release) into apo\build and runs the ring tests.
# Needs Visual Studio 2022 (Build Tools is enough) with the C++ workload and the Windows 11 SDK.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$out = Join-Path $here 'build'
New-Item -ItemType Directory -Force $out | Out-Null

$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'Visual Studio C++ build tools not found' }

$flags = '/nologo /std:c++20 /O2 /MT /W4 /WX /EHsc /permissive- /DUNICODE /D_UNICODE /DWIN32_LEAN_AND_MEAN /DNOMINMAX'
$script = @"
@call "$vs\VC\Auxiliary\Build\vcvars64.bat" >nul 2>nul || exit /b 1
cl $flags /LD "$here\src\apo.cpp" /Fe:SoundboardApo.dll /link /DEF:"$here\SoundboardApo.def" audiobaseprocessingobject.lib audiomediatypecrt.lib ole32.lib advapi32.lib /NODEFAULTLIB:atls.lib || exit /b 1
cl $flags "$here\src\capture.cpp" /Fe:SoundboardCapture.exe /link ole32.lib mmdevapi.lib version.lib || exit /b 1
cl $flags "$here\tests\ring_test.cpp" /Fe:ring_test.exe || exit /b 1
cl $flags "$here\tests\com_test.cpp" /Fe:com_test.exe /link audiobaseprocessingobject.lib audiomediatypecrt.lib ole32.lib advapi32.lib /NODEFAULTLIB:atls.lib || exit /b 1
"@
$cmdFile = Join-Path $out 'build.cmd'
Set-Content -Path $cmdFile -Value $script -Encoding ascii

Push-Location $out
try {
    cmd /c "`"$cmdFile`""
    if ($LASTEXITCODE) { throw "build failed ($LASTEXITCODE)" }
    & .\ring_test.exe
    if ($LASTEXITCODE) { throw 'ring tests failed' }
    & .\com_test.exe
    if ($LASTEXITCODE) { throw 'COM tests failed' }
} finally {
    Pop-Location
}
Write-Host "Built $out\SoundboardApo.dll"
