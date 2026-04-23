@echo off
cd /d "%~dp0"

echo.
echo ==========================================
echo   DTM Build Sheet v7 Setup
echo ==========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo python was not found on this machine.
    echo Install Python 3.11 or later from https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\" (
    echo Creating local virtual environment...
    python -m venv .venv
)

echo Installing v7 into .venv...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e .

if %errorlevel% == 0 (
    echo.
    echo v7 setup complete.
    echo You can now run Launch_DTM_VehicleBuilder.bat
    pause
    exit /b 0
)

echo.
echo v7 setup did not finish cleanly.
pause
