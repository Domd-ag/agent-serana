@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "BACKEND_DIR=%ROOT_DIR%backend"
set "VENV_PYTHON=%BACKEND_DIR%\venv\Scripts\python.exe"
set "ENV_FILE=%BACKEND_DIR%\.env"
set "ENV_EXAMPLE=%BACKEND_DIR%\.env.example"

if not exist "%ENV_FILE%" (
    if exist "%ENV_EXAMPLE%" (
        copy "%ENV_EXAMPLE%" "%ENV_FILE%" >nul
        echo [INFO] Created backend\.env from backend\.env.example
    )
)

if not exist "%VENV_PYTHON%" (
    echo [INFO] Python virtual environment not found, creating backend\venv ...
    py -3 -m venv "%BACKEND_DIR%\venv"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment. Please install Python 3 first.
        pause
        exit /b 1
    )
)

cd /d "%BACKEND_DIR%"

echo [INFO] Installing or updating backend dependencies ...
"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check your network or Python environment.
    pause
    exit /b 1
)

echo ==========================================
echo Starting Serana backend
echo Backend dir: %BACKEND_DIR%
echo Config file: %ENV_FILE%
echo Health: http://127.0.0.1:8000/health
echo API docs: http://127.0.0.1:8000/docs
echo LAN URL: http://%COMPUTERNAME%:8000
echo Press Ctrl+C to stop
echo ==========================================
echo.

"%VENV_PYTHON%" -m uvicorn app.main:app --host 0.0.0.0 --port 8000

echo.
echo Backend process exited.
pause
