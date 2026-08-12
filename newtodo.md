# TODO — OMS+WMS+TMS 系统改进清单

基于 2026-08-12 核查后的状态编写（对比 SAP S/4HANA / NetSuite / ShipHero；SAP 接口暂不开发）。

---

## ✅ 已完成（可作为参考，勿重复实现）

### Phase A — 已完成的架构与质量改进
- **OpenTelemetry + Sentry**：已在 `src/core/middleware.py` TraceContext + uvicorn instrumentation；Sentry SDK (`sentry-sdk[fastapi]`) 自动捕获未处理异常
- **Outbox Pattern**：`src/core/outbox.py` OutboxEvent + append/dispatch；Celery 定时轮询；oms service `create_order` 已调用
- **PDA 离线作业**：SQLite SyncQueue + WebSocket 实时广播，API 兼容层
- **测试/质量**：pytest (~1720 用例全通过) / ruff lint clean / mypy type-check
- **文档**: docs/architecture.md（系统架构总览）、OPERATIONS.md（操作手册 v1.0）

### Phase B — 已完成的 API 端点与页面
- OMS: orders CRUD + split/merge (`GET /merge/{group_id}` → `{"items":[...]}`, MergeGroupResponse)
- WMS: vendors, shipments, purchase-orders, `/warehouses/{id}/locations` (LocationListResponse, status/position)
- TMS: transport-orders, waybills, return-orders, exceptions (TransportExceptionResponse), sessions (`GET /{device_id}/sessions`)
- 条码：EAN-13/QR/ZPL + Excel 导入导出

---

## 🔧 Phase C — Bug Fixes（优先，低挂起成本）

### [ ] Order Split/Merge REST endpoints
- **现状**: split/merge service 逻辑存在但无公开 endpoint
- **改动范围**:
  - `src/oms/router.py` — `POST /api/v1/orders/{id}/split`, `POST /api/v1/orders/merge`, `GET /api/v1/merge/{group_id}`

### [ ] Admin UI templates
- **现状**: `warehouses.html` 模板已记录为缺失
- **改动范围**: 生成 `src/admin/templates/admin/warehouses.html` (~30 行)

---

## 🎯 Phase D — Core Business Gaps（重要）

### [ ] Inventory FEFO/FIFO batch management
- **现状**: `Inventory.quantity = int`, 仅有 JSON `batch_no`；无效期字段缺失
- **对标**: SAP WM Batch/Expiry / NetSuite SuiteInventory FIFO+FEFO
- **改动范围**:
  - `src/wms/models.py` — Inventory: +`expiry_date`,`manufacturing_date`,`received_at`
  - WMS Service `_pick_batches()`: FEFO/FIFO 拣货策略实现
  - Alembic migration: +3 列 + 索引

### [ ] Route Plan Redis cache + carrier multi-rate shopping (Phase 3)
- **现状**: Dijkstra 每次重算；承运商静态配置
- **改动范围**:
  - `src/tms/service.py` — find_best_route_plan 增加 Redis 缓存层，key=`route:{origin_city}:{dest_city}:{weight_kg}`, TTL=24h

### [ ] ABC-XYZ inventory analysis Dashboard (Phase 3)
- **对标**: SAP Analytics Cloud Inventory KPIs / ShipHero Rate Comparison Engine
- **改动范围**:
  - `src/wms/analysis.py` — ABC(Pareto) + XYZ(CV 波动系数)
  - Celery Cron — 每日计算后写入 Redis 缓存

### [ ] SKU Master with Weight/Volume (Phase D / Phase 5 第 3)
- **现状**: SKU Model 缺少 `weight_kg`, `volume_m3`（影响运费计算）；Inventory 引用字符串 ID（非规范化）
- **对标**: SAP Material Master Dimensions, ShipHero Dimensional Weight
- **改动范围**:
  - `src/wms/models.py` — SKUMaster model: `weight_kg`, `volume_m3`, `hs_code`, `unit_of_measure` + Alembic
  - `src/oms/schemas.py` — Order LineItem pydantic model 增加 weight/volume

### [ ] Address Master Entity with Deduplication (Phase D / Phase 5 第 4)
- **现状**: 地址嵌入在 Order/Shipment JSON，无独立 master 表 + 去重归一化；对标 SAP BP Address / NetSuite Address Book
- **改动范围**:
  - `src/core/models.py` — `AddressMaster` model with address normalization (geocoding, dedup)
  - `src/oms/service.py` — `resolve_address()`, reuse customer addresses
  - Shipment: reference Address ID instead of embedded JSON

---

## 🚀 Phase E — Advanced Features

### [ ] Purchase Orders (采购单) — OMS 扩展
- **现状**: 无采购单模型/接口；对标 SAP ME (Manufacturing Execution), Oracle Procurement Cloud
- **改动范围**:
  - `src/oms/models.py` — `PurchaseOrder`, `POItem` models + Alembic
  - `src/oms/service.py` — `create_purchase_order()`, `approve_po()`, `receive_goods()`
  - `src/oms/router.py` — `/api/v1/purchase-orders/*` CRUD endpoints

### [ ] Invoice (发票) + Credit Memo
- **现状**: 无开票逻辑，WMS TMS 不生成财务单据；对标 SAP SD Billing, NetSuite Invoice Management
- **改动范围**:
  - `src/oms/models.py` — `Invoice`, `CreditMemo` models + Alembic
  - `src/oms/service.py` — `generate_invoice()`, `post_credit_memo()`
  - `src/oms/router.py` — `/api/v1/invoices/*` endpoints

### [ ] SKU Weight/Volume Fields for Freight Calculation (Phase D / Phase E)
- **现状**: SKU Model 缺少重量体积，影响 TMS 运费计算；Inventory 引用字符串 ID（非规范化）；对标 SAP Material Master Dimensions, ShipHero Dimensional Weight
- **改动范围**：与 D#3 SKUMaster + LineItem pydantic 合并实现

### [ ] Address Master Entity (Phase D / Phase E)
- **现状**: 地址嵌入 Order/Shipment JSON，无独立 master；对标 SAP Business Partner Address, NetSuite Customer Address Book
- **改动范围**：与 D#4 AddressMaster 合并实现

---

## 🛠️ Phase F — DevOps / Production Hardening

### [ ] CI/CD Pipeline + Automated E2E Tests
- **现状**: 无 GitHub Actions；测试手动运行
- **改动范围**:
  - `.github/workflows/ci.yml` — pytest, ruff, mypy（已存在 ci.yml，更新）
  - E2E: Playwright tests against local Docker compose stack
  - Coverage gate: `pytest-cov --fail-under=70`

### [ ] Deployment Scripts (docker-compose + systemd / K8s Helm)
- **现状**: docker-compose.yml 只有 DB+Redis，无 admin worker/celery beat；对标 SAP Cloud Foundry, ShipHero ECS deployment scripts
- **改动范围**: deploy/ Dockerfile per service, `docker-compose.prod.yml`, Helm chart

### [ ] Health Check Endpoints + Readiness Probe
- **现状**: `/health` only returns static JSON
- **改动范围**: `src/api/v1/health.py` — DB connectivity test, Redis ping, disk usage（供 K8s LivenessProbe/readiness）

---

## 📋 待办统计（剔除 SAP connectors 后）

| Phase | 任务数 | 说明 |
|-------|--------|------|
| C Bug Fixes | 2 | split/merge endpoint、admin template |
| D Core Gaps | 5 | FEFO batch、route cache、ABC-XYZ、SKU dims、address master |
| E Advanced | 3 | POs、Invoice+CM、freight calc(与 SKU dims 合并) |
| F DevOps | 3 | CI/CD、deploy scripts、/health probe |
| **总计** | **13** | 原 14 - 1 connectors = 13 |

---

## 📊 建议开发顺序

```
Phase C (Bug Fixes, low hanging cost) → Phase D (Core Gaps) → Phase E (Advanced) → Phase F (DevOps)
    |                                      |               |              |
    V                                      V               V              V
   P0                         P1 / P2           P3             P5
   (2项)                      (5项)             (3项)            (3项)
```

---

## 📝 补充：当前已完成的改进项（勿重复实现）

- ✅ Excel 批量条码生成模块 (`src/barcode/excel_barcode.py`) — EAN-13 / QR Code / ZPL 输出
- ✅ 操作手册更新 (`OPERATIONS.md` — ~153 行) + docs/architecture.md
- ✅ API 接口文档完善 (含 curl 示例)、response_model：MergeGroupResponse、LocationListResponse、PurchaseOrderListResponse、VendorListResponse、ReturnOrderResponse、TransportExceptionResponse、SessionResponse

---

## 📖 备注：已移除的 SAP 相关任务

以下事项**因与 SAP 接口相关，暂不开发**（已从清单中剔除）：
- ~~Phase D#4 ERP/EDI Connectors (SAP PI/PO + Oracle X12)~~ — SAP IDoc / Oracle EDI X12 对接已移除
- ~~Phase E Purchase Orders 对标 SAP ME、Invoice 对标 SAP SD Billing —— 保留但仅实现基础 CRUD，不绑定 SAP 协议~~

(End of file)
