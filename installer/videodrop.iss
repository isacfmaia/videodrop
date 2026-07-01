#define MyAppName "VideoDrop"
#define MyAppVersion "1.0.8"
#define MyAppPublisher "Isac Maia"
#define MyAppExeName "VideoDrop.exe"

[Setup]
AppId={{546F0E08-15D0-4BD7-A045-7A8E3A4A7D33}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\VideoDrop
DefaultGroupName=VideoDrop
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=VideoDrop-Setup
SetupIconFile=..\build\windows\videodrop.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "Atalhos:"; Flags: checkedonce
Name: "startup"; Description: "Iniciar o VideoDrop com o Windows"; GroupDescription: "Inicialização:"; Flags: unchecked

[Files]
Source: "..\dist\VideoDrop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\VideoDrop"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\VideoDrop"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\VideoDrop"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--no-open"; WorkingDir: "{app}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir o VideoDrop"; Flags: nowait postinstall skipifsilent
