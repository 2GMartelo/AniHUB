; Inno Setup script. Build with:  ISCC /DAppVersion=0.1.0 packaging\installer.iss
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6E1B2D3C-5A4F-4C8E-9B7A-3F2D1A0C9E11}
AppName=AniHUB
AppVersion={#AppVersion}
AppPublisher=AniHUB
DefaultDirName={autopf}\AniHUB
DefaultGroupName=AniHUB
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=AniHUB-Setup-{#AppVersion}
SetupIconFile=..\build\anihub.ico
UninstallDisplayIcon={app}\AniHUB.exe
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
LicenseFile=..\LICENSE

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AniHUB\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\AniHUB"; Filename: "{app}\AniHUB.exe"
Name: "{autodesktop}\AniHUB"; Filename: "{app}\AniHUB.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AniHUB.exe"; Description: "{cm:LaunchProgram,AniHUB}"; Flags: nowait postinstall skipifsilent

; Settings, library and downloaded data live in %APPDATA%\AniHUB and are deliberately kept on uninstall.
