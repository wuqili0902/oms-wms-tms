#!/usr/bin/env bash
# ============================================================================
# OMS-WMS-TMS 一键部署脚本
# 用法:
#   ./deploy.sh              — 首次部署（构建 + 启动）
#   ./deploy.sh stop         — 停止所有服务
#   ./deploy.sh restart      — 重启所有服务
#   ./deploy.sh logs         — 查看日志（实时跟踪）
#   ./deploy.sh status       — 查看服务状态
#   ./deploy.sh backup       — 手动备份数据库
#   ./deploy.sh restore FILE — 从备份恢复
#   ./deploy.sh destroy      — 停止并删除所有数据（危险！）
#   ./deploy.sh migrate      — 仅执行数据库迁移
#   ./deploy.sh update       — 拉取最新代码并重新部署
# ============================================================================
set -euo pipefail

# ---------- 配置 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/deploy/docker-compose.prod.yml"
ENV_FILE="${SCRIPT_DIR}/deploy/.env"
ENV_EXAMPLE="${SCRIPT_DIR}/deploy/.env.production.example"
BACKUP_DIR="${SCRIPT_DIR}/backups"
HEALTH_URL="http://localhost:8000/api/v1/health"
HEALTH_TIMEOUT=120

# ---------- 颜色 ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
step()  { echo -e "\n${CYAN}===> $*${NC}"; }

# ---------- 前置检查 ----------
check_prerequisites() {
    step "检查前置条件"

    if ! command -v docker &>/dev/null; then
        error "未找到 docker，请先安装 Docker"
        exit 1
    fi
    ok "Docker $(docker --version | awk '{print $3}' | tr -d ',')"

    # 检查 docker compose（v2）或 docker-compose（v1）
    if docker compose version &>/dev/null; then
        COMPOSE="docker compose"
        ok "Docker Compose $(docker compose version --short)"
    elif command -v docker-compose &>/dev/null; then
        COMPOSE="docker-compose"
        ok "Docker Compose $(docker-compose --version | awk '{print $NF}')"
    else
        error "未找到 docker compose，请安装 Docker Compose v2"
        exit 1
    fi

    # 检查 node（前端构建需要）
    if ! command -v node &>/dev/null; then
        warn "未找到 Node.js，将跳过前端构建（nginx 服务需要 frontend/dist）"
        SKIP_FRONTEND=true
    else
        ok "Node.js $(node --version)"
        SKIP_FRONTEND=false
    fi
}

# ---------- 环境配置 ----------
setup_env() {
    step "配置环境变量"

    if [[ ! -f "$ENV_FILE" ]]; then
        if [[ -f "$ENV_EXAMPLE" ]]; then
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            warn "已从模板创建 deploy/.env，请编辑填入真实值"
        else
            error "未找到 .env 模板文件"
            exit 1
        fi
    fi

    # 自动生成 SECRET_KEY（如果还是默认值）
    if grep -q "REPLACE_WITH_64_HEX_CHARS" "$ENV_FILE" 2>/dev/null; then
        local NEW_KEY
        NEW_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
        sed -i.bak "s/REPLACE_WITH_64_HEX_CHARS/${NEW_KEY}/" "$ENV_FILE"
        rm -f "${ENV_FILE}.bak"
        ok "已自动生成 SECRET_KEY"
    fi

    # 检查 PG_PASSWORD 是否已设置
    if grep -q "REPLACE_WITH_STRONG_DB_PASSWORD" "$ENV_FILE" 2>/dev/null; then
        error "请编辑 deploy/.env，将 PG_PASSWORD 替换为真实密码"
        exit 1
    fi

    ok "环境配置就绪"
}

# ---------- 构建前端 ----------
build_frontend() {
    if [[ "${SKIP_FRONTEND:-false}" == "true" ]]; then
        warn "跳过前端构建"
        return
    fi

    step "构建前端"

    local FE_DIR="${SCRIPT_DIR}/frontend"
    if [[ ! -d "$FE_DIR" ]]; then
        warn "未找到 frontend/ 目录，跳过前端构建"
        return
    fi

    cd "$FE_DIR"

    if [[ ! -d "node_modules" ]]; then
        info "安装前端依赖..."
        npm ci --prefer-offline 2>&1 | tail -3
    fi

    info "构建前端..."
    npm run build 2>&1 | tail -5

    if [[ -d "dist" ]]; then
        ok "前端构建完成 → frontend/dist/"
    else
        warn "前端构建可能失败，dist 目录不存在"
    fi

    cd "$SCRIPT_DIR"
}

# ---------- 构建 Docker 镜像 ----------
build_image() {
    step "构建 Docker 镜像"

    cd "$SCRIPT_DIR"
    docker build -f docker/Dockerfile -t oms-wms-tms:latest . 2>&1 | tail -5

    ok "镜像构建完成: oms-wms-tms:latest"
}

# ---------- 数据库迁移 ----------
run_migrate() {
    step "执行数据库迁移"

    # 先确保 PG 已启动
    $COMPOSE -f "$COMPOSE_FILE" up -d postgres 2>/dev/null
    info "等待 PostgreSQL 就绪..."
    sleep 5

    # 在 app 容器内执行迁移
    $COMPOSE -f "$COMPOSE_FILE" run --rm app alembic upgrade head 2>&1 | tail -10

    ok "数据库迁移完成"
}

# ---------- 启动服务 ----------
start_services() {
    step "启动全部服务"

    $COMPOSE -f "$COMPOSE_FILE" up -d 2>&1

    ok "服务启动完成"
}

# ---------- 健康检查 ----------
health_check() {
    step "健康检查（最多等待 ${HEALTH_TIMEOUT}s）"

    local elapsed=0
    while [[ $elapsed -lt $HEALTH_TIMEOUT ]]; do
        if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
            local resp
            resp=$(curl -sf "$HEALTH_URL" 2>/dev/null || echo '{}')
            ok "应用健康: $resp"
            return 0
        fi
        sleep 3
        elapsed=$((elapsed + 3))
        printf "."
    done

    echo ""
    warn "健康检查超时，查看日志排查: ./deploy.sh logs"
    return 1
}

# ---------- 完整部署 ----------
do_deploy() {
    echo -e "\n${CYAN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║   OMS-WMS-TMS 一键部署                  ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════╝${NC}\n"

    check_prerequisites
    setup_env
    build_frontend
    build_image

    # 先启动 PG/Redis，再迁移
    step "启动数据库和缓存"
    $COMPOSE -f "$COMPOSE_FILE" up -d postgres redis 2>&1
    info "等待基础设施就绪..."
    sleep 8

    run_migrate
    start_services

    # 等待 app 就绪后再启动 nginx（nginx 依赖 app）
    sleep 5
    $COMPOSE -f "$COMPOSE_FILE" up -d nginx 2>/dev/null

    health_check

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   部署成功！                              ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo "  API:       http://localhost:8000"
    echo "  前端:      http://localhost"
    echo "  健康检查:  $HEALTH_URL"
    echo ""
    echo "  管理命令:"
    echo "    ./deploy.sh logs      — 查看日志"
    echo "    ./deploy.sh status    — 服务状态"
    echo "    ./deploy.sh stop      — 停止服务"
    echo "    ./deploy.sh backup    — 备份数据库"
    echo ""
}

# ---------- 停止 ----------
do_stop() {
    step "停止所有服务"
    $COMPOSE -f "$COMPOSE_FILE" down
    ok "已停止"
}

# ---------- 重启 ----------
do_restart() {
    step "重启所有服务"
    $COMPOSE -f "$COMPOSE_FILE" restart
    ok "已重启"
    health_check || true
}

# ---------- 日志 ----------
do_logs() {
    $COMPOSE -f "$COMPOSE_FILE" logs -f --tail=100
}

# ---------- 状态 ----------
do_status() {
    step "服务状态"
    $COMPOSE -f "$COMPOSE_FILE" ps
    echo ""
    step "容器资源使用"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" \
        $($COMPOSE -f "$COMPOSE_FILE" ps -q 2>/dev/null) 2>/dev/null || true
    echo ""
    step "健康检查"
    curl -sf "$HEALTH_URL" 2>/dev/null && echo "" || warn "应用未响应"
}

# ---------- 备份 ----------
do_backup() {
    mkdir -p "$BACKUP_DIR"

    # 从 .env 读取配置
    source "$ENV_FILE" 2>/dev/null || true
    local PG_HOST="${PG_HOST:-localhost}"
    local PG_PORT="${PG_PORT:-5432}"
    local PG_USER="${PG_USER:-postgres}"
    local PG_DATABASE="${PG_DATABASE:-oms_wms_tms}"
    local PG_PASSWORD="${PG_PASSWORD:-}"

    local TIMESTAMP
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    local BACKUP_FILE="${BACKUP_DIR}/oms_wms_tms_${TIMESTAMP}.sql.gz"

    step "备份数据库 → $BACKUP_FILE"

    export PGPASSWORD="$PG_PASSWORD"
    docker exec -e PGPASSWORD="$PG_PASSWORD" \
        $($COMPOSE -f "$COMPOSE_FILE" ps -q postgres) \
        pg_dump -U "$PG_USER" -d "$PG_DATABASE" \
        --format=custom --compress=9 \
        2>/dev/null | gzip > "$BACKUP_FILE"

    # 清理 30 天前的备份
    find "$BACKUP_DIR" -name "oms_wms_tms_*.sql.gz" -mtime +30 -delete 2>/dev/null

    ok "备份完成: $(du -h "$BACKUP_FILE" | awk '{print $1}') — $BACKUP_FILE"
}

# ---------- 恢复 ----------
do_restore() {
    local BACKUP_FILE="${1:-}"
    if [[ -z "$BACKUP_FILE" || ! -f "$BACKUP_FILE" ]]; then
        error "用法: ./deploy.sh restore <备份文件路径>"
        echo ""
        echo "可用备份:"
        ls -lh "$BACKUP_DIR"/oms_wms_tms_*.sql.gz 2>/dev/null || echo "  （无备份）"
        exit 1
    fi

    step "从备份恢复: $BACKUP_FILE"
    warn "此操作将覆盖当前数据库，3 秒后开始..."
    sleep 3

    source "$ENV_FILE" 2>/dev/null || true
    local PG_USER="${PG_USER:-postgres}"
    local PG_DATABASE="${PG_DATABASE:-oms_wms_tms}"
    local PG_PASSWORD="${PG_PASSWORD:-}"

    gunzip -c "$BACKUP_FILE" | docker exec -i \
        -e PGPASSWORD="$PG_PASSWORD" \
        $($COMPOSE -f "$COMPOSE_FILE" ps -q postgres) \
        psql -U "$PG_USER" -d "$PG_DATABASE" -q 2>&1 | tail -5

    ok "恢复完成"
}

# ---------- 销毁 ----------
do_destroy() {
    echo -e "\n${RED}╔══════════════════════════════════════════╗${NC}"
    echo -e "${RED}║   警告: 即将删除所有服务和数据！          ║${NC}"
    echo -e "${RED}║   数据库和缓存数据将不可恢复              ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════╝${NC}"
    read -r -p "输入 YES 确认删除: " confirm
    if [[ "$confirm" != "YES" ]]; then
        info "已取消"
        return
    fi

    step "停止并删除所有容器和数据卷"
    $COMPOSE -f "$COMPOSE_FILE" down -v --remove-orphans
    ok "已销毁所有服务和数据"
}

# ---------- 更新部署 ----------
do_update() {
    step "拉取最新代码"
    cd "$SCRIPT_DIR"
    git pull origin master

    step "重新部署"
    do_deploy
}

# ---------- 入口 ----------
case "${1:-deploy}" in
    deploy)   do_deploy ;;
    stop)     do_stop ;;
    restart)  do_restart ;;
    logs)     do_logs ;;
    status)   do_status ;;
    backup)   do_backup ;;
    restore)  do_restore "${2:-}" ;;
    destroy)  do_destroy ;;
    migrate)  check_prerequisites; setup_env; run_migrate ;;
    update)   do_update ;;
    *)
        echo "用法: $0 {deploy|stop|restart|logs|status|backup|restore|destroy|migrate|update}"
        echo ""
        echo "  deploy              首次部署（构建 + 启动）"
        echo "  update              拉取最新代码并重新部署"
        echo "  stop                停止所有服务"
        echo "  restart             重启所有服务"
        echo "  logs                实时查看日志"
        echo "  status              查看服务状态和资源使用"
        echo "  backup              手动备份数据库"
        echo "  restore <file>      从备份恢复数据库"
        echo "  migrate             仅执行数据库迁移"
        echo "  destroy             停止并删除所有数据（危险！）"
        exit 1
        ;;
esac
