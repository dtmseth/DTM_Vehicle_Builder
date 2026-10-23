@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_prebuilt_windows_updater_test.ps1"
exit /b %ERRORLEVEL%
