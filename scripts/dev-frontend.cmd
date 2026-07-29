@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev-frontend.ps1"
exit /b %ERRORLEVEL%
