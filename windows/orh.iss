#define MyAppName "OpenRemoteHub"
#define MyAppVersion "0.5.7"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\OpenRemoteHub
DefaultGroupName=OpenRemoteHub
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ORH-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\OpenRemoteHub.exe
DisableProgramGroupPage=yes

[Files]
Source: "..\build\windows\OpenRemoteHub\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{userprograms}\OpenRemoteHub"; Filename: "{app}\OpenRemoteHub.exe"
Name: "{userprograms}\OpenRemoteHub 停止"; Filename: "{app}\OpenRemoteHub.exe"; Parameters: "--stop"
Name: "{userstartup}\OpenRemoteHub"; Filename: "{app}\OpenRemoteHub.exe"; Parameters: "--serve"

[Run]
Filename: "{app}\OpenRemoteHub.exe"; Description: "打开 OpenRemoteHub"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\OpenRemoteHub.exe"; Parameters: "--stop"; Flags: runhidden
