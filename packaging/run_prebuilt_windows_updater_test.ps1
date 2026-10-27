$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($env:OS -ne "Windows_NT") {
    throw "Run this test inside the Parallels Windows VM."
}

if (Get-Process -Name "DTM Vehicle Builder" -ErrorAction SilentlyContinue) {
    throw "Close DTM Vehicle Builder, then run this test again."
}

$Installers = @(
    Get-ChildItem -File -Filter "DTM_Vehicle_Builder_Setup-*.exe" |
        Where-Object { $_.BaseName -match '^DTM_Vehicle_Builder_Setup-(\d+\.\d+\.\d+)$' } |
        Sort-Object { [version]([regex]::Match($_.BaseName, '(\d+\.\d+\.\d+)$').Groups[1].Value) }
)
if ($Installers.Count -ne 2) {
    throw "This folder must contain exactly two disposable DTM test installers."
}

$FirstInstaller = $Installers[0]
$SecondInstaller = $Installers[1]
$FirstVersion = [regex]::Match($FirstInstaller.BaseName, '(\d+\.\d+\.\d+)$').Groups[1].Value
$SecondVersion = [regex]::Match($SecondInstaller.BaseName, '(\d+\.\d+\.\d+)$').Groups[1].Value

$TestWorkspace = Join-Path $env:LOCALAPPDATA "DTM-Updater-Progress-Test"
$Queue = Join-Path $TestWorkspace ".queued_installer"
$UpdateMarker = Join-Path $Queue "update-in-progress.json"
New-Item -ItemType Directory -Force $Queue | Out-Null

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
    throw "A previous updater test is still running. Wait one minute and try again."
}

Get-ChildItem $Queue -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -like "DTM_Vehicle_Builder_Setup-*.exe" -or
        $_.Name -in @(
            "update-in-progress.json",
            "run-windows-update.ps1",
            "windows-update-window-ready"
        )
    } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$env:DTM_WORKSPACE_DIR = $TestWorkspace
$env:DTM_UPDATER_TEST_MANUAL_ONLY = "1"
Remove-Item Env:DTM_CLOUD -ErrorAction SilentlyContinue
[Environment]::SetEnvironmentVariable("DTM_CLOUD", $null, "User")
[Environment]::SetEnvironmentVariable("DTM_WORKSPACE_DIR", $TestWorkspace, "User")

Write-Host ""
Write-Host "Installing disposable DTM $FirstVersion..."
Write-Host "Watch for the branded DTM startup splash and changing status text."
$Install = Start-Process -FilePath $FirstInstaller.FullName -ArgumentList @(
    "/SILENT", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"
) -PassThru
$Install.WaitForExit()
if ($Install.ExitCode -ne 0) {
    throw "The first installer stopped with exit code $($Install.ExitCode)."
}

Write-Host "Waiting for DTM $FirstVersion to open..."
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
        # Normal while the disposable app is starting.
    }
    Start-Sleep -Milliseconds 500
}
if (!$AppReady) {
    throw "DTM $FirstVersion did not finish opening within one minute."
}

Copy-Item $SecondInstaller.FullName (Join-Path $Queue $SecondInstaller.Name) -Force

Write-Host ""
Write-Host "READY" -ForegroundColor Green
Write-Host "1. Wait up to one minute for the update banner in DTM."
Write-Host "2. Click Restart & Install."
Write-Host "3. Confirm the small DTM progress window appears before the main app closes."
Write-Host "4. Confirm it remains for the entire install; no separate installer window should appear."
Write-Host "5. Confirm the branded startup splash covers the final app startup."
Write-Host "6. Confirm the splash closes only when v$SecondVersion is fully visible."
Write-Host ""
Write-Host "Keep Windows security enabled. Restore your Parallels snapshot when finished."
