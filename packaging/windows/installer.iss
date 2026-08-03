; ScreenMagnet Windows installer.
;
; Bundles the PyInstaller-frozen app, the doubletake AirPlay sender, and
; chains the GStreamer runtime + VC++ redistributable as silent prerequisites
; so the end user needs nothing pre-installed. Build with:
;   ISCC packaging\windows\installer.iss
; (run PyInstaller first -- this expects dist\ScreenMagnet\ to already exist.)

#define AppName "ScreenMagnet"
#define AppVersion "0.1.0"
#define AppPublisher "DMoneyManZ"
#define AppURL "https://github.com/DMoneyManZ/ScreenMagnet"

[Setup]
AppId={{B37F0D9C-6C2B-4E36-9C6A-2F6E3B1E7F41}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=ScreenMagnet-Setup
SetupIconFile=..\..\app\assets\screenmagnet.ico
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Installing GStreamer/VC++ system-wide needs a genuine elevated token, so this
; requests it normally (the standard, expected UAC prompt most Windows
; installers show) rather than trying to dodge elevation.
PrivilegesRequired=admin
UninstallDisplayIcon={app}\ScreenMagnet.exe

[Files]
Source: "dist\ScreenMagnet\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs
Source: "vendor\doubletake.exe"; DestDir: "{app}\doubletake\bin"; Flags: ignoreversion
Source: "prereqs\gstreamer-1.0-msvc-x86_64-1.28.5.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "prereqs\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing the Visual C++ Runtime..."; Check: VCRedistNeedsInstall
Filename: "{tmp}\gstreamer-1.0-msvc-x86_64-1.28.5.exe"; Parameters: "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"; StatusMsg: "Installing GStreamer (this can take a few minutes)..."; Check: GStreamerNeedsInstall
Filename: "{app}\ScreenMagnet.exe"; Description: "Launch ScreenMagnet"; Flags: nowait postinstall skipifsilent

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\ScreenMagnet.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ScreenMagnet.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "SCREENMAGNET_DOUBLETAKE"; ValueData: "{app}\doubletake"; Flags: preservestringtype

[Code]
function GStreamerNeedsInstall(): Boolean;
begin
  Result := not FileExists(ExpandConstant('{pf}\gstreamer\1.0\msvc_x86_64\bin\gst-inspect-1.0.exe'));
end;

function VCRedistNeedsInstall(): Boolean;
var
  Installed: Cardinal;
begin
  Result := True;
  if RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64', 'Installed', Installed) then
    Result := (Installed <> 1);
end;
