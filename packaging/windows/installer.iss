#define MyAppName "DTM Vehicle Builder"
#define MyAppVersion "0.7.0"
#define MyAppPublisher "DTM"
#define MyAppExeName "DTM Vehicle Builder.exe"
#define MyAppDir "..\..\dist\DTM Vehicle Builder"
#define MyIconFile "..\..\packaging\icons\app.ico"

[Setup]
AppId={{8F3A2B1C-9D4E-4F5A-8B7C-1D2E3F4A5B6C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\..\dist
OutputBaseFilename=DTM_Vehicle_Builder_Setup
SetupIconFile={#MyIconFile}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#MyAppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// On upgrade, wipe the bundled-data directories (config + assets) from the
// user's AppData workspace so the app re-seeds fresh files on next launch.
// User output, drafts, and input files are preserved.
procedure CurStepChanged(CurStep: TSetupStep);
var
  WorkspaceRoot: String;
begin
  if CurStep = ssInstall then
  begin
    WorkspaceRoot := ExpandConstant('{userappdata}\DTM Vehicle Builder');
    if DirExists(WorkspaceRoot + '\config') then
      DelTree(WorkspaceRoot + '\config', True, True, True);
    if DirExists(WorkspaceRoot + '\assets') then
      DelTree(WorkspaceRoot + '\assets', True, True, True);
  end;
end;
