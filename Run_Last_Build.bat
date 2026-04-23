@echo off
cd /d "%~dp0"

echo.
echo ==========================================
echo   DTM Build Sheet v7
echo ==========================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo Local v7 virtual environment not found.
    echo Run Setup_DTM_VehicleBuilder.bat first.
    echo.
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m dtm_buildsheet.generator_cli

if %errorlevel% == 0 (
    for /f "delims=" %%f in ('dir /b /o-d "workspace\output\*_v7.pptx" 2^>nul') do (
        echo.
        echo Opening: workspace\output\%%f
        echo.
        start "" "workspace\output\%%f"
        exit /b 0
    )
)

echo.
echo The v7 generator did not finish cleanly.
pause
