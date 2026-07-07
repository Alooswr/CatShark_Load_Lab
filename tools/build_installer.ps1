param(
    [string]$Version = "0.2.0"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Resolve-Path (Join-Path $ProjectRoot "..\..\work\venv-bukong-load-tester\Scripts\python.exe")
$BuildRoot = Join-Path $ProjectRoot "build"
$DistRoot = Join-Path $ProjectRoot "dist"
$InstallerOut = Join-Path $ProjectRoot "installer"
$PayloadRoot = Join-Path $BuildRoot "installer_payload"
$InstallerExe = Join-Path $InstallerOut "BukongLoadTester-Setup-$Version.exe"

Push-Location $ProjectRoot

& $VenvPython tools\create_icon.py

if (Test-Path (Join-Path $DistRoot "BukongLoadTester")) {
    Remove-Item -LiteralPath (Join-Path $DistRoot "BukongLoadTester") -Recurse -Force
}
if (Test-Path $PayloadRoot) {
    Remove-Item -LiteralPath $PayloadRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $PayloadRoot -Force | Out-Null
New-Item -ItemType Directory -Path $InstallerOut -Force | Out-Null

& $VenvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name BukongLoadTester `
    --icon assets\app.ico `
    --add-data "assets\app.ico;assets" `
    run.py

$AppZip = Join-Path $PayloadRoot "app.zip"
if (Test-Path $AppZip) { Remove-Item -LiteralPath $AppZip -Force }
Compress-Archive -Path (Join-Path $DistRoot "BukongLoadTester\*") -DestinationPath $AppZip -Force

$InstallCmd = @'
@echo off
setlocal
set "APPDIR=%LOCALAPPDATA%\BukongLoadTester"
if exist "%APPDIR%" rmdir /S /Q "%APPDIR%"
mkdir "%APPDIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force '%~dp0app.zip' '%APPDIR%'"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0CreateShortcut.ps1"
echo Bukong Load Tester installed to %APPDIR%
'@

$ShortcutPs1 = @'
$ErrorActionPreference = "Stop"
$appDir = Join-Path $env:LOCALAPPDATA "BukongLoadTester"
$target = Join-Path $appDir "BukongLoadTester.exe"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Bukong Load Tester.lnk"
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $appDir
$shortcut.IconLocation = "$target,0"
$shortcut.Description = "Bukong Load Tester"
$shortcut.Save()
'@

Set-Content -Path (Join-Path $PayloadRoot "Install.cmd") -Value $InstallCmd -Encoding ASCII
Set-Content -Path (Join-Path $PayloadRoot "CreateShortcut.ps1") -Value $ShortcutPs1 -Encoding UTF8

$SedPath = Join-Path $BuildRoot "BukongLoadTesterInstaller.sed"
$Sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=1
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=Bukong Load Tester installed.
TargetName=$InstallerExe
FriendlyName=Bukong Load Tester Installer
AppLaunched=Install.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles
[Strings]
FILE0="Install.cmd"
FILE1="CreateShortcut.ps1"
FILE2="app.zip"
[SourceFiles]
SourceFiles0=$PayloadRoot
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
"@

Set-Content -Path $SedPath -Value $Sed -Encoding ASCII
& iexpress.exe /N /Q $SedPath
Write-Host $InstallerExe

Pop-Location
