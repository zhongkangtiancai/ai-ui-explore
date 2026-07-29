@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev-backend.ps1"
exit /b %ERRORLEVEL%
