@echo off
chcp 65001 >nul
echo ╔══════════════════════════════════════╗
echo ║  物流管理系统 - 开发模式启动          ║
echo ║  OMS · WMS · TMS                    ║
echo ╚══════════════════════════════════════╝
echo.

:: ── Start infrastructure (Postgres + Redis) ──
echo [1/3] 启动基础设施...
docker compose up -d postgres redis
if errorlevel 1 (
    echo ⚠ Docker 未运行，跳过基础设施启动
    echo   请确保 PostgreSQL ^(localhost:5432^) 和 Redis ^(localhost:6379^) 已可用
)

:: ── Start backend ──
echo [2/3] 启动后端 API (uvicorn)...
start "Backend" cmd /c "uvicorn src.main:app --reload --host 0.0.0.0 --port 8000"

:: ── Start frontend ──
echo [3/3] 启动前端开发服务器 (vite)...
start "Frontend" cmd /c "cd /d %~dp0frontend && npm run dev"

echo.
echo ✅ 后端: http://localhost:8000
echo ✅ 前端: http://localhost:5173
echo ✅ API 文档: http://localhost:8000/docs
echo.
