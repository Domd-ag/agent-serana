@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"

if not exist "%BACKEND%\test_api_flows.py" (
    echo Backend test entry not found: %BACKEND%\test_api_flows.py
    exit /b 1
)

cd /d "%BACKEND%" || exit /b 1

set "PYTHONUTF8=1"
set "PYTHONPATH=%CD%"

if "%~1"=="" (
    python -m unittest test_api_flows
) else (
    python -m unittest %*
)

exit /b %ERRORLEVEL%
