#define MyAppName "SmartTimers"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "SmartTimers"
#define MyAppExeName "SmartTimers.exe"

[Setup]
AppId={{A3F9E92C-9D34-4A4C-A1A7-7B5F2C20C9A1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=release
OutputBaseFilename=SmartTimers_Setup_v{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64 ia64
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "dist\SmartTimers.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
