# ============================================================================
# OMS-WMS-TMS 一键部署脚本 (Windows PowerShell)
# 用法:
#   .\deploy.ps1              — 首次部署（构建 + 启动）
#   .\deploy.ps1 stop         — 停止所有服务
#   .\deploy.ps1 restart      — 重启所有服务
#   .\deploy.ps1 logs         — 查看日志
#   .\deploy.ps1 status       — 查看服务状态
#   .\deploy.ps1 backup       — 手动备份数据库
#   .\deploy.ps1 restore FILE — 从备份恢复
#   .\deploy.ps1 destroy      — 停止并删除所有数据（危险！）
#   .\deploy.ps1 migrate      — 仅执行数据库迁移
#   .\deploy.ps1 update       — 拉取最新代码并重新部署
# ============================================================================
param(
    [Parameter(Position=0)]
    [ValidateSet("deploy","stop","restart","logs","status","backup","restore","destroy","migrate","update")]
    [string]$Command = "deploy",

    [Parameter(Position=1)]
    [string]$RestoreFile = ""
)

$ErrorActionPreference = "Stop"
$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ComposeFile = Join-Path $RootDir "deploy\docker-compose.prod.yml"
$EnvFile = Join-Path $RootDir "deploy\.env"
$EnvExample = Join-Path $RootDir "deploy\.env.production.example"
$BackupDir = Join-Path $RootDir "backups"
$HealthUrl = "http://localhost:8000/api/v1/health"
$HealthTimeout = 120

# ---------- 辅助函数 ----------
function Write-Step  { param([string]$Msg) Write-Host "`n===> $Msg" -ForegroundColor Cyan }
function Write-Ok    { param([string]$Msg) Write-Host "[OK]    $Msg" -ForegroundColor Green }
function Write-Warn  { param([string]$Msg) Write-Host "[WARN]  $Msg" -ForegroundColor Yellow }
function Write-Err   { param([string]$Msg) Write-Host "[ERROR] $Msg" -ForegroundColor Red }

function Invoke-Compose {
    & docker compose -f $ComposeFile @args
}

function Wait-ForHealthy {
    param([int]$Timeout = $HealthTimeout)
    $elapsed = 0
    while ($elapsed -lt $Timeout) {
        try {
            $resp = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3 -ErrorAction Stop
            Write-Ok "应用健康: $($resp | ConvertTo-Json -Compress)"
            return $true
        } catch {
            Start-Sleep -Seconds 3
            $elapsed += 3
            Write-Host "." -NoNewline
        }
    }
    Write-Host ""
    Write-Warn "健康检查超时，请查看日志: .\deploy.ps1 logs"
    return $false
}

# ---------- 前置检查 ----------
function Test-Prerequisites {
    Write-Step "检查前置条件"

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Err "未找到 docker，请先安装 Docker Desktop"
        exit 1
    }
    Write-Ok "Docker $((docker --version) -replace '.*version\s+([\d.]+).*','$1')"

    # 检查 docker compose
    try {
        $v = docker compose version --short 2>$null
        Write-Ok "Docker Compose $v"
    } catch {
        Write-Err "未找到 docker compose，请安装 Docker Compose v2"
        exit 1
    }
}

# ---------- 环境配置 ----------
function Initialize-Env {
    Write-Step "配置环境变量"

    if (-not (Test-Path $EnvFile)) {
        if (Test-Path $EnvExample) {
            Copy-Item $EnvExample $EnvFile
            Write-Warn "已从模板创建 deploy\.env，请编辑填入真实值"
        } else {
            Write-Err "未找到 .env 模板文件"
            exit 1
        }
    }

    # 自动生成 SECRET_KEY
    $content = Get-Content $EnvFile -Raw
    if ($content -match "REPLACE_WITH_64_HEX_CHARS") {
        $bytes = New-Object byte[] 32
        [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
        $key = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
        $content = $content -replace "REPLACE_WITH_64_HEX_CHARS", $key
        Set-Content -Path $EnvFile -Value $content -NoNewline
        Write-Ok "已自动生成 SECRET_KEY"
    }

    if ($content -match "REPLACE_WITH_STRONG_DB_PASSWORD") {
        Write-Err "请编辑 deploy\.env，将 PG_PASSWORD 替换为真实密码"
        exit 1
    }

    Write-Ok "环境配置就绪"
}

# ---------- 构建前端 ----------
function Build-Frontend {
    $feDir = Join-Path $RootDir "frontend"
    if (-not (Test-Path $feDir)) {
        Write-Warn "未找到 frontend/ 目录，跳过前端构建"
        return
    }

    Write-Step "构建前端"

    Push-Location $feDir
    try {
        if (-not (Test-Path "node_modules")) {
            Write-Host "安装前端依赖..."
            npm ci --prefer-offline 2>&1 | Select-Object -Last 3
        }
        Write-Host "构建前端..."
        npm run build 2>&1 | Select-Object -Last 5
        if (Test-Path "dist") {
            Write-Ok "前端构建完成"
        } else {
            Write-Warn "前端构建可能失败"
        }
    } finally {
        Pop-Location
    }
}

# ---------- 构建镜像 ----------
function Build-Image {
    Write-Step "构建 Docker 镜像"
    Push-Location $RootDir
    try {
        & docker build -f docker/Dockerfile -t oms-wms-tms:latest . 2>&1 | Select-Object -Last 5
        Write-Ok "镜像构建完成"
    } finally {
        Pop-Location
    }
}

# ---------- 迁移 ----------
function Invoke-Migrate {
    Write-Step "执行数据库迁移"
    Invoke-Compose up -d postgres 2>$null
    Write-Host "等待 PostgreSQL 就绪..."
    Start-Sleep -Seconds 5
    Invoke-Compose run --rm app alembic upgrade head 2>&1 | Select-Object -Last 10
    Write-Ok "数据库迁移完成"
}

# ---------- 启动服务 ----------
function Start-All {
    Write-Step "启动全部服务"
    Invoke-Compose up -d 2>&1
    Write-Ok "服务启动完成"
}

# ========== 命令实现 ==========

function Deploy {
    Write-Host "`n╔══════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║   OMS-WMS-TMS 一键部署                  ║" -ForegroundColor Cyan
    Write-Host "╚══════════════════════════════════════════╝`n" -ForegroundColor Cyan

    Test-Prerequisites
    Initialize-Env
    Build-Frontend
    Build-Image

    Write-Step "启动数据库和缓存"
    Invoke-Compose up -d postgres redis 2>&1
    Write-Host "等待基础设施就绪..."
    Start-Sleep -Seconds 8

    Invoke-Migrate
    Start-All

    Start-Sleep -Seconds 5
    try { Invoke-Compose up -d nginx 2>$null } catch {}

    $ok = Wait-ForHealthy

    Write-Host ""
    if ($ok) {
        Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Green
        Write-Host "║   部署成功！                              ║" -ForegroundColor Green
        Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Green
    } else {
        Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Yellow
        Write-Host "║   部署完成，但健康检查未通过              ║" -ForegroundColor Yellow
        Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  API:       http://localhost:8000"
    Write-Host "  前端:      http://localhost"
    Write-Host "  健康检查:  $HealthUrl"
    Write-Host ""
    Write-Host "  管理命令:"
    Write-Host "    .\deploy.ps1 logs      — 查看日志"
    Write-Host "    .\deploy.ps1 status    — 服务状态"
    Write-Host "    .\deploy.ps1 stop      — 停止服务"
    Write-Host "    .\deploy.ps1 backup    — 备份数据库"
    Write-Host ""
}

function Stop-All {
    Write-Step "停止所有服务"
    Invoke-Compose down
    Write-Ok "已停止"
}

function Restart-All {
    Write-Step "重启所有服务"
    Invoke-Compose restart
    Write-Ok "已重启"
    Wait-ForHealthy | Out-Null
}

function Show-Logs {
    Invoke-Compose logs -f --tail=100
}

function Show-Status {
    Write-Step "服务状态"
    Invoke-Compose ps
    Write-Host ""
    Write-Step "健康检查"
    try {
        $resp = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 5
        Write-Ok "$($resp | ConvertTo-Json -Compress)"
    } catch {
        Write-Warn "应用未响应"
    }
}

function Invoke-Backup {
    if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Path $BackupDir | Out-Null }

    # 从 .env 读取配置
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^([^#=]+)=(.*)$") {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }

    $pgUser = if ($env:PG_USER) { $env:PG_USER } else { "postgres" }
    $pgDb = if ($env:PG_DATABASE) { $env:PG_DATABASE } else { "oms_wms_tms" }
    $pgPass = if ($env:PG_PASSWORD) { $env:PG_PASSWORD } else { "" }
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $file = Join-Path $BackupDir "oms_wms_tms_$ts.sql.gz"

    Write-Step "备份数据库 → $file"

    $pgContainer = (Invoke-Compose ps -q postgres).Trim()
    & docker exec -e PGPASSWORD=$pgPass $pgContainer pg_dump -U $pgUser -d $pgDb --format=custom --compress=9 2>$null | & gzip > $file

    $size = (Get-Item $file).Length / 1MB
    Write-Ok "备份完成: $([math]::Round($size, 1)) MB — $file"
}

function Invoke-Restore {
    if (-not $RestoreFile -or -not (Test-Path $RestoreFile)) {
        Write-Err "用法: .\deploy.ps1 restore <备份文件路径>"
        Write-Host "`n可用备份:"
        Get-ChildItem $BackupDir -Filter "*.sql.gz" -ErrorAction SilentlyContinue |
            Format-Table Name, @{N="Size";E={"$([math]::Round($_.Length/1MB,1)) MB"}}, LastWriteTime
        exit 1
    }

    Write-Step "从备份恢复: $RestoreFile"
    Write-Warn "此操作将覆盖当前数据库，3 秒后开始..."
    Start-Sleep -Seconds 3

    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^([^#=]+)=(.*)$") {
            [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
        }
    }
    $pgUser = if ($env:PG_USER) { $env:PG_USER } else { "postgres" }
    $pgDb = if ($env:PG_DATABASE) { $env:PG_DATABASE } else { "oms_wms_tms" }
    $pgPass = if ($env:PG_PASSWORD) { $env:PG_PASSWORD } else { "" }
    $pgContainer = (Invoke-Compose ps -q postgres).Trim()

    & gunzip -c $RestoreFile | & docker exec -i -e PGPASSWORD=$pgPass $pgContainer psql -U $pgUser -d $pgDb -q 2>&1 | Select-Object -Last 5
    Write-Ok "恢复完成"
}

function Invoke-Destroy {
    Write-Host "`n╔══════════════════════════════════════════╗" -ForegroundColor Red
    Write-Host "║   警告: 即将删除所有服务和数据！          ║" -ForegroundColor Red
    Write-Host "║   数据库和缓存数据将不可恢复              ║" -ForegroundColor Red
    Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Red
    $confirm = Read-Host "输入 YES 确认删除"
    if ($confirm -ne "YES") {
        Write-Host "已取消" -ForegroundColor Cyan
        return
    }
    Write-Step "停止并删除所有容器和数据卷"
    Invoke-Compose down -v --remove-orphans
    Write-Ok "已销毁所有服务和数据"
}

function Invoke-Update {
    Write-Step "拉取最新代码"
    Push-Location $RootDir
    git pull origin master
    Pop-Location
    Deploy
}

# ========== 路由 ==========
switch ($Command) {
    "deploy"   { Deploy }
    "stop"     { Stop-All }
    "restart"  { Restart-All }
    "logs"     { Show-Logs }
    "status"   { Show-Status }
    "backup"   { Invoke-Backup }
    "restore"  { Invoke-Restore }
    "destroy"  { Invoke-Destroy }
    "migrate"  { Test-Prerequisites; Initialize-Env; Invoke-Migrate }
    "update"   { Invoke-Update }
}
