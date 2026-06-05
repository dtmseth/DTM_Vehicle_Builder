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

[InstallDelete]
; Force-wipe PyInstaller's _internal directory before copying new files. This
; is what carries the dtm_buildsheet-{version}.dist-info/METADATA that
; importlib.metadata reads — if an old .dist-info survives the upgrade
; alongside the new one, get_embedded_version() returns the wrong number and
; the update banner keeps pestering the user about an "available" version
; they just installed. Running this between the uninstall poll loop and the
; [Files] copy guarantees a clean slate regardless of what the old
; uninstaller left behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#MyAppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Auto-launch the new version after install, INCLUDING silent installs (the
; auto-update path drives the installer in /VERYSILENT). Without dropping
; skipifsilent, silent installs would replace the binaries but never bring
; the app back up.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall

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
  InstallDir: String;
  WaitCount: Integer;
begin
  Result := True;
  if IsAlreadyInstalled() then
  begin
    UninstallExe := RemoveQuotes(GetUninstallString());
    Exec(UninstallExe, '/SILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
    // ewWaitUntilTerminated returns when the uninstaller process exits, but
    // Inno Setup uninstallers fork a helper that finishes the work AFTER the
    // main process exits (it has to delete unins000.exe itself). Without
    // waiting for the install directory to actually empty out, the new
    // install begins copying files while the old uninstall is still chewing
    // on them — producing a Frankenstein with mixed-version .dist-info and
    // a stale version string after over-installs.
    InstallDir := ExpandConstant('{autopf}\{#MyAppName}');
    for WaitCount := 1 to 60 do
    begin
      if not DirExists(InstallDir) then
        Break;
      Sleep(500);  // up to 30s total
    end;
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
