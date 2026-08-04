@echo off
setlocal EnableExtensions
REM ============================================================
REM  OMS+WMS+TMS - build script
REM
REM  Run on a NEW machine before deploying:
REM    [1] check toolchain (Node / Python)
REM    [2] build frontend (TypeScript -> frontend/dist)
REM    [3] install backend Python deps into .venv
REM    [4] run DB migrations (alembic upgrade head)
REM
REM  After this: run deployall.bat for Docker, or dev-start.bat
REM  for native uvicorn + vite.
REM ============================================================

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo.
echo ============================================================
echo   OMS+WMS+TMS  build (for deploying on a new machine)
echo ============================================================
echo.

REM ---- [0] check toolchain ------------------------------------
set "ERR=0"
for /f "delims=" %%a in ('node --version 2^>nul') do set "NODE_VER=%%a"
for /f "delims=" %%a in ('npm --version 2^>nul') do set "NPM_VER=%%a"
for /f "delims=" %%a in ('python --version 2^>nul') do set "PY_VER=%%a"

echo Detected:
echo   Node   : %NODE_VER%     (frontend needs 20.19+ / 22.12+)
echo   npm    : %NPM_VER%
echo   Python : %PY_VER%       (backend needs 3.12+)
echo   Docker : checked by deployall.bat
echo.

if "%NODE_VER%"=="" (
    echo [ERROR] Node.js not found. Install Node 22 LTS: https://nodejs.org
    set "ERR=1"
)
if "%PY_VER%"=="" (
    echo [ERROR] Python not found. Install Python 3.12: https://www.python.org/downloads/
    set "ERR=1"
)
if "%ERR%"=="1" exit /b 1

REM ---- [1] build frontend --------------------------------------
echo.
echo [1/4] Building frontend (npm ci + vite build) ...
cd /d "%ROOT%frontend"

echo   npm ci ...
call npm ci
if errorlevel 1 (
    echo [ERROR] npm ci failed. Check network / node_modules conflicts.
    exit /b 1
)

echo   vue-tsc + vite build ...
call npm run build
if errorlevel 1 (
    echo [ERROR] Frontend build failed. Fix TypeScript errors.
    exit /b 1
)

if not exist "%ROOT%frontend\dist\index.html" (
    echo [ERROR] Build output missing: frontend\dist\index.html
    exit /b 1
)
echo   [OK] frontend built -> frontend\dist

REM ---- [2] install backend Python deps --------------------------
cd /d "%ROOT%"
echo.
echo [2/4] Creating venv and installing backend deps ...
if not exist ".venv" (
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        exit /b 1
    )
)
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Failed to activate venv.
    exit /b 1
)

echo   pip install -e ".[dev,otel]" ...
call pip install --upgrade pip
call pip install -e ".[dev,otel]"
if errorlevel 1 (
    echo [ERROR] Backend deps install failed.
    exit /b 1
)
echo   [OK] backend deps installed

REM ---- [3] init .env if missing --------------------------------
if not exist ".env" (
    echo.
    echo [3/4] Creating .env ...
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo   [OK] Copied .env.example to .env
        echo   [!!] Edit SECRET_KEY and DB passwords in .env.
    ) else (
        echo   [WARN] No .env.example; create .env manually.
    )
) else (
    echo [3/4] .env already exists
)

REM ---- [4] run migrations ---------------------------------------
echo.
echo [4/4] Running migrations (alembic upgrade head) ...
call alembic upgrade head
if errorlevel 1 (
    echo [WARN] Migration failed. Possible causes:
    echo        - PostgreSQL not running locally (DATABASE_URL -> localhost:5432)
    echo        - wrong DB password in .env
    echo        For Docker deploys this step runs in the container; safe to ignore.
)

call deactivate >nul 2>&1
echo.
echo ============================================================
echo   Build finished.
echo ============================================================
echo   Next steps:
echo     Option A (recommended, Docker): run  deployall.bat
echo     Option B (native dev):           run  dev-start.bat
echo.
echo   If infra (PostgreSQL/Redis) was never started locally, run:
echo     docker compose up -d postgres redis
echo ============================================================
exit /b 0
