@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM ============================================================
REM  OMS+WMS+TMS - native deployment (NO Docker required)
REM
REM  Deploys the full stack on Windows using locally installed
REM  PostgreSQL + Redis, without Docker:
REM    [1] check toolchain (Python / Node)
REM    [2] check + start PostgreSQL and Redis
REM    [3] create database if missing
REM    [4] install backend deps (reuses .venv if present)
REM    [5] build frontend (or reuse frontend\dist)
REM    [6] run DB migrations
REM    [7] start backend (uvicorn) + frontend (vite) + Celery worker
REM
REM  Prerequisites (installed manually on the machine):
REM    - Python 3.12+  (https://www.python.org/downloads/)
REM    - Node 22 LTS   (https://nodejs.org)
REM    - PostgreSQL 16 (Windows installer: https://www.enterprisedb.com/downloads/postgresql-postgresql-downloads)
REM    - Redis for Windows (Memurai: https://www.memurai.com  or  MS Redis zip)
REM
REM  Usage:
REM    native-start.bat         full native deploy
REM    native-start.bat stop    stop backend + celery
REM ============================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

set "CMD=%~1"
if "%CMD%"=="" set "CMD=start"

if "%CMD%"=="stop" (
    taskkill /F /FI "IMAGENAME eq uvicorn.exe" >nul 2>&1
    taskkill /F /FI "IMAGENAME eq celery.exe" >nul 2>&1
    echo [OK] Stopped backend and celery.
    goto :eof
)

echo.
echo ============================================================
echo   OMS+WMS+TMS  native deploy (no Docker)
echo ============================================================
echo.

REM ---- [1] check toolchain ------------------------------------
set "ERR=0"
for /f "delims=" %%a in ('python --version 2^>nul') do set "PY_VER=%%a"
for /f "delims=" %%a in ('node --version 2^>nul') do set "NODE_VER=%%a"

echo Detected:
echo   Python : %PY_VER%
echo   Node   : %NODE_VER%
echo.

if "%PY_VER%"=="" (
    echo [ERROR] Python not found. Install Python 3.12+.
    set "ERR=1"
)
if "%NODE_VER%"=="" (
    echo [ERROR] Node not found. Install Node 22 LTS.
    set "ERR=1"
)
if "%ERR%"=="1" exit /b 1

REM ---- [2] check PostgreSQL + Redis ----------------------------
echo [1/6] Checking infrastructure (PostgreSQL / Redis) ...
set "PG_SERVICE="
for /f "delims=" %%a in ('net start 2^>nul ^| findstr /i "postgres"') do set "PG_SERVICE=running"

set "REDIS_SERVICE="
for /f "delims=" %%a in ('net start 2^>nul ^| findstr /i "redis"') do set "REDIS_SERVICE=running"
if not defined REDIS_SERVICE (
    for /f "delims=" %%a in ('net start 2^>nul ^| findstr /i "memurai"') do set "REDIS_SERVICE=running"
)

if not "%PG_SERVICE%"=="running" (
    echo   [WARN] PostgreSQL service not detected as running.
    echo          Install / start PostgreSQL first, or check .env DATABASE_URL.
    echo          Current: postgresql+asyncpg://postgres:postgres@localhost:5432/oms_wms_tms
)
if not "%REDIS_SERVICE%"=="running" (
    echo   [WARN] Redis service not detected as running.
    echo          Install Memurai, Redis for Windows, or start redis-server.
    echo          Current: redis://localhost:6379/0
)
echo   [DONE] infrastructure check complete (warnings above are advisory).

REM ---- [3] ensure .env -----------------------------------------
echo.
echo [2/6] Checking .env ...
if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo   [OK] Copied .env.example to .env
        echo   [!!] Edit SECRET_KEY in .env before continuing.
        pause
    ) else (
        echo   [ERROR] Neither .env nor .env.example found.
        exit /b 1
    )
) else (
    echo   [OK] .env already exists
)

REM ---- [4] create database if missing --------------------------
echo.
echo [3/6] Creating database if missing (oms_wms_tms) ...
REM Read PG connection from .env, fall back to defaults
set "PG_HOST=localhost"
set "PG_PORT=5432"
set "PG_USER=postgres"
set "PG_PASS=postgres"
set "PG_DB=oms_wms_tms"

set "PG_BIN="
for /d %%d in ("C:\Program Files\PostgreSQL\*") do set "PG_BIN=%%d\bin"
if defined PG_BIN (
    set "PGPASSWORD=%PG_PASS%"
    "%PG_BIN%\psql.exe" -w -h %PG_HOST% -p %PG_PORT% -U %PG_USER% -tAc "SELECT 1 FROM pg_database WHERE datname='%PG_DB%'" >"%TEMP%\pgcheck.txt" 2>nul
    set /p PGRESULT=<"%TEMP%\pgcheck.txt"
    if "!PGRESULT!"=="1" (
        echo   [OK] Database %PG_DB% already exists.
    ) else (
        echo   Creating database %PG_DB% ...
        "%PG_BIN%\psql.exe" -w -h %PG_HOST% -p %PG_PORT% -U %PG_USER% -c "CREATE DATABASE %PG_DB%"
        if errorlevel 1 (
            echo   [WARN] Could not create database. Check PG_PASS / pg_hba.conf.
        ) else (
            echo   [OK] Database %PG_DB% created.
        )
    )
    set "PGPASSWORD="
) else (
    echo   [WARN] psql.exe not found in C:\Program Files\PostgreSQL.
    echo          Create database manually if it does not exist.
)

REM ---- [5] install backend deps --------------------------------
echo.
echo [4/6] Installing backend dependencies ...
if not exist ".venv" (
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        exit /b 1
    )
)
call ".venv\Scripts\activate.bat"
call pip install -e ".[dev,otel]" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Backend deps install failed.
    exit /b 1
)
echo   [OK] backend deps ready

REM ---- [6] build frontend --------------------------------------
echo.
echo [5/6] Building frontend ...
cd /d "%ROOT%frontend"
call npm ci
if errorlevel 1 (
    echo [ERROR] npm ci failed.
    exit /b 1
)
call npm run build
if errorlevel 1 (
    echo [ERROR] Frontend build failed.
    exit /b 1
)
cd /d "%ROOT%"
echo   [OK] frontend built -> frontend\dist

REM ---- [7] run migrations --------------------------------------
echo.
echo [6/6] Running migrations ...
call alembic upgrade head
if errorlevel 1 (
    echo [WARN] Migration failed. Check PostgreSQL connection.
    exit /b 1
)
echo   [OK] migrations applied

call deactivate >nul 2>&1

REM ---- [8] start services ---------------------------------------
echo.
echo Starting services ...
echo   Starting backend  (uvicorn) on :8000
start "OMS-Backend" /D "%ROOT%" cmd /c ".start-backend.cmd"

echo   Starting celery worker (optional, for background jobs)
start "OMS-Celery" /D "%ROOT%" cmd /c ".start-celery.cmd"

echo   Starting frontend  (vite dev) on :5173
start "OMS-Frontend" /D "%ROOT%frontend" cmd /c ".start-frontend.cmd"

echo.
echo ============================================================
echo   Native deployment started.
echo ============================================================
echo   Backend  : http://localhost:8000/api/v1
echo   Frontend : http://localhost:5173     (vite dev server)
echo   API docs : http://localhost:8000/docs
echo   Health   : http://localhost:8000/api/v1/health
echo.
echo   Stop with:  native-start.bat stop
echo ============================================================
exit /b 0
