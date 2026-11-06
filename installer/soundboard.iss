; Inno Setup script for Soundboard-Setup-<version>.exe. Built by installer\build.ps1:
;   ISCC /DAppVersion=1.2.3 installer\soundboard.iss
; Installs the app (dist\Soundboard) and the mic plugin DLL, then puts the plugin on every mic.
; The uninstaller takes the plugin off every mic and restores each mic's own effects first.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6A560AB3-6B88-471E-A5B1-AFBA10C4A08D}
AppName=Soundboard
AppVersion={#AppVersion}
AppVerName=Soundboard {#AppVersion}
AppPublisher=Ofek Tal
DefaultDirName={autopf}\Soundboard
DisableProgramGroupPage=yes
DisableDirPage=auto
; The mic plugin is registered machine-wide and loaded by Windows Audio, so this needs admin.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Soundboard-Setup-{#AppVersion}
SetupIconFile=..\soundboard\assets\icon.ico
UninstallDisplayIcon={app}\Soundboard.exe
UninstallDisplayName=Soundboard
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "micplugin"; Description: "Add the mic plugin to my microphones (Discord and games hear your sounds, no virtual cable)"
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Soundboard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\apo\build\SoundboardApo.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\apo\build\SoundboardCapture.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Soundboard"; Filename: "{app}\Soundboard.exe"
Name: "{autodesktop}\Soundboard"; Filename: "{app}\Soundboard.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Soundboard.exe"; Parameters: "--admin install"; StatusMsg: "Adding the mic plugin to your microphones (audio pauses for a second)..."; Flags: runhidden waituntilterminated; Tasks: micplugin
Filename: "{app}\Soundboard.exe"; Description: "Start Soundboard"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallRun]
; Runs before the files are deleted: restores every mic, unregisters the plugin, restarts audio.
Filename: "{app}\Soundboard.exe"; Parameters: "--admin uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveMicPlugin"

[Code]
var
  AudioStopped: Boolean;

function RunNet(const Params: String): Boolean;
var
  Code: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\net.exe'), Params, '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

// On an upgrade, Windows Audio has the old plugin DLL loaded, so it can't be replaced.
// Stop audio for the moment the files are copied.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  AudioStopped := False;
  if FileExists(ExpandConstant('{app}\SoundboardApo.dll')) then
    AudioStopped := RunNet('stop audiosrv /y');
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // Never leave the PC without sound (the mic plugin step restarts it again anyway).
  if (CurStep = ssPostInstall) and AudioStopped then
    RunNet('start audiosrv');
end;
