@echo off
chcp 932 >nul 2>&1

REM OCR System - Startup Script (Windows)
REM ============================================================

echo.
echo [INFO] Starting OCR Accounting System...
echo.

REM Disable Docker Build Cloud to use local builder
SET BUILDX_NO_DEFAULT_LOAD=1

REM Check Docker Compose
WHERE docker >nul 2>&1
IF %ERRORLEVEL% EQU 0 (
    REM Use local builder to avoid Docker Build Cloud (Metal builder) path issues
    docker buildx use desktop-linux >nul 2>&1
    IF %ERRORLEVEL% NEQ 0 (
        docker buildx use default >nul 2>&1
    )

    WHERE docker-compose >nul 2>&1
    IF %ERRORLEVEL% EQU 0 (
        echo [INFO] Starting with Docker Compose...
        docker-compose -f "%~dp0docker-compose.yml" up --build
        goto :EOF
    )
    REM Try docker compose (v2)
    docker compose version >nul 2>&1
    IF %ERRORLEVEL% EQU 0 (
        echo [INFO] Starting with Docker Compose v2...
        docker compose -f "%~dp0docker-compose.yml" up --build
        goto :EOF
    )
)

echo [WARN] Docker not found. Starting in local mode...
echo.

REM === Backend ===
echo [INFO] Starting FastAPI backend (port 8000)...
cd /d "%~dp0backend"

IF NOT EXIST venv (
    python -m venv venv
)

call venv\Scripts\activate.bat

pip install -r requirements.txt -q

IF NOT EXIST .env (
    IF EXIST .env.example (
        copy .env.example .env
        echo [INFO] Created .env from .env.example
    )
)

IF NOT EXIST test-reports (
    mkdir test-reports
)

start "OCR Backend" /B cmd /c "venv\Scripts\activate.bat && uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload"

cd /d "%~dp0"

REM === Frontend ===
echo [INFO] Starting Next.js frontend (port 3000)...
cd /d "%~dp0frontend"

IF NOT EXIST node_modules (
    call npm install
)

start "OCR Frontend" /B npm run dev

cd /d "%~dp0"

echo.
echo [OK] Startup complete!
echo.
echo   Frontend :  http://localhost:3000
echo   Backend  :  http://localhost:8000
echo   API Docs :  http://localhost:8000/docs
echo   Tests    :  http://localhost:3000/test-results
echo   Report   :  http://localhost:8000/test-report/html
echo.
echo Press any key to exit (servers continue in background)
pause >nul
