; Online Windows preview installer. Run build.ps1 with a verified prerequisite
; manifest; third-party prerequisite executables are never embedded.
#ifndef AppVersion
  #error AppVersion is required. Use packaging/windows/build.ps1.
#endif
#ifndef AppNumericVersion
  #error AppNumericVersion is required. Use packaging/windows/build.ps1.
#endif
#define AppName "ScreenMagnet"

[Setup]
AppId={{B37F0D9C-6C2B-4E36-9C6A-2F6E3B1E7F41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} Windows Preview
VersionInfoVersion={#AppNumericVersion}
AppPublisher=DMoneyManZ
AppPublisherURL=https://github.com/DMoneyManZ/ScreenMagnet
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=ScreenMagnet-Setup
SetupIconFile=..\..\app\assets\screenmagnet.ico
LicenseFile=dist\ScreenMagnet\LICENSE
InfoBeforeFile=dist\ScreenMagnet\WINDOWS-PREVIEW.txt
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
UninstallDisplayIcon={app}\ScreenMagnet.exe
CloseApplications=yes
WizardStyle=modern

[Files]
Source: "dist\ScreenMagnet\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "install-prerequisites.ps1"; Flags: dontcopy
Source: "dist\ScreenMagnet\windows-prerequisites.json"; Flags: dontcopy

[Run]
Filename: "{app}\ScreenMagnet.exe"; Description: "Launch ScreenMagnet Windows Preview"; Flags: nowait postinstall skipifsilent

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\ScreenMagnet.exe"; AppUserModelID: "io.screenmagnet.ScreenMagnet"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ScreenMagnet.exe"; Tasks: desktopicon; AppUserModelID: "io.screenmagnet.ScreenMagnet"

[Tasks]
Name: desktopicon; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Code]
var
  PrerequisitesReady: Boolean;
  PrerequisitesNeedRestart: Boolean;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
  Arguments: String;
begin
  Result := '';
  if PrerequisitesReady then exit;
  try
    ExtractTemporaryFile('install-prerequisites.ps1');
    ExtractTemporaryFile('windows-prerequisites.json');
    WizardForm.StatusLabel.Caption := 'Checking prerequisites; downloading missing official runtimes...';
    Arguments := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' +
      ExpandConstant('{tmp}\install-prerequisites.ps1') + '" -ManifestPath "' +
      ExpandConstant('{tmp}\windows-prerequisites.json') + '" -DownloadDirectory "' +
      ExpandConstant('{tmp}\screenmagnet-prerequisites') + '" -Install -LogPath "' +
      ExpandConstant('{tmp}\screenmagnet-prerequisites.log') + '"';
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      Arguments, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := 'Could not start prerequisite verification. Windows PowerShell is required.'
    else if (ExitCode <> 0) and (ExitCode <> 3010) then
      Result := 'Prerequisite verification or installation failed. Check your internet connection and the log: ' +
        ExpandConstant('{tmp}\screenmagnet-prerequisites.log')
    else begin
      PrerequisitesReady := True;
      PrerequisitesNeedRestart := ExitCode = 3010;
    end;
  except
    Result := GetExceptionMessage;
  end;
end;

function NeedRestart: Boolean;
begin
  Result := PrerequisitesNeedRestart;
end;
