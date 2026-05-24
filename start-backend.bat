@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "BACKEND_DIR=%ROOT_DIR%backend"
set "VENV_PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Python virtual environment not found:
    echo         %VENV_PYTHON%
    echo.
    echo Please create the backend virtual environment first.
    pause
    exit /b 1
)

cd /d "%BACKEND_DIR%"

echo ==========================================
echo Starting Serana backend...
echo Backend dir: %BACKEND_DIR%
echo URL: http://0.0.0.0:8000
echo Press Ctrl+C to stop
echo ==========================================
echo.

"%VENV_PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

echo.
echo Backend process exited.
pause
