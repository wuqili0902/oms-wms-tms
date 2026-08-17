# 部署手册

## 目录

1. [环境要求](#1-环境要求)
2. [本地开发环境](#2-本地开发环境)
3. [Docker Compose 部署](#3-docker-compose-部署)
4. [Kubernetes Helm 部署](#4-kubernetes-helm-部署)
5. [数据库迁移](#5-数据库迁移)
6. [CI/CD 流水线](#6-cicd-流水线)
7. [备份与恢复](#7-备份与恢复)
8. [监控与告警](#8-监控与告警)
9. [故障排查](#9-故障排查)

---

## 1. 环境要求

| 组件 | 版本要求 |
|------|---------|
| Python | >= 3.12 |
| PostgreSQL | >= 16 |
| Redis | >= 7 |
| Node.js | >= 22（仅前端构建） |
| Docker | >= 24（容器化部署） |
| Helm | >= 3.12（K8s 部署） |

---

## 2. 本地开发环境

### 2.1 克隆并初始化

```bash
git clone https://github.com/wuqili0902/oms-wms-tms.git
cd oms-wms-tms

# 启动基础服务
docker run -d --name pg-dev -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=oms_wms_tms postgres:16-alpine
docker run -d --name redis-dev -p 6379:6379 redis:7-alpine

# 配置环境变量
cp .env.example .env
```

### 2.2 安装依赖

```bash
pip install -e ".[dev]"
alembic upgrade head

cd frontend && npm install
```

### 2.3 启动服务

```bash
# 终端 1: 后端 API
python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# 终端 2: 前端
cd frontend && npm run dev

# 终端 3: Celery Worker
celery -A src.celeryconf worker --loglevel=info --concurrency=4

# 终端 4: Celery Beat
celery -A src.celeryconf beat --loglevel=info
```

### 2.4 验证

```bash
curl http://localhost:8000/api/v1/health
python -m pytest tests/ -x -q
```

---

## 3. Docker Compose 部署

### 3.1 准备生产配置

```bash
cp deploy/.env.production.example deploy/.env
```

必填项：

```env
SECRET_KEY=<生成 32 位随机字符串: openssl rand -hex 32>
PG_USER=postgres
PG_PASSWORD=<强密码>
PG_DATABASE=oms_wms_tms
DATABASE_URL=postgresql+asyncpg://postgres:<密码>@postgres:5432/oms_wms_tms
DATABASE_SYNC_URL=postgresql://postgres:<密码>@postgres:5432/oms_wms_tms
REDIS_URL=redis://redis:6379/0
```

### 3.2 构建与启动

```bash
docker build -f docker/Dockerfile -t oms-wms-tms:latest .
cd deploy
docker compose -f docker-compose.prod.yml up -d
```

### 3.3 服务清单

| 服务 | 端口 | 资源 | 说明 |
|------|------|------|------|
| postgres | 5432 | 2 CPU / 2G | PostgreSQL 16 数据库 |
| redis | 6379 | 1 CPU / 1G | Redis 7 缓存/消息队列 |
| app | 8000 | 2 CPU / 1G | FastAPI 后端（4 worker） |
| celery_worker | - | 2 CPU / 1G | Celery 异步任务（4 并发） |
| celery_beat | - | 0.5 CPU / 256M | Celery 定时调度 |
| nginx | 80/443 | 0.5 CPU / 256M | Nginx 反向代理 |

### 3.4 常用操作

```bash
# 查看状态
docker compose -f docker-compose.prod.yml ps

# 查看日志
docker compose -f docker-compose.prod.yml logs -f app
docker compose -f docker-compose.prod.yml logs -f celery_worker

# 重启单个服务
docker compose -f docker-compose.prod.yml restart app

# 停止全部
docker compose -f docker-compose.prod.yml down

# 停止并清除数据（危险）
docker compose -f docker-compose.prod.yml down -v
```

---

## 4. Kubernetes Helm 部署

### 4.1 前置条件

- Kubernetes >= 1.25，Helm >= 3.12
- ingress-nginx + cert-manager 已安装
- kubectl 已配置集群访问

### 4.2 创建 Secret

```bash
kubectl create namespace oms-wms-tms

kubectl create secret generic oms-wms-tms-secret \
  --from-literal=SECRET_KEY=$(openssl rand -hex 32) \
  --from-literal=PG_PASSWORD=<强密码> \
  -n oms-wms-tms
```

### 4.3 安装

```bash
cd deploy/helm
helm dependency update tms/

helm upgrade --install oms-wms-tms tms/ \
  --namespace oms-wms-tms \
  --set postgresql.auth.postgresPassword=<PG密码> \
  --set postgresql.auth.database=oms_wms_tms \
  --set ingress.hosts[0].host=tms.your-domain.com \
  --set ingress.tls[0].hosts[0]=tms.your-domain.com \
  --set ingress.tls[0].secretName=tms-tls
```

### 4.4 K8s 资源清单

| 资源 | 说明 |
|------|------|
| Deployment (app) | 2~10 副本, HPA 自动扩缩 |
| Deployment (worker) | 2 副本, Celery Worker |
| Deployment (beat) | 1 副本, Celery Beat |
| Service | ClusterIP:8000 |
| Ingress | Nginx + TLS (cert-manager) |
| ConfigMap | 非敏感配置 |
| Secret | 敏感配置 (SECRET_KEY, DB, SMTP) |
| HPA | CPU 75% / Memory 80% 触发扩缩 |
| Migration Job | post-install/post-upgrade 钩子执行 alembic |
| Backup CronJob | 每日 02:00 pg_dump, 保留 30 天 |

### 4.5 常用操作

```bash
# 查看 Pod 状态
kubectl get pods -n oms-wms-tms

# 查看日志
kubectl logs -f deployment/oms-wms-tms -n oms-wms-tms

# 手动触发迁移
kubectl exec -it deployment/oms-wms-tms -n oms-wms-tms -- alembic upgrade head

# 扩缩容
kubectl scale deployment/oms-wms-tms --replicas=3 -n oms-wms-tms

# 卸载
helm uninstall oms-wms-tms -n oms-wms-tms
```

---

## 5. 数据库迁移

### 5.1 Alembic 基本操作

```bash
# 查看当前版本
alembic current

# 执行全部迁移
alembic upgrade head

# 回滚一步
alembic downgrade -1

# 查看迁移历史
alembic history

# 生成迁移（自动生成 diff）
alembic revision --autogenerate -m "描述"
```

### 5.2 注意事项

- 迁移链使用 SAVEPOINT 助手 `_best_effort()`，单步失败不会中止整个事务
- CI 中 `alembic upgrade head` 对全新 PG 验证迁移链完整性
- 生产环境迁移由 Helm migration-job 自动执行（post-install/post-upgrade hook）
- SQLite 仅用于测试，生产必须使用 PostgreSQL

---

## 6. CI/CD 流水线

### 6.1 CI (ci.yml)

触发条件：push to main/master/develop，PR to main/master

```
lint → test → frontend-build
```

| Job | 内容 |
|-----|------|
| lint | `ruff check src/ tests/` + mypy（soft fail） |
| test | 启动 PG 16 + Redis 7 → `alembic upgrade head` → `pytest tests/ -x` |
| frontend-build | `npm ci && npm run build` |

### 6.2 CD (deploy.yml)

触发条件：push to main/master，release

```
test → build-and-push → deploy
```

| Job | 内容 |
|-----|------|
| test | 同 CI |
| build-and-push | Docker Buildx 构建 → 推送 GHCR (`ghcr.io/wuqili0902/oms-wms-tms`) |
| deploy | `helm upgrade --install`（main/master 分支） |

镜像标签策略：
- `sha-<7位commit>` — 每次 push
- `<semver>` — release tag
- `branch-<name>` — 分支名

---

## 7. 备份与恢复

### 7.1 手动备份

```bash
# 备份（自定义压缩）
PGPASSWORD=<密码> pg_dump -h localhost -U postgres \
  --format=custom --compress=9 oms_wms_tms \
  > backup_$(date +%Y%m%d_%H%M%S).dump

# 备份为 SQL 文本
PGPASSWORD=<密码> pg_dump -h localhost -U postgres \
  --clean --if-exists oms_wms_tms \
  > backup_$(date +%Y%m%d_%H%M%S).sql
```

### 7.2 自动备份

Helm 部署已包含 CronJob（默认每日 02:00，保留 30 天）：

```bash
# 查看备份 CronJob
kubectl get cronjob -n oms-wms-tms

# 手动触发一次备份
kubectl create job --from=cronjob/oms-wms-tms-backup manual-backup-$(date +%s) -n oms-wms-tms
```

### 7.3 恢复

```bash
# 从 .dump 恢复
pg_restore -h localhost -U postgres -d oms_wms_tms --clean backup.dump

# 从 .sql 恢复
psql -h localhost -U postgres -d oms_wms_tms < backup.sql
```

---

## 8. 监控与告警

### 8.1 健康检查端点

```
GET /api/v1/health    — 完整检查（DB + Redis）
GET /api/v1/ready     — Readiness Probe（仅就绪状态）
```

K8s 已配置 liveness/readiness probe：
- liveness: `/api/v1/health`，period 30s
- readiness: `/api/v1/ready`，period 10s

### 8.2 可观测性

| 组件 | 配置项 |
|------|--------|
| Sentry | `SENTRY_DSN` — 异常追踪 |
| OpenTelemetry | `OTEL_EXPORTER_OTLP_ENDPOINT` — 分布式链路追踪 |
| 日志 | JSON 格式, `LOG_LEVEL=info`, max 10MB rotation |

### 8.3 速率限制

```env
RATE_LIMIT_REQUESTS=100   # 窗口内最大请求数
RATE_LIMIT_WINDOW=60       # 时间窗口（秒）
```

开发环境自动绕过（`settings.testing = True`）。

---

## 9. 故障排查

### 9.1 应用启动失败

```bash
# 检查日志
docker compose -f docker-compose.prod.yml logs app --tail=100

# 常见原因：
# 1. DATABASE_URL 连接失败 → 检查 PG 是否启动、密码是否正确
# 2. REDIS_URL 连接失败 → 检查 Redis 是否启动
# 3. SECRET_KEY 未设置 → 必须设置 >= 32 字符
# 4. alembic 迁移未执行 → alembic upgrade head
```

### 9.2 数据库连接满

```env
# 调整连接池
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
```

```bash
# 查看当前连接数
docker exec oms-wms-tms-postgres psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"
```

### 9.3 Celery 任务不执行

```bash
# 检查 Redis 连接
docker exec oms-wms-tms-redis redis-cli ping

# 检查 Worker 状态
docker exec oms-wms-tms-celery_worker celery -A src.celeryconf inspect active

# 查看计划任务
docker exec oms-wms-tms-celery_worker celery -A src.celeryconf inspect scheduled

# 重启 Worker
docker compose -f docker-compose.prod.yml restart celery_worker
```

### 9.4 Nginx 502 Bad Gateway

```bash
# 检查 app 是否健康
docker compose -f docker-compose.prod.yml ps app

# 检查端口是否暴露
docker compose -f docker-compose.prod.yml port app 8000

# Nginx upstream 配置
cat docker/nginx/default.conf
```

### 9.5 前端页面空白

1. 确认后端 API 正常：`curl http://<host>/api/v1/health`
2. 检查 `CORS_ORIGINS` 是否包含前端域名
3. 浏览器 DevTools → Network → 检查 401/403

### 9.6 性能调优建议

| 配置 | 开发环境 | 生产环境 |
|------|---------|---------|
| DB_POOL_SIZE | 5 | 20 |
| DB_MAX_OVERFLOW | 5 | 10 |
| Celery concurrency | 2 | 4 |
| App workers | 1 | 4 |
| Redis maxmemory | 256MB | 1GB |
| Rate limit | 1000/60s | 100/60s |
