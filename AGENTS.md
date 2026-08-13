# AGENTS.md

## 项目定位
OMS-WMS-TMS 一体化物流平台。FastAPI + SQLAlchemy async + PostgreSQL + Redis + Celery 后端,Vue3 + TS 前端。约 19818 文件、40+ 模块。

## 双工具工作流(重要)

本机本地推理能力有限(16GB VRAM,一次只能加载一个模型),因此采用**双工具分工**,**禁止**混用:

| 阶段 | 工具 | 模型 | 说明 |
|------|------|------|------|
| 规划 / 方案 / 架构 / 分析 | Claude Code | 35B-A3B (Q4, 全显存 90+ t/s) | 视野宽,方案全面 |
| 编码 / 修 bug / 重构 | opencode | 9B-Coder-MTP (Q8, 43-53 t/s) | 不乱改正确代码 |
| 疑难 bug 兜底 | opencode / deep | 云端 DeepSeek | 本地搞不定时 |

**模型能力边界(实测结论,必须遵守):**
- 35B-A3B:适合"动脑"(规划/分析),**禁止让它直接改代码**——实测会把正确代码改坏且不自知。
- 9B-Coder-MTP:适合"动手"(编码),会逐步验证、不乱改。
- 9B-Coder-MTP **不能用于 Claude Code**(Anthropic 协议不兼容),反之 35B-A3B 配 opencode 编码同样危险。

## 上下文交接协议(关键)

两个工具各自独立会话、模型切换有冷启动开销,因此**规划产出必须落盘**:

1. 规划阶段(Claude Code + 35B)产出方案文档到 `docs/`:
   - `docs/plan-<feature>.md` — 技术方案、数据模型、里程碑
   - 关键设计决策写进文档,**不要只留在对话里**
2. 编码阶段(opencode + 9B)开工前**先读方案**:
   - 首个动作是 `Read docs/plan-<feature>.md`,再开始实现
   - 若方案不存在,先向用户确认是"没有规划"还是"让我现做"

## 编码约定

- 遵循项目既有代码风格,不引入未使用的新依赖
- 修改前先理解模块职责(src/oms, src/wms, src/tms, src/pda, src/logistics)
- 已知技术债:test_e2e 超时;test_notification_router.py WebSocket mock 问题
- 涉及这些区域时先说明现状,再动手
- 数据库变更需写迁移,禁止直接改表结构

## 工具链使用

- **opencode**:默认模型 9B-Coder-MTP;`review` agent 做只读审查(9B-claude-4.8)
- **Claude Code**:模型 35B-A3B,Anthropic 端点走 LM Studio 1234 端口
- 切换模型:首次请求会自动触发 LM Studio 加载,需等待几秒~几十秒

## 当前开发任务(2026-08 核查后更新)

> 注:`newtodo.md` 中的 Phase 4-6 清单**已全部实现**,不要按那份文档开工。以下为核查后的真实待办。

### 已知技术债(改到相关区域先说明)
- 2026-08-13 修复(commit e7a849d):PG 迁移链 — alembic `26f0642a5601` 改用 SAVEPOINT 助手 `_best_effort()`,失败步骤不再中止整个事务;先建 `uq_role_permission`/`uq_user_role` 与 `eb47b7e1074b` 重复问题已在 PG 全量验证消除;`src/tms/models.py` CarrierConfig 增加唯一 PK `id`,`carrier_code` 改 unique 列(修复 `transport_orders.carrier_config_id` 在 PG 下无效的悬空 FK);CI(ci.yml/deploy.yml)新增 `alembic upgrade head` 对全新 PG 服务验证迁移;`tests/conftest.py` 恢复 SQLite-only 并注释说明原因(asyncpg 池无法跨 pytest-asyncio auto 模式事件循环)
- 2026-08-13 修复(commit 53e92bb/8e171c9):CI 首次跑绿 — `test_raises_on_empty_secret` 用 monkeypatch 清 SECRET_KEY(CI 注入 SECRET_KEY 时会误失败);`frontend/package-lock.json` 用 `npm@10` + 官方 registry 重新生成(旧 lockfile 由本机 npm11 生成且缺 `unplugin@3.3.0`,npm10 用 EUSAGE 拒绝;本机全局 registry 是 npmmirror,其 tgz 地址 GitHub Actions 拉不到);deploy.yml postgres health-cmd 加引号(`pg_isready -U postgres` 无引号导致 docker create exit 125)
- 2026-08-13 部署路径修复(commit 084b974/1b02392):Helm Chart.yaml 声明 bitnami postgresql/redis 依赖(缺声明则 subchart 不装);migration-job 从 secret 注入 DATABASE_URL(否则 hook 跑在默认 SQLite);secret 补 PG_USER/PG_DATABASE/PG_PASSWORD(backup-cronjob 曾引用未定义 key);新增 `deploy/.env.production.example` 生产密钥模板;compose 三服务补 Sentry/OTLP/Firebase/日志 env;dev/ 收纳根目录调试脚本 + ruff/pytest exclude
- 2026-08-13 验证:**GitHub Actions 全线绿**(CI run 16 + Build/Test/Deploy run 6:lint/test/frontend-build/build-and-push/deploy 全 success,GHCR 镜像已推送)
- 2026-08-13 核查:`ruff check src/ tests/` 现已 **All checks passed!**(此前"212 个错误无法自动修复"清单已全部清除),`test_notification_router.py`/`test_notification_ws.py`/`test_e2e` 42 passed(WebSocket mock 问题与 E2E 超时均已解决)
- 2026-08-13 mobile/ 补齐:client.js 的 localStorage → AsyncStorage(原生 RN 无 localStorage);`request()` 离线入队仅限 mutation 且排除 4xx 业务错误;修复 PackingRecord/StockCount 的 `??`+`||` 混用语法错误;补依赖 async-storage/expo-asset/font/constants/web 三件套;生成合法 icon;package-lock.json 用官方 registry 重新生成(0 npmmirror)。`expo export --platform android` 验证通过(Metro 打包成功)

### 已确认完成(勿重复实现)
- OrderPriority 枚举(URGENT)、warehouses.html、orders split/merge API、TMS ERP connector
- PurchaseOrder/Invoice/CreditMemo 模型+迁移+API、SKU weight_kg/volume_m3、AddressMaster+resolve_address
- deploy/ Helm chart + docker-compose.prod.yml、/health 健康检查(DB/Redis/readiness)
- 2026-08-02 修复:forecast.py 语法错误、RedisClient 真实客户端恢复(含 MemoryCache fallback)、offline SyncQueue 实现、outbox/tasks/notification WS 测试同步。全量测试 **1704 passed / 0 failed / 10 skipped**
- 2026-08-02 清理:`TestPDAOffline`(假想 SQLAlchemy API,能力由 src/pda 提供)、`src/ml/` 旧版 DemandForecaster + 其测试、`LocalStore`/`SyncQueue` 死代码 + `test_offline.py`/`test_e2e.py` 对应测试。全量测试 **1685 passed / 0 failed / 7 skipped**
- 2026-08-03 修复:`tests/test_e2e/test_full_system.py` 超时问题已解决 — 原因是 `/api/v1/warehouses` 与 `/warehouses/{id}/locations` 改为分页返回结构(`{"items":[...]}`),E2E 断言仍按裸 list 处理。已在测试中改用 `body["items"]`,并移除 pyproject.toml 的 `--ignore=tests/test_e2e`,E2E 已纳入主测试套件。全量测试 **1691 passed / 0 failed / 7 skipped**
- 2026-08-03 架构简化:完全移除 RabbitMQ 基础设施(App 从未使用 — Celery 以 Redis 为 broker,Outbox 走 HTTP 派发)。清理点:config.rabbitmq_url、core/outbox.py 中 rabbitmq 引用、docker-compose/prod-compose/Helm 的 rabbitmq 服务、RABBITMQ_URL 注入、.env/.env.example、build/deployall/dev-start .bat、文档
- 2026-08-03 Rate Limiter 配置化:阈值/窗口从 settings 读取(`rate_limit_requests`/`rate_limit_window`),修复 `get_rate_limit_headers` 硬编码 60 的 bug,`api_rate_limit` 改为跟随 settings 默认值
- 2026-08-03 文档:`docs/architecture.md` 创建(系统架构总览,路由/中间件/核心层/业务域/任务/部署/测试)
- 2026-08-04 Pydantic Response models 补齐(全量):给原本返回裸 dict/list 的端点加 `response_model` 类型安全约束。已完成 — OMS `GET /merge/{group_id}`→`MergeGroupResponse`;WMS `GET /shipments`→`list[ShipmentResponse]`、`GET /vendors`→`VendorListResponse`、`GET /vendors/{id}`→`VendorResponse`、`GET /purchase-orders`→`PurchaseOrderListResponse`、`GET /{wh_id}/locations`→`LocationListResponse`(新建 ShipmentResponse/VendorResponse/VendorListResponse/PurchaseOrderListResponse/LocationListResponse;补 PurchaseOrderResponse 的 expected_date/created_at、LocationResponse 的 status/position);TMS `GET /return-orders`→`list[ReturnOrderResponse]`(拆包原 `(items,total)` 元组)、`POST|GET|PATCH return-orders`→`ReturnOrderResponse`、`GET /exceptions`→`list[TransportExceptionResponse]`、exceptions 增改→`TransportExceptionResponse`(新建该类)、`GET /devices/{id}/sessions`→`list[SessionResponse]`(修正:剔除模型不存在的 user_agent,补 status)。full 全量 **1691 passed / 0 failed / 7 skipped**(顺带 dashboard `git status` 缺 MergeGroup 测试 stub 字段与 service 不一致已修)。
