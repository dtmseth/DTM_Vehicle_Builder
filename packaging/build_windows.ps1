$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

if (!(Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Run Setup_DTM_VehicleBuilder.command or create the venv first."
    exit 1
}

& ".venv\Scripts\python.exe" -m pip install -e ".[packaging-win]"

$ProjectText = Get-Content "pyproject.toml" -Raw
if ($ProjectText -match '(?m)^version\s*=\s*"([^"]+)"') {
    $env:APP_VERSION = $Matches[1]
} else {
    throw "Could not read project version from pyproject.toml"
}

& ".venv\Scripts\python.exe" -m PyInstaller --clean "packaging/pyinstaller/DTM_VehicleBuilder.spec"

& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "packaging\windows\installer.iss"

Write-Host ""
Write-Host "Build complete."
Write-Host "App output:"
Write-Host "  dist\DTM Vehicle Builder"
Write-Host "Installer:"
Write-Host "  dist\DTM_Vehicle_Builder_Setup.exe"
