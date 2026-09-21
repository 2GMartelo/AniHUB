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
CloseApplications=yes
RestartApplications=no
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

[CustomMessages]
russian.DeleteLibrary=Удалить и папку библиотеки?%n%n%1%n%nВ ней ваши арты, манга, книги и база. Это действие нельзя отменить.
english.DeleteLibrary=Also delete the library folder?%n%n%1%n%nIt holds your arts, manga, books and the database. This cannot be undone.
russian.DeleteSettings=Удалить настройки, логи и скачанные обновления AniHUB (%APPDATA%\AniHUB)?
english.DeleteSettings=Delete AniHUB settings, logs and downloaded updates (%APPDATA%\AniHUB)?

[Code]
{ The library folder is chosen by the user and stored in config.json ("library_path"). Uninstalling keeps everything unless the
  user says otherwise; a silent uninstall never deletes user data. }
function ReadLibraryPath(): String;
var
  Lines: TArrayOfString;
  I, P: Integer;
  S: String;
begin
  Result := '';
  if not LoadStringsFromFile(ExpandConstant('{userappdata}\AniHUB\config.json'), Lines) then Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    P := Pos('"library_path"', Lines[I]);
    if P > 0 then
    begin
      S := Copy(Lines[I], P + 14, MaxInt);
      P := Pos('"', S);
      if P = 0 then Exit;
      S := Copy(S, P + 1, MaxInt);
      P := Pos('"', S);
      if P = 0 then Exit;
      S := Copy(S, 1, P - 1);
      StringChangeEx(S, '\', '', True);
      Result := S;
      Exit;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Lib, Data: String;
begin
  if (CurUninstallStep <> usPostUninstall) or UninstallSilent then Exit;
  Lib := ReadLibraryPath();
  { only a folder that really is an AniHUB library (it has its database) is ever offered for deletion }
  if (Lib <> '') and FileExists(Lib + '\dbnihub.db') then
    if MsgBox(FmtMessage(CustomMessage('DeleteLibrary'), [Lib]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(Lib, True, True, True);
  Data := ExpandConstant('{userappdata}\AniHUB');
  if DirExists(Data) then
    if MsgBox(CustomMessage('DeleteSettings'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(Data, True, True, True);
end;
