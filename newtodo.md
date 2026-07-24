# TODO — OMS+WMS+TMS 系统改进清单

根据行业标杆（SAP S/4HANA, Oracle NetSuite, ShipHero, Alibaba）竞品分析，列出当前项目待改进事项。

---

## Phase 1 — P0 (紧急)

### [ ] OpenTelemetry + Sentry 接入日志追踪
- **现状**: X-Request-ID 唯一链路 ID，无分布式追踪；stdout → docker logs 原始输出
- **对标**: SAP (Cloud Foundry Logging Service) / ShipHero (OpenTelemetry Collector + Jaeger)
- **改动范围**: 
  - `src/core/middleware.py` — 增加 TraceContext
  - `main.py` — 接入 `opentelemetry-api` + `opentelemetry-sdk` + `opentelemetry-instrumentation-fastapi`
  - Sentry SDK (`sentry-sdk[fastapi]`) — 自动捕获未处理异常并告警

### [ ] Outbox Pattern — 跨服务数据一致性
- **现状**: OMS 创建订单后仅本地 DB commit，WMS/TMS 无感知
- **对标**: SAP S/4HANA Business Transaction Services / ShipHero Saga + Outbox
- **改动范围**:
  - `src/core/database.py` — 增加 `OutboxMessage` ORM Model (event_type, payload, status)
  - WMS Router — OrderCreated → 写本地 DB + Outbox Table
  - Celery Worker — Poll Outbox → Dispatch via RabbitMQ
  - TMS Router — 同样模式

### [ ] PDA 离线作业模式 (SQLite + SyncQueue)
- **现状**: API 依赖网络，无本地缓存；扫码仅上报不处理
- **对标**: SAP EWM MDM / ShipStation RFID PDA App
- **改动范围**:
  - `src/pda/` — 新建模块: SQLite 本地 DB + Sync Queue (outbox 模式)
  - `src/api/v1/mobile.py` — REST API 兼容层，支持离线端调用
  - `src/tasks/sync.py` — Celery Worker 自动推送缓存到主库

---

## Phase 2 — P1 (重要)

### [ ] Inventory FEFO/FIFO 批次管理
- **现状**: `Inventory.quantity = int`, 仅有 JSON `batch_no`, 无效期
- **对标**: SAP WM Batch/Expiry / NetSuite SuiteInventory FIFO + FEFO
- **改动范围**:
  - `src/wms/models.py` — `Inventory` 增加: `batch_no`, `expiry_date`, `batch_status`
  - WMS Service — 新增 `pick_fifo()` / `pick_fefo()` 方法 (拣货策略)
  - Celery Cron — `inventory_aging_report` (库存周转天数计算)

### [ ] ERP/EDI Connector (SAP PI/PO + Oracle EDI X12)
- **现状**: 纯 REST API，无 SAP / Oracle / Shopify / Amazon 对接
- **对标**: SAP IDoc / NetSuite SuiteTalk / Shopify WMS API
- **改动范围**:
  - `src/connectors/sap.py` — SAP PI/PO (SOAP + IDoc XML)
  - `src/connectors/oracle_edi.py` — EDI X12 / ASC 850 Order Message
  - `src/connectors/shopify_webhook.py` — Shopify Webhook → OMS
  - `src/connectors/amazon_mws.py` — Amazon MWS / SP-API

### [ ] 订单拆单/合并 (SplitOrder / MergeOrders)
- **现状**: 1:1 Order ↔ Shipment，无拆分或聚合
- **对标**: SAP SD Multi-Source Sourcing / Shopify Split Fulfillment
- **改动范围**:
  - `src/oms/models.py` — 增加 `MergeGroup`, `SplitChildOrders` (FK → parent)
  - WMS Service — 多订单合并为 Wave，生成 Shipment
  - TMS Service — 合并发货节省运费

---

## Phase 3 — P2 (锦上添花)

### [ ] Route Plan Redis Cache + Carrier Multi-Rate Shopping
- **现状**: Dijkstra 每次重新计算; 承运商仅静态 `carrier_routes`
- **对标**: SAP TM Carrier Selection / ShipHero Rate Comparison Engine
- **改动范围**:
  - `src/cache/redis_client.py` — 增加 `RoutePlanCache` (TTL=24h)
  - TMS Service — Route Plan → Redis Cache (`(origin_city, dest_city)` key)
  - Carrier Config — 实时 API 比价 + SLA 自动选择最优承运商

### [ ] ABC-XYZ 库存分析 Dashboard
- **现状**: Inventory 仅数量; 无周转天数 / 价值分层
- **对标**: SAP Analytics Cloud Inventory KPIs
- **改动范围**:
  - `src/wms/analysis.py` — ABC (RFM) + XYZ (需求波动系数 CV²)
  - Celery Cron — 每日计算 SKU 分类并刷新 Redis Dashboard Cache

---

## 建议开发顺序

```text
Phase 1 → Phase 2 → Phase 3
 |           |            |
 V           V            V
P0         P1          P2
 (4项)     (3项)       (2项)
```

- **Phase 1**: OpenTelemetry / Outbox / PDA Offline — 先补齐可观测性与核心能力
- **Phase 2**: Inventory FEFO/FIFO / ERP Connector / SplitMerge — 完善供应链业务闭环
- **Phase 3**: Route Plan Cache / ABC Dashboard — 性能优化与运营分析

---

> 📌 **总体评价**: 当前项目是一个优秀的学习/原型级 SCM 系统，代码质量高、模块职责清晰。但距离商业级产品在分布式事务一致性、离线移动端、库存精细化、可观测性四个维度还有较大差距。
>
> **建议 Phase 1-2 优先补齐核心供应链能力 (FEFO/FIFO + SplitOrder)，Phase 3 再扩展生态对接 (ERP/EDI)。**

---

## 补充说明：当前已完成的改进项

以下事项已在之前的对话中完成（可作为后续 TODO 的参考）：
- ✅ Excel 批量条码生成模块 (`src/barcode/excel_barcode.py`) — EAN-13 / QR Code / ZPL 输出
- ✅ 操作手册更新 (`MANUAL.md` — ~964 行)
- ✅ API 接口文档完善 (含详细 curl 示例)
