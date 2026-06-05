@echo off
setlocal

set "ROOT=%~dp0"
set "SCRIPT=%ROOT%scripts\check-doc-encoding.ps1"

if not exist "%SCRIPT%" (
    echo Missing script: %SCRIPT%
    exit /b 1
)

where pwsh >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    pwsh -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
)

exit /b %ERRORLEVEL%
