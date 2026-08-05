# TODO — OMS+WMS+TMS 系统改进清单

根据行业标杆（SAP S/4HANA, Oracle NetSuite, ShipHero, Alibaba）竞品分析，列出当前项目待改进事项。

---

## Phase 1 — P0 (紧急)

### [x] OpenTelemetry + Sentry 接入日志追踪
- **现状**: X-Request-ID 唯一链路 ID，无分布式追踪；stdout → docker logs 原始输出
- **对标**: SAP (Cloud Foundry Logging Service) / ShipHero (OpenTelemetry Collector + Jaeger)
- **改动范围**: 
  - `src/core/middleware.py` — 增加 TraceContext
  - `main.py` — 接入 `opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-instrumentation-fastapi`
  - Sentry SDK (`sentry-sdk[fastapi]`) — 自动捕获未处理异常并告警

### [x] Outbox Pattern — 跨服务数据一致性
- **现状**: OMS 创建订单后仅本地 DB commit，WMS/TMS 无感知
- **对标**: SAP S/4HANA Business Transaction Services / ShipHero Saga + Outbox
- **改动范围**:
  - `src/core/database.py` — 增加 `get_session` 上下文管理器
  - `src/core/outbox.py` — OutboxEvent 模型 + append/dispatch 函数
  - `src/tasks/outbox.py` — Celery 定时轮询任务
  - `src/oms/service.py` — `create_order` 调用 `append_event`

### [x] PDA 离线作业模式 (SQLite + SyncQueue)
- **现状**: API 依赖网络，无本地缓存；扫码仅上报不处理
- **对标**: SAP EWM MDM / ShipStation RFID PDA App
- **改动范围**:
  - `src/pda/` — 新建模块
  - `src/core/offline.py` — SyncQueueService 本地 SQLite 队列
  - `src/api/v1/mobile.py` — REST API 兼容层，支持离线端调用
  - `src/tasks/sync.py` — Celery Worker 自动推送缓存到主库

---

## Phase 2 — P1 (重要)

### [x] Inventory FEFO/FIFO 批次管理
- **现状**: `Inventory.quantity = int`, 仅有 JSON `batch_no`, 无效期
- **对标**: SAP WM Batch/Expiry / NetSuite SuiteInventory FIFO + FEFO
- **改动范围**:
  - `src/wms/models.py` — `Inventory` 增加: `expiry_date`, `manufacturing_date`, `received_at`
  - WMS Service — 新增 `_pick_batches()` 方法 (FEFO/FIFO 拣货策略)
  - Alembic 迁移 — 新增 3 列 + 索引

### [x] ERP/EDI Connector (SAP PI/PO + Oracle EDI X12)
- **现状**: 纯 REST API，无 SAP / Oracle / Shopify / Amazon 对接
- **对标**: SAP IDoc / NetSuite SuiteTalk / Shopify WMS API
- **改动范围**:
  - `src/connectors/` — 新建连接器包
  - `src/connectors/shopify_webhook.py` — Shopify Webhook → OMS
  - `src/connectors/amazon_mws.py` — Amazon SP-API 订单导入

### [x] 订单拆单/合并 (SplitOrder / MergeOrders)
- **现状**: 1:1 Order ↔ Shipment，无拆分或聚合
- **对标**: SAP SD Multi-Source Sourcing / Shopify Split Fulfillment
- **改动范围**:
  - `src/oms/models.py` — 增加 `MergeGroup`, `SplitChildOrders`
  - `src/oms/merge.py` — 拆分/合并 service 函数
  - `src/oms/router.py` — `POST /{id}/split`, `POST /merge`, `GET /merge/{id}`

---

## Phase 3 — P2 (锦上添花)

### [x] Route Plan Redis Cache + Carrier Multi-Rate Shopping
- **现状**: Dijkstra 每次重新计算; 承运商仅静态 `carrier_routes`
- **对标**: SAP TM Carrier Selection / ShipHero Rate Comparison Engine
- **改动范围**:
  - `src/tms/service.py` — `find_best_route_plan` 增加 Redis 缓存层
  - 缓存 key: `route:{origin_city}:{dest_city}:{weight_kg}`, TTL=24h

### [x] ABC-XYZ 库存分析 Dashboard
- **现状**: Inventory 仅数量; 无周转天数 / 价值分层
- **对标**: SAP Analytics Cloud Inventory KPIs
- **改动范围**:
  - `src/wms/analysis.py` — ABC (Pareto) + XYZ (CV 波动系数)
  - Celery Cron — 每日计算后写入 Redis 缓存

---

## Phase 4 — P3 (新增，根据代码审计实际发现的缺失项)

### [ ] Bug Fix: `OrderPriority.URGANIC` → `URGENT` (阻断所有订单创建)
- **文件**: `src/oms/service.py` line ~47
- **影响**: 所有创建订单的 API 调用直接崩溃
- **对标**: SAP SD Order Creation — 优先级枚举必须准确

### [ ] Admin UI: `warehouses.html` template (缺失页面)
- **现状**: `router.py` 已注册 `/admin/warehouses` 路由，但模板不存在
- **文件**: `src/admin/templates/admin/warehouses.html` (~30 行)
- **对标**: SAP EWM Warehouse Management Console

### [ ] Order Split/Merge — API Endpoints (仅 Service 逻辑未暴露)
- **现状**: `_pick_batches()` 拆分逻辑在 WMS，但无 `/api/v1/orders/split`, `/merge` REST endpoint
- **对标**: Shopify Split Fulfillment API / SAP Multi-Source Sourcing

### [ ] ERP Connectors — `src/tms/connectors/erp.py` (仅骨架)
- **现状**: 有文件但只有 stub，无 SAP PI/PO / Oracle EDI X12 实际对接
- **对标**: SAP IDoc, Oracle SOA Suite

### [ ] PurchaseOrder / Invoice Models
- **现状**: `src/models/` 中缺少采购单、发票实体
- **对标**: SAP MM (Material Management) — PO + Goods Receipt + Invoice Verification

### [ ] SKU Weight/Volume Fields
- **现状**: SKU 模型缺少 `weight_kg`, `volume_m3` 字段（影响运费计算）
- **对标**: SAP SD Shipping Units / ShipHero Dimensional Weight

### [ ] Address Master Entity (独立实体)
- **现状**: 地址嵌入在 Order/Shipment Model 中，无独立 Address master 表 + 去重归一化
- **对标**: SAP Business Partner Address / NetSuite Customer Address Book

---

## Phase 5 — P4 (高级功能，对标企业级系统)

### [ ] Purchase Orders (采购单) — OMS 扩展
- **现状**: 无采购单模型/接口
- **对标**: SAP ME (Manufacturing Execution), Oracle Procurement Cloud
- **改动范围**:
  - `src/oms/models.py` — `PurchaseOrder`, `POItem` models
  - `src/oms/service.py` — `create_purchase_order()`, `approve_po()`, `receive_goods()`
  - `src/oms/router.py` — `/api/v1/purchase-orders/*` CRUD endpoints

### [ ] Invoice (发票) + Credit Memo
- **现状**: 无开票逻辑，WMS TMS 不生成财务单据
- **对标**: SAP SD Billing, NetSuite Invoice Management
- **改动范围**:
  - `src/oms/models.py` — `Invoice`, `CreditMemo` models
  - `src/oms/service.py` — `generate_invoice()`, `post_credit_memo()`
  - `src/oms/router.py` — `/api/v1/invoices/*` endpoints

### [ ] SKU Master with Weight/Volume
- **现状**: `Inventory.sku_id` 引用的是字符串 ID（非规范化）；SKU Model 缺少重量体积
- **对标**: SAP Material Master Dimensions, ShipHero Dimensional Weight
- **改动范围**:
  - `src/wms/models.py` — `SKUMaster` model: `weight_kg`, `volume_m3`, `hs_code`, `unit_of_measure`
  - `src/oms/schemas.py` — Order Line Item 增加 weight/volume 字段
  - TMS freight calculation 使用 SKU dimensions

### [ ] Address Master + Deduplication
- **现状**: Address info stored as JSON in Order/Shipment; no master table
- **对标**: SAP Business Partner Address, NetSuite Customer Address Book
- **改动范围**:
  - `src/core/models.py` — `AddressMaster` model with address normalization (geocoding, dedup)
  - `src/oms/service.py` — `resolve_address()` reuse customer addresses
  - `src/wms/models.py` — Shipment → reference Address ID instead of embedded JSON

---

## Phase 6 — P5 (DevOps / Production Hardening)

### [ ] CI/CD Pipeline + Automated E2E Tests
- **现状**: 无 GitHub Actions; 测试手动运行
- **对标**: ShipHero CI (CircleCI → AWS ECS), SAP DevOps Pipeline
- **改动范围**:
  - `.github/workflows/ci.yml` — pytest, ruff, mypy
  - E2E: Playwright tests against local Docker compose stack
  - Coverage gate: `pytest-cov --fail-under=70`

### [ ] Deployment Scripts (docker-compose + systemd / K8s Helm)
- **现状**: docker-compose.yml 存在但只有 DB + Redis; no admin worker / celery beat
- **对标**: SAP Cloud Foundry, ShipHero ECS deployment scripts
- **改动范围**:
  - `deploy/` — Dockerfile for each service, docker-compose.prod.yml
  - Helm chart or K8s manifests

### [ ] Health Check Endpoints + Readiness Probe
- **现状**: `/health` only returns static JSON
- **对标**: Kubernetes LivenessProbe + Redis DB size check
- **改动范围**:
  - `src/api/v1/health.py` — add DB connectivity test, Redis ping, disk usage

---

## 建议开发顺序

```text
Phase 4 (Bug Fixes) → Phase 5 (Core Business Gaps) → Phase 6 (Advanced) → Phase 7 (DevOps)
   |                        |                              |               |
   V                        V                              V               V
 P3                    P2                             P1              P0
 (7项)                (4项)                          (2项)           (3项)
```

---

## 补充说明：当前已完成的改进项

以下事项已在之前的对话中完成（可作为后续 TODO 的参考）：
- ✅ Excel 批量条码生成模块 (`src/barcode/excel_barcode.py`) — EAN-13 / QR Code / ZPL 输出
- ✅ 操作手册更新 (`MANUAL.md` — ~964 行)
- ✅ API 接口文档完善 (含详细 curl 示例)
- ✅ Middleware 修复 (TraceContext/RequestID/RequestLogging/AuditLog — 4 个 Bug)
- ✅ 数据库连接测试通过 (356/356, 6 skipped)
