param(
    [switch]$Cleanup
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if ($Cleanup) {
    [Environment]::SetEnvironmentVariable("DTM_CLOUD", $null, "User")
    [Environment]::SetEnvironmentVariable("DTM_WORKSPACE_DIR", $null, "User")
    Write-Host "Updater-test environment settings cleared."
    Write-Host "Restore the Parallels snapshot to remove the test install and test data."
    exit 0
}

if ($env:OS -ne "Windows_NT") {
    throw "Run this script inside the Parallels Windows VM."
}

if (Get-Process -Name "DTM Vehicle Builder" -ErrorAction SilentlyContinue) {
    throw "Close DTM Vehicle Builder, then run this command again."
}

# The repository may be on a Parallels shared drive beside a Mac `.venv`.
# A separate Windows environment avoids modifying or confusing either one.
$WindowsVenv = Join-Path (Get-Location) ".venv-win-x64"
$WindowsPython = Join-Path $WindowsVenv "Scripts\python.exe"
$InnoCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)
$InnoCompiler = $InnoCandidates |
    Where-Object { $_ -and (Test-Path $_) } |
    Select-Object -First 1
if (!$InnoCompiler) {
    $InnoCommand = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($InnoCommand) {
        $InnoCompiler = $InnoCommand.Source
    }
}
if (!(Test-Path $WindowsPython)) {
    $PythonLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    $PythonPrefix = @("-3")
    if (!$PythonLauncher) {
        $PythonLauncher = Get-Command "python.exe" -ErrorAction SilentlyContinue
        $PythonPrefix = @()
    }
    # A default Windows install may expose a Microsoft Store placeholder as
    # python.exe. It looks like Python to Get-Command but cannot run a build.
    if ($PythonLauncher -and $PythonLauncher.Source -like "*\WindowsApps\python*.exe") {
        $PythonLauncher = $null
    }
}

$SetupCommands = @()
if (!(Test-Path $WindowsPython) -and !$PythonLauncher) {
    $SetupCommands += "winget install --exact --id Python.Python.3.12 --scope user"
}
if (!$InnoCompiler -or !(Test-Path $InnoCompiler)) {
    $SetupCommands += "winget install --exact --id JRSoftware.InnoSetup"
}
if ($SetupCommands.Count -gt 0) {
    Write-Host ""
    Write-Host "ONE-TIME SETUP NEEDED" -ForegroundColor Yellow
    Write-Host "Run the command(s) below, close and reopen PowerShell, then run this test again:"
    Write-Host ""
    foreach ($SetupCommand in $SetupCommands) {
        Write-Host $SetupCommand -ForegroundColor Cyan
    }
    exit 1
}

$PythonProbe = $WindowsPython
$PythonProbeArguments = @()
if (!(Test-Path $WindowsPython)) {
    $PythonProbe = $PythonLauncher.Source
    $PythonProbeArguments = $PythonPrefix
}
$DetectedArchitecture = & $PythonProbe @PythonProbeArguments -c "import sysconfig; print(sysconfig.get_platform().lower())"
if ($LASTEXITCODE -ne 0) {
    throw "Windows Python could not be checked."
}
if (($DetectedArchitecture | Select-Object -Last 1) -match "arm") {
    Write-Host ""
    Write-Host "ONE-TIME PYTHON CORRECTION NEEDED" -ForegroundColor Yellow
    Write-Host "Parallels installed ARM64 Python, but this test must build the x64 app used by your Windows users."
    Write-Host "Run these two commands, close and reopen PowerShell, then run this test again:"
    Write-Host ""
    Write-Host "winget uninstall --exact --id Python.Python.3.12" -ForegroundColor Cyan
    Write-Host "winget install --exact --id Python.Python.3.12 --architecture x64 --scope user" -ForegroundColor Cyan
    exit 1
}

if (!(Test-Path $WindowsPython)) {
    Write-Host "Creating a separate Windows build environment..."
    $PythonArguments = $PythonPrefix + @("-m", "venv", $WindowsVenv)
    & $PythonLauncher.Source @PythonArguments
    if ($LASTEXITCODE -ne 0 -or !(Test-Path $WindowsPython)) {
        throw "Windows could not create the build environment."
    }
}

$ProjectText = Get-Content "pyproject.toml" -Raw
if ($ProjectText -notmatch '(?m)^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"') {
    throw "Could not read the numeric app version from pyproject.toml."
}

$Major = [int]$Matches[1]
$Minor = [int]$Matches[2]
$Patch = [int]$Matches[3]
$FirstVersion = "$Major.$Minor.$($Patch + 1)"
$SecondVersion = "$Major.$Minor.$($Patch + 2)"

$TestWorkspace = Join-Path $env:LOCALAPPDATA "DTM-Updater-Test"
$BuildRoot = Join-Path $env:LOCALAPPDATA "DTM-Updater-Build"
$BuildDist = Join-Path $BuildRoot "dist"
$InstallerStore = Join-Path $env:TEMP "DTM-Updater-Test-Installers"
$Queue = Join-Path $TestWorkspace ".queued_installer"
$UpdateMarker = Join-Path $Queue "update-in-progress.json"

$env:DTM_WORKSPACE_DIR = $TestWorkspace
# This acceptance helper must stop at the first version and wait for the
# tester's button click. Production launches retain the normal boot-time
# fallback for updates left queued by a crash or power loss.
$env:DTM_UPDATER_TEST_MANUAL_ONLY = "1"
# Use the normal production cloud/sign-in path. Earlier revisions forced
# DTM_CLOUD=0, which proved the local installer mechanics but not the real
# signed-in desktop experience. The disposable installer is still injected
# only into the isolated local queue; it is never uploaded to Releases.
Remove-Item Env:DTM_CLOUD -ErrorAction SilentlyContinue
[Environment]::SetEnvironmentVariable("DTM_CLOUD", $null, "User")
[Environment]::SetEnvironmentVariable("DTM_WORKSPACE_DIR", $TestWorkspace, "User")

New-Item -ItemType Directory -Force $InstallerStore | Out-Null
New-Item -ItemType Directory -Force $Queue | Out-Null
# A cancelled acceptance run may leave its disposable installer or handoff
# marker behind. Clear only updater-test artifacts from the isolated queue so
# the first test build cannot immediately consume yesterday's second build.
$PreviousUpdaterPid = 0
if (Test-Path $UpdateMarker) {
    try {
        $PreviousUpdaterState = Get-Content $UpdateMarker -Raw | ConvertFrom-Json
        $PreviousUpdaterPid = [int]$PreviousUpdaterState.pid
    } catch {
        $PreviousUpdaterPid = 0
    }
}
if ($PreviousUpdaterPid -gt 0 -and (Get-Process -Id $PreviousUpdaterPid -ErrorAction SilentlyContinue)) {
    throw "A previous updater test is still finishing. Wait one minute, close DTM if it opens, then run this command again."
}
Get-ChildItem $Queue -File -Filter "DTM_Vehicle_Builder_Setup-*.exe" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue
Remove-Item $UpdateMarker -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $Queue "run-windows-update.ps1") -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Building disposable version $FirstVersion..."
$FirstBuilt = Join-Path $BuildDist "DTM_Vehicle_Builder_Setup-$FirstVersion.exe"
Remove-Item $FirstBuilt -Force -ErrorAction SilentlyContinue
& ".\packaging\build_windows.ps1" -TestVersion $FirstVersion -PythonPath $WindowsPython -InnoCompiler $InnoCompiler -BuildRoot $BuildRoot -FastCompression -Incremental
if (!(Test-Path $FirstBuilt)) {
    throw "The first test installer was not created."
}
$FirstInstaller = Join-Path $InstallerStore "DTM_Vehicle_Builder_Setup-$FirstVersion.exe"
Copy-Item $FirstBuilt $FirstInstaller -Force

Write-Host ""
Write-Host "Building disposable update $SecondVersion..."
$SecondBuilt = Join-Path $BuildDist "DTM_Vehicle_Builder_Setup-$SecondVersion.exe"
Remove-Item $SecondBuilt -Force -ErrorAction SilentlyContinue
& ".\packaging\build_windows.ps1" -TestVersion $SecondVersion -PythonPath $WindowsPython -InnoCompiler $InnoCompiler -BuildRoot $BuildRoot -InstallerOnly -FastCompression
if (!(Test-Path $SecondBuilt)) {
    throw "The second test installer was not created."
}
$SecondInstaller = Join-Path $InstallerStore "DTM_Vehicle_Builder_Setup-$SecondVersion.exe"
Copy-Item $SecondBuilt $SecondInstaller -Force

Write-Host ""
Write-Host "Installing $FirstVersion. DTM will open when it is ready..."
$InstallOptions = @{
    FilePath = $FirstInstaller
    ArgumentList = @("/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1")
    PassThru = $true
}
$Install = Start-Process @InstallOptions
# Start-Process -Wait follows the app that Inno Setup launches and therefore
# does not return until DTM itself closes. Wait only for the installer process
# so the second installer can be queued while DTM remains open.
$Install.WaitForExit()
if ($Install.ExitCode -ne 0) {
    throw "The first installer stopped with exit code $($Install.ExitCode)."
}

# Do not queue the second installer until the first app has passed its
# boot-time queued-update check and is actually serving the UI. Copying it
# immediately after Inno exits races the newly launched app and can make the
# second installer run before the user ever sees the first version.
Write-Host "Waiting for $FirstVersion to finish opening..."
$ReadyDeadline = [DateTime]::UtcNow.AddMinutes(1)
$AppReady = $false
while ([DateTime]::UtcNow -lt $ReadyDeadline) {
    try {
        $ReadyResponse = Invoke-WebRequest -Uri "http://127.0.0.1:7655/" -UseBasicParsing -TimeoutSec 2
        if ($ReadyResponse.StatusCode -eq 200) {
            $AppReady = $true
            break
        }
    } catch {
        # Normal while the packaged app and its local server are starting.
    }
    Start-Sleep -Milliseconds 500
}
if (!$AppReady) {
    throw "DTM $FirstVersion did not finish opening within one minute."
}

$QueuedInstaller = Join-Path $Queue "DTM_Vehicle_Builder_Setup-$SecondVersion.exe"
Copy-Item $SecondInstaller $QueuedInstaller -Force

Write-Host ""
Write-Host "READY - the test is paused at $FirstVersion and will not install $SecondVersion without your input."
Write-Host ""
Write-Host "1. In DTM, wait up to one minute for the $SecondVersion update banner."
Write-Host "2. Sign in normally. Do not create or publish real work during this test."
Write-Host "3. Click Restart & Install. DTM should close, show installer progress, then reopen."
Write-Host "4. Confirm DTM shows v$SecondVersion and your test project is still there."
Write-Host ""
Write-Host "Keep Windows security enabled. Photograph any warning instead of bypassing it."
Write-Host "Restore the Parallels snapshot when you finish."
