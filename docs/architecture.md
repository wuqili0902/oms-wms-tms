# OMS/WMS/TMS 系统架构

> 本文档为系统技术架构总览，基于当前代码实际结构（2026-08 核查）。功能性操作手册见根目录 `README.md`。

## 1. 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.12+ / Node 22 + TypeScript 5 |
| Web 框架 | FastAPI (ASGI, Uvicorn) |
| ORM | SQLAlchemy 2.0 async + Alembic 迁移 |
| 数据库 | PostgreSQL 16 (asyncpg)；开发/测试可用 SQLite |
| 缓存 / 消息 | Redis 7 |
| 后台任务 | Celery (Redis 为 broker) + Celery Beat 定时任务 |
| 指标监控 | Prometheus (`/metrics`) |
| 追踪 | OpenTelemetry OTLP |
| 错误上报 | Sentry (生产环境) |
| 前端 | Vue 3 + TS (Vite build) |
| 部署 | docker-compose / Helm (K8s) / GitHub Actions |

> 说明：RabbitMQ 已完全移除。Celery 以 Redis 为 broker，Outbox 事件通过 HTTP 派发。

## 2. 应用入口与路由挂载

入口：`src/main.py`。路由统一挂载于 FastAPI 实例。

| 前缀 | 路由 | 模块 |
|------|------|------|
| `/api/v1` | `auth_router` | `src/auth` |
| `/api/v1` | `oms_router` | `src/oms` |
| `/api/v1` | `wms_router` | `src/wms` |
| `/api/v1` | `barcode_router` | `src/barcode` |
| `/api/v1` | `logistics_router` | `src/logistics` |
| `/api/v1` | `tms_router` | `src/tms` |
| `/api/v1` | `mobile_router` | `src/api/v1/mobile.py` |
| `/api/v1` | `connectors_router` | `src/connectors` |
| `/api/v1` | `import_routes` | `src/core/_import` |
| `/api/v1` | `stock_router` | `src/stock` |
| (无前缀) | `notification_router` | `src/notification` |
| (无前缀) | `analytics_router` | `src/analytics` |
| (无前缀) | `admin_router` | `src/admin` (Jinja2 HTML 页面) |
| (无前缀) | `pda_router` | `src/pda` |
| (无前缀) | `webhooks_router` | `src/webhooks` |

健康检查：`/health` (根级，供容器探针)、`/api/v1` 下 `health_router`。

## 3. 中间件与横切关注点

中间件注册顺序（`src/main.py`，由内向外执行）：

1. `CORSMiddleware` — 跨域（`settings.cors_origins_list`）
2. `CsrfMiddleware` — 管理员 HTML 表单 CSRF 防护
3. `TraceContext` — 生成/传递 `trace_id`（最先，供下游中间件使用）
4. `RequestIDMiddleware` — 请求 ID
5. `RequestLoggingMiddleware` — 请求日志
6. `AuditLogMiddleware` — 写操作审计日志

统一错误响应：全局异常处理器把各类异常映射为 `error_response()`（`src/core/response.py`）。

## 4. 核心层（`src/core`）

| 文件 | 职责 |
|------|------|
| `database.py` | SQLAlchemy async 引擎、会话管理、后台任务独立会话 |
| `config.py` | Pydantic Settings，环境变量/.env 配置 |
| `security.py` | JWT 签发校验、密码哈希 (bcrypt) |
| `rate_limiter.py` | Redis 令牌桶限流（默认值来自 settings） |
| `outbox.py` | Outbox 事件表、追加/派发/标记，Celery 轮询 HTTP 派发 |
| `middleware.py` | Trace/RequestID/RequestLogging/AuditLog 中间件 |
| `response.py` | 统一成功/失败响应结构 |
| `exceptions.py` | 领域异常类型（App/Auth/NotFound/Validation/...） |
| `pagination.py` | 列表分页返回结构 |
| `csrf.py` | CSRF 中间件 |
| `tracing.py` / `export.py` / `import_utils.py` | 追踪 / 导出 / 导入工具 |
| `_import/` | 库存/订单导入路由 |

## 5. 业务域

### OMS — 订单管理 (`src/oms`)
- 模型：`Order`（含 priority/status）
- 能力：创建/更新订单、状态流转、订单拆分/合并（`src/oms/merge.py`）、地址解析
- outbox 事件：`ORDER_CREATED` 等

### WMS — 仓库作业 (`src/wms`)
- 仓库、库位、批次库存管理
- FEFO/FIFO 分配、ABC-XYZ 分析 (`analysis.py`)
- 拣货单 (`services/picking_service.py`)、收货/盘点/调整
- 单据类型：采购、退货、调拨、调整、销售出库

### PDA — 离线作业 (`src/pda`)
- 无网络环境下本地缓存（SQLite, `core/offline.py`）+ SyncQueue
- WebSocket 实时通道 (`ws.py`)
- 网络恢复自动同步

### TMS — 运输配送 (`src/tms`)
- 运输订单、ERP 对接 (`connectors/erp.py`)
- 需求预测 (`ml/forecast.py`)
- 推送服务 (`push_service.py`)、种子数据 (`seed.py`)

### 其他
- `src/barcode` — 条形码/GTIN 模板生成
- `src/logistics` — 物流承运商对接（bfia/carriers，含 Kefi 单号查询）
- `src/connectors` — 电商对接（Shopify webhook、Amazon SP-API）
- `src/notification` — WebSocket/邮件通知
- `src/analytics` — 分析查询
- `src/webhooks` — 外部 webhook 处理
- `src/stock` — 库存路由
- `src/admin` — 管理员 HTML 页面
- `src/models` — 共享/基础 ORM 模型（base、inventory、erp_connector、analytics 等）

## 6. 后台任务（Celery）

- `src/celery_app.py` — Celery 实例（Redis broker + result backend）
- `src/celeryconf.py` — Beat 定时调度（outbox 派发、低库存预警、过期 token 清理、日报聚合、未结订单处理等）
- `src/tasks/` — 各类任务的定义

## 7. 数据流（Outbox 一致性）

```
业务写操作 ──同事务──> outbox_events 表
                        │
                Celery/dashboard 轮询 overlay
                        │ fetch 100 pending
                        ▼
              HTTP POST → outbox_dispatch_url
                        │ 成功
                        ▼
               mark_dispatched / mark_failed
```

## 8. 部署

- `docker-compose.yml`：开发（PG + Redis + app + nginx）
- `deploy/docker-compose.prod.yml`：生产（postgres/redis/app/celery_worker/celery_beat/nginx）
- `deploy/helm/tms`：Helm chart（deployment、configmap、secret、ingress、hpa、migration-job、backup-cronjob）
- `.github/workflows/`：CI (ruff/mypy + pytest + 前端构建)、deploy

## 9. 测试

- `tests/` pytest + pytest-asyncio（anyio 后端）
- 本地默认 SQLite；CI 使用 PostgreSQL 16 + Redis 7
- E2E 测试 `tests/test_e2e/` 已纳入主套件