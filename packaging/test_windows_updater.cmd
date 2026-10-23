@echo off
setlocal

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0test_windows_updater.ps1" %*
exit /b %ERRORLEVEL%
