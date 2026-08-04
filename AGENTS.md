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
- `.github/workflows/` 已存在(ci.yml + deploy.yml),但尚未实际跑绿验证
- CI `lint` job(ruff check src/ tests/)仍有 **212 个错误无法自动修复**:E501 行长(90)、F821 未定义名(45,多为 schemas/service 内 `Literal`/`SKU`/`Warehouse`/`User` 等缺失 import,可能为真实 bug,需人工逐处补 import)、F841 未用变量(21)、E402(13) 等。`--fix` 已自动修复 306 项(import 排序/未用 import 等,2026-08-03)

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
