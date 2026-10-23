#define MyAppName "DTM Vehicle Builder"
#define MyAppVersion GetEnv("APP_VERSION") != "" ? GetEnv("APP_VERSION") : "1.0.0"
#define MyAppPublisher "DTM"
#define MyAppExeName "DTM Vehicle Builder.exe"
#define MyAppDir GetEnv("DTM_BUILD_APP_DIR") != "" ? GetEnv("DTM_BUILD_APP_DIR") : "..\..\dist\DTM Vehicle Builder"
#define MyOutputDir GetEnv("DTM_BUILD_OUTPUT_DIR") != "" ? GetEnv("DTM_BUILD_OUTPUT_DIR") : "..\..\dist"
#define MyIconFile "..\..\packaging\icons\app.ico"
#define MyAppId "8F3A2B1C-9D4E-4F5A-8B7C-1D2E3F4A5B6C"

[Setup]
AppId={{{#MyAppId}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir={#MyOutputDir}
OutputBaseFilename=DTM_Vehicle_Builder_Setup
SetupIconFile={#MyIconFile}
#if GetEnv("DTM_BUILD_FAST_COMPRESSION") == "1"
Compression=lzma2/fast
SolidCompression=no
#else
Compression=lzma
SolidCompression=yes
#endif
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
CloseApplicationsFilter=*.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Force-wipe PyInstaller's app-managed _internal directory before copying new
; files. This prevents an over-install from retaining old Python modules,
; resources, or the runtime build-version marker. User data lives elsewhere
; and is not affected.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#MyAppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; The explicit Restart & Install path passes /RELAUNCH=1 and opens the new
; version after showing progress. A ready update applied during a normal app
; close passes /RELAUNCH=0, installs quietly, and respects the user's intent
; to leave DTM closed.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall; Check: ShouldRelaunchAfterInstall

[Code]

function ShouldRelaunchAfterInstall(): Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|1}') <> '0';
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
