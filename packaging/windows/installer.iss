#define MyAppName "DTM Vehicle Builder"
#define MyAppVersion GetEnv("APP_VERSION") != "" ? GetEnv("APP_VERSION") : "1.0.0"
#define MyAppPublisher "DTM"
#define MyAppExeName "DTM Vehicle Builder.exe"
#define MyAppDir "..\..\dist\DTM Vehicle Builder"
#define MyIconFile "..\..\packaging\icons\app.ico"
#define MyAppId "8F3A2B1C-9D4E-4F5A-8B7C-1D2E3F4A5B6C"

[Setup]
AppId={{{#MyAppId}}
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
CloseApplications=yes
CloseApplicationsFilter=*.exe

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

// ── Helpers ───────────────────────────────────────────────────────────────────

function GetUninstallString(): String;
var
  Key: String;
  Str: String;
begin
  Key := 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{#MyAppId}_is1';
  Str := '';
  if not RegQueryStringValue(HKCU, Key, 'UninstallString', Str) then
    RegQueryStringValue(HKLM, Key, 'UninstallString', Str);
  Result := Str;
end;

function IsAlreadyInstalled(): Boolean;
begin
  Result := GetUninstallString() <> '';
end;

// ── Uninstall previous version before installing ──────────────────────────────
// Runs silently so the user sees a single smooth install experience.

function InitializeSetup(): Boolean;
var
  UninstallExe: String;
  ResultCode: Integer;
begin
  Result := True;
  if IsAlreadyInstalled() then
  begin
    UninstallExe := RemoveQuotes(GetUninstallString());
    Exec(UninstallExe, '/SILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
  end;
end;

// ── Wipe workspace bundled-data dirs before seeding fresh ones ────────────────
// Preserves output/, input/, and drafts/ (user-created files).
// Everything else in the workspace is app-managed and must be fresh.

procedure CurStepChanged(CurStep: TSetupStep);
var
  Root: String;
  I: Integer;
  Dirs: TArrayOfString;
begin
  if CurStep = ssInstall then
  begin
    Root := ExpandConstant('{userappdata}\DTM Vehicle Builder');
    SetArrayLength(Dirs, 3);
    Dirs[0] := Root + '\config';
    Dirs[1] := Root + '\assets';
    Dirs[2] := Root + '\templates';
    for I := 0 to GetArrayLength(Dirs) - 1 do
    begin
      if DirExists(Dirs[I]) then
        DelTree(Dirs[I], True, True, True);
    end;
  end;
end;
