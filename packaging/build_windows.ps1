$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

if (!(Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Run Setup_DTM_VehicleBuilder.command or create the venv first."
    exit 1
}

& ".venv\Scripts\python.exe" -m pip install -e ".[packaging-win]"
& ".venv\Scripts\python.exe" -m PyInstaller --clean "packaging/pyinstaller/DTM_VehicleBuilder.spec"

Write-Host ""
Write-Host "Build complete."
Write-Host "App output:"
Write-Host "  dist\DTM Vehicle Builder"
