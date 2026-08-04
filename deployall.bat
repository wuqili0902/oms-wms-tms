@echo off
setlocal EnableExtensions
REM ============================================================
REM  OMS+WMS+TMS - one-shot build + deploy
REM
REM  Runs on a fresh machine:
REM    [1] check toolchain (Node / Docker)
REM    [2] build frontend (TypeScript -> frontend/dist)
REM    [3] ensure .env exists (with random DB passwords)
REM    [4] build backend image (pip deps + alembic migration)
REM    [5] start all services (app / celery / nginx / PG / Redis)
REM    [6] wait for health check
REM
REM  Usage:
REM    deployall.bat          full build + start
REM    deployall.bat down     stop and remove containers
REM    deployall.bat logs     tail logs
REM    deployall.bat up       skip build, start existing image
REM    deployall.bat rebuild  rebuild image then start
REM ============================================================

set "ROOT=%~dp0"
cd /d "%ROOT%"
set "COMPOSE_FILE=deploy\docker-compose.prod.yml"
set "COMPOSE_PROJECT_NAME=oms-wms-tms"

set "CMD=%~1"
if "%CMD%"=="" set "CMD=full"

REM ---- short commands that do not need a build ----
if "%CMD%"=="down" (
    docker compose -f %COMPOSE_FILE% -p %COMPOSE_PROJECT_NAME% --env-file .env down
    goto :eof
)
if "%CMD%"=="logs" (
    docker compose -f %COMPOSE_FILE% -p %COMPOSE_PROJECT_NAME% --env-file .env logs -f --tail=100
    goto :eof
)

echo.
echo ============================================================
echo   OMS+WMS+TMS  one-shot build + deploy
echo ============================================================
echo.

REM ---- [0] check toolchain ------------------------------------
set "ERR=0"
for /f "delims=" %%a in ('node --version 2^>nul') do set "NODE_VER=%%a"
for /f "delims=" %%a in ('npm --version 2^>nul') do set "NPM_VER=%%a"
for /f "delims=" %%a in ('docker --version 2^>nul') do set "DOCKER_VER=%%a"

echo Detected:
echo   Node   : %NODE_VER%     (frontend build needs 20.19+ / 22.12+)
echo   npm    : %NPM_VER%
echo   Docker : %DOCKER_VER%
echo.

if "%NODE_VER%"=="" (
    echo [ERROR] Node.js not found. Install Node 22 LTS: https://nodejs.org
    set "ERR=1"
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker is not running. Start Docker Desktop first.
    set "ERR=1"
)
if "%ERR%"=="1" exit /b 1

REM ---- [1] build frontend (skipped in "up" mode) ---------------
if not "%CMD%"=="up" (
    echo [1/5] Building frontend (npm ci + vite build) ...
    cd /d "%ROOT%frontend"
    call npm ci
    if errorlevel 1 (
        echo [ERROR] npm ci failed. Check network and retry.
        exit /b 1
    )
    call npm run build
    if errorlevel 1 (
        echo [ERROR] Frontend build failed. Fix TypeScript errors first.
        exit /b 1
    )
    if not exist "%ROOT%frontend\dist\index.html" (
        echo [ERROR] Build output missing: frontend\dist\index.html
        exit /b 1
    )
    echo   [OK] frontend built
    cd /d "%ROOT%"
) else (
    echo [1/5] Skipping frontend build (up mode), using existing frontend\dist
)

REM ---- [2] ensure .env ------------------------------------------
echo.
echo [2/5] Checking .env ...
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

REM ---- [3] generate DB passwords --------------------------------
echo.
echo [3/5] Preparing database passwords ...
set "PG_USER=postgres"
set "PG_PASSWORD="

for /f "usebackq delims=" %%a in (`powershell -NoProfile -Command "$chars='abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'; -join (1..24 | ForEach-Object { Get-Random -Maximum $chars.Length | ForEach-Object { $chars[$_] } })"`) do set "PG_PASSWORD=%%a"

if "%PG_PASSWORD%"=="" set "PG_PASSWORD=postgres"

echo   PG_USER           : %PG_USER%
echo   PG_PASSWORD       : %PG_PASSWORD%

REM ---- [4] build and start --------------------------------------
echo.
if "%CMD%"=="rebuild" (
    echo [4/5] Rebuilding image (--no-cache) ...
    docker compose -f %COMPOSE_FILE% -p %COMPOSE_PROJECT_NAME% --env-file .env build --no-cache
) else (
    echo [4/5] Building image ...
    docker compose -f %COMPOSE_FILE% -p %COMPOSE_PROJECT_NAME% --env-file .env build
)
if errorlevel 1 (
    echo [ERROR] Image build failed. See logs above.
    exit /b 1
)

echo [5/5] Starting services ...
docker compose -f %COMPOSE_FILE% -p %COMPOSE_PROJECT_NAME% --env-file .env up -d
if errorlevel 1 (
    echo [ERROR] Failed to start services. See logs above.
    exit /b 1
)

REM ---- [6] wait for health check ---------------------------------
echo.
echo Waiting for app readiness (max 120s) ...
set /a tries=0
:loop
set /a tries+=1
if %tries% gtr 120 (
    echo [WARN] Health check timed out. Run "deployall.bat logs" to inspect.
    echo        Common cause: empty SECRET_KEY or wrong DB password.
    exit /b 1
)
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:8000/api/v1/health' -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [OK] App is healthy.
    echo.
    echo   Frontend  : http://localhost/        (nginx)
    echo   API       : http://localhost:8000/api/v1
    echo   Health    : http://localhost:8000/api/v1/health
    echo   DB pass   : %PG_PASSWORD%
    echo.
    echo   Note: DB password is random per deploy. To pin it,
    echo         add PG_PASSWORD to .env.
    exit /b 0
)
timeout /t 2 /nobreak >nul
goto :loop
