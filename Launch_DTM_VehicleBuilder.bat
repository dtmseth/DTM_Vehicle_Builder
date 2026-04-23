@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setup required. Please run Setup_DTM_VehicleBuilder.bat before using the app.
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m dtm_buildsheet
