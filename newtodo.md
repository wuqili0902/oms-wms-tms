# TODO — OMS+WMS+TMS 系统改进清单

基于 2026-08-12 核查后的状态编写（对比 SAP S/4HANA / NetSuite / ShipHero）。

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
- **改动范围**: 生成 `src/admin/templates/admin/warehouses.html`

### [ ] PurchaseOrder / Invoice / CreditMemo models + endpoints (Phase 5)
- 见 Phase D 第 1-3 项，补充对应的 router CRUD。

---

## 🎯 Phase D — Core Business Gaps（重要）

### [ ] Inventory FEFO/FIFO batch management
- **现状**: `Inventory.quantity = int`, 仅有 JSON `batch_no`；无效期字段缺失
- **对标**: SAP WM Batch/Expiry / NetSuite SuiteInventory FIFO+FEFO
- **改动范围**:
  - `src/wms/models.py` — Inventory: +`expiry_date`,`manufacturing_date`,`received_at`
  - WMS Service `_pick_batches()`: FEFO/FIFO 拣货策略实现
  - Alembic migration: +3 列 + 索引

### [ ] ERP/EDI Connectors (Phase B, Phase 2) — SAP PI/PO + Oracle EDI X12
- **现状**: `src/tms/connectors/erp.py` 仅有骨架 stub，无真实对接
- **对标**: SAP IDoc / NetSuite SuiteTalk / Shopify WMS API / Amazon SP-API
- **改动范围**:
  - `src/connectors/shopify_webhook.py` — Shopify Webhook → OMS（已有）
  - `src/connectors/amazon_mws.py` — Amazon SP-API 订单导入/Tracking（已有）
  - `src/connectors/sap_idoc.py` + `oracle_edi_x12.py`

### [ ] Route Plan Redis cache + carrier multi-rate shopping (Phase 3)
- **现状**: Dijkstra 每次重算；承运商静态配置
- **改动范围**:
  - `src/tms/service.py` — find_best_route_plan: key=`route:{origin}:{dest}:{weight_kg}`, TTL=24h

### [ ] ABC-XYZ inventory analysis Dashboard (Phase 3)
- **对标**: SAP Analytics Cloud Inventory KPIs / ShipHero Rate Comparison
- **改动范围**:
  - `src/wms/analysis.py` — ABC(Pareto) + XYZ(CV 波动系数)
  - Celery Cron: 每日计算后写入 Redis

### [ ] SKU weight/volume fields for freight (Phase D / Phase 5 第 3)
- **现状**: SKU 模型缺少 `weight_kg`,`volume_m3`，影响 TMS 运费计算；Inventory 引用字符串 ID（非规范化）
- **改动范围**:
  - `src/wms/models.py` — SKUMaster: `weight_kg`, `volume_m3`, `hs_code`, `unit_of_measure` + Alembic
  - `src/oms/schemas.py` — Order LineItem pydantic model 增加 weight/volume

### [ ] Address Master entity with dedup (Phase D / Phase 5 第 4)
- **现状**: 地址嵌入在 Order/Shipment JSON，无独立 master 表 + 归一化去重
- **对标**: SAP Business Partner Address / NetSuite Customer Address Book
- **改动范围**:
  - `src/core/models.py` — `AddressMaster`: address normalization (geocoding, dedup)
  - `src/oms/service.py` — `resolve_address()`, reuse customer addresses
  - Shipment: 引用 Address ID 而非嵌入 JSON

---

## 🚀 Phase E — Advanced Features

### [ ] Purchase Orders (Procurement) — OMS 扩展 (Phase 5, Phase D 第 1)
- **对标**: SAP ME / Oracle Procurement Cloud
- **改动范围**:
  - `src/oms/models.py` — `PurchaseOrder`, `POItem` models + Alembic
  - `src/oms/service.py` — create_po/approve/receive_goods

### [ ] Invoice + CreditMemo (Phase D 第 3)
- **对标**: SAP SD Billing / NetSuite Invoice Management
- **改动范围**: `src/oms/models.py` — `Invoice`,`CreditMemo`; service generate_invoice/post_credit_memo; router `/api/v1/invoices/*`

### [ ] SKU Master weight/volume + TMS freight calc (Phase D 第 3)

---

## 🛠️ Phase F — DevOps / Production Hardening

### [ ] CI/CD Pipeline
- **改动范围**: `.github/workflows/ci.yml` — pytest, ruff, mypy；E2E: Playwright + docker-compose stack；coverage gate `--fail-under=70`

### [ ] Deployment scripts (Phase 6)
- **改动范围**: deploy/ Dockerfiles per service, `docker-compose.prod.yml`, Helm chart / K8s manifests

### [ ] Health check endpoints + readiness probe (Phase F)
- **现状**: `/health` 仅返回静态 JSON
- **改动范围**: `src/api/v1/health.py` — DB connectivity test, Redis ping, disk usage

---

## 📋 建议开发顺序

```
Phase C (Bug Fixes, low hanging cost) → Phase D (Core Gaps) → Phase E (Advanced) → Phase F (DevOps)
    |                                      |               |              |
    V                                      V               V              V
  P0                         P1 / P2           P3             P5
```

---

## 📊 待办统计

| Phase | 任务数 | 说明 |
|-------|--------|------|
| C Bug Fixes | 2 | split/merge endpoint, admin template |
| D Core Gaps | 6 | batch, connectors, route cache, ABC-XYZ, SKU dims, address master |
| E Advanced | 3 | POs, Invoice+CM, freight calc(与 D 第 3 合并) |
| F DevOps | 3 | CI/CD, deploy scripts, /health probe |
| **总计** | **14** | — |

---

## 📝 补充：当前已完成的改进项（勿重复实现）

- ✅ Excel 批量条码生成 (`src/barcode/excel_barcode.py`) — EAN-13 / QR Code / ZPL
- ✅ OPERATIONS.md 操作手册 v1.0
- ✅ docs/architecture.md 系统架构总览
- ✅ API 端点 + response_model: MergeGroupResponse, LocationListResponse, PurchaseOrderListResponse, VendorListResponse, ReturnOrderResponse, TransportExceptionResponse, SessionResponse
- ✅ Middleware: TraceContext/RequestID/RequestLogging/AuditLog（4 个 bug）修复

(End of file)
