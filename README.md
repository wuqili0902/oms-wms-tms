# OMS/WMS/TMS 操作手册 v1.0

## 项目概述

Oms-Wms-Tms 是一套完整的仓储物流管理系统，集成订单管理（OMS）、仓库作业（WMS）和运输配送（TMS）。系统采用微服务架构，支持 SAP PI/PO + Oracle EDI 对接、FEFO/FIFO 批次库存管理、PDA 离线作业模式等高级功能。

## 模块索引

| # | 模块 | 路径 |
|---|------|------|
| P0 | OpenTelemetry 分布式追踪 + Sentry 错误上报 | `src/telemetry.py` |
| P0 | Outbox Pattern 跨服务数据一致性 | `src/models/outbox.py` |
| P0 | PDA 离线作业模式 (SQLite + SyncQueue) | `src/pda/offline_mode.py` |
| P1 | Inventory FEFO/FIFO 批次管理 | `src/models/inventory.py` |
| P1 | ERP/EDI Connector (SAP PI/PO + Oracle EDI) | `src/models/erp_connector.py` |
| P2 | Route Plan Redis Cache + Carrier Multi-Rate Shopping | `src/models/route_plan.py` |
| P3 | ABC-XYZ 库存分析 Dashboard | `src/models/analytics.py` |

## 详细模块说明

### Phase 1 — P0 (核心基础设施)

#### 1. OpenTelemetry + Sentry (`src/telemetry.py`)
实现分布式追踪和错误上报，支持跨服务链路追踪。

**关键配置:**
```python
OTEL_EXPORTER_OTLP_ENDPOINT = "http://otel-collector:4317"
SENTRY_DSN = os.getenv("SENTRY_DSN")
```

#### 2. Outbox Pattern (`src/models/outbox.py`)
通过事务型消息表实现跨服务数据一致性。

**使用方式:**
```python
with Session() as session:
    order = Order(...)
    session.add(order)
    
    # 同时写入 outbox，而非直接发 MQ
    outbox_msg = OutboxMessage(
        aggregate_id=order.id,
        topic="orders",
        event_type="ORDER_CREATED"
    )
    session.add(outbox_msg)

# Consumer: poll outbox → dispatch (e.g. HTTP POST) → mark dispatched
```

#### 3. PDA 离线作业模式 (`src/pda/offline_mode.py`)
仓库作业员使用 PDA 设备在无网络环境下进行拣货、盘点、收货等操作，待网络恢复后自动同步。

**核心组件:**
- `SQLiteDB`: 本地缓存数据库 (WAL mode)
- `SyncQueue`: FIFO 队列，管理离线操作
- `PdaSession`: 管理用户会话和凭证

### Phase 2 — P1 (业务核心)

#### 4. Inventory FEFO/FIFO 批次管理 (`src/models/inventory.py`)
实现基于批次级的库存追踪，支持 FIFO（先进先出）和 FEFO（先到期先出）策略。

**关键模型:**
- `InventoryBatch`: 物理批次记录 (lot/batch)
- `InventoryReservation`: 订单预留库存
- `AllocationService`: 分配服务，支持 FIFO/FEFO/LIFO 策略

**业务规则:**
```python
# FIFO: 按 received_at 排序取货
query.order_by(InventoryBatch.received_at)

# FEFO: 按 expiry_date 排序，NULL 值排最后
query.order_by(InventoryBatch.expiry_date.nulls_last())
```

#### 5. ERP/EDI Connector (`src/models/erp_connector.py`)
实现与 SAP PI/PO + Oracle EDI 的对接，支持双向订单同步。

**支持的消息格式:**
- SAP IDOC (ORDERS, DELJRN, DESADV, INVOIC)
- EDIFACT / ANSI X12 (850, 855, 856, 810)

#### 6. Route Plan + Rate Shopping (`src/models/route_plan.py`)
智能配送路由和承运商比价系统。

**核心逻辑:**
```python
# Stage 1: 根据目的地筛选 eligible carriers
route = await route_cache.get_or_compute_route_plan("10001")

# Stage 2: 只对 carrier API 请求 eligible ones (减少 ~60% API 调用)
rates = [get_rate(c, order_id=order.id) for c in route.eligible_carriers]
```

### Phase 3 — P2 (高级分析)

#### 7. ABC-XYZ Inventory Analysis (`src/models/analytics.py`)
库存分类与补货建议。

**分类规则:**
| Category | Revenue Share | Formula |
|----------|---------------|---------|
| A        | >70%          | Pareto principle |
| B        | 20%-70%       | Mid-range |
| C        | <20%          | Low-value |

**Safety Stock Formulas:**
- AX (stable, high value): `Zα × σ_d × √LT` → 最小安全库存
- AZ (erratic, low value): `Zα × σ_d × √(LT + 3*LT_lead)` → 最大安全库存

## 配置指南

### 环境变量 (.env)
```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost/wms
SQLITE_LOCAL_PATH=/tmp/pda_cache.db

# ERP Integration
SAP_PI_HOST=https://sap-pi.example.com/pi-api
SAP_PI_USER=wms_service_account
SAP_PI_TOKEN=<token>
EDI_TRADING_PARTNER_ID=TP001

# Telemetry
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
SENTRY_DSN=https://<dsn>@sentry.io/<project-id>

# Redis (Route Cache)
REDIS_URL=redis://localhost:6379/0
```

## 数据流图

```
┌──────────┐    ┌──────────┐     ┌──────────┐     ┌──────────┐
│ Customer │ →→ │   WMS    │ →→  │ ERP/SAP  │ →→  │ Carrier  │
└────┬─────┘    └────┬─────┘     └────┬─────┘     └────┬─────┘
      ↑               ↓                ↓                 ↓
┌─────┴─────┐   ┌───┴────────┐  ┌───┴──────────┐  ┌───┴────────┐
│ PDA/APP  │   │ Outbox     │  │ EDI/IDOC     │  │ Route Cache│
└───────────┘   └────────────┘  └──────────────┘  └────────────┘
```

## API 参考

### Inventory APIs (`src/models/inventory.py`)
| Method | Path                           | Description          |
|--------|--------------------------------|----------------------|
| GET    | /api/v1/inventory/batches      | List batches         |
| POST   | /api/v1/inventory/allocate     | Allocate stock       |
| POST   | /api/v1/inventory/consume      | Consume reservation  |
| GET    | /api/v1/inventory/expiry-check | FEFO compliance      |

### ERP Connector APIs (`src/models/erp_connector.py`)
| Method | Path                           | Description          |
|--------|--------------------------------|----------------------|
| POST   | /api/v1/erp/sync-order         | Sync order to ERP    |
| GET    | /api/v1/erp/inbound/{msg_id}   | Poll inbound message |
| DELETE | /api/v1/edi/dlq/{dlq_id}       | Retry DLQ entry      |

### Analytics APIs (`src/models/analytics.py`)
| Method | Path                             | Description          |
|--------|----------------------------------|----------------------|
| GET    | /api/v1/analytics/abc-xyz        | Get segmentation     |
| POST   | /api/v1/analytics/regenerate     | Re-compute analysis  |

## 部署说明

### Docker Compose
```yaml
version: '3.8'
services:
  postgres:
    image: postgres:15
    volumes:
      - pg_data:/var/lib/postgresql/data
  
  redis:
    image: redis:7-alpine
    
  otel-collector:
    image: otel/opentelemetry-collector-contrib
    ports: ["4317:4317"]

  app:
    build: .
    depends_on: [postgres, redis]
```

### Database Migration
```bash
# Run migrations
alembic upgrade head

# Create new migration
alembic revision -m "add_inventory_batches_table"
```

## 常见问题 (FAQ)

**Q: FEFO/FIFO 分配失败怎么办？**
A: 检查 `InsufficientStockError` — 可能是批次过期或未入库。调用 `/api/v1/inventory/expiry-check` 查看预警批次。

**Q: Outbox 消息未消费？**
A: 检查 Celery worker (`dispatch_outbox_events`) 是否运行，以及 `OUTBOX_DISPATCH_URL` 端点是否可达。

**PDA 离线模式下数据如何同步？**
A: SyncQueue 会在网络恢复时自动将 SQLite 缓存推送到主数据库。可通过 `SyncStatus` API 查看同步进度。

## 扩展阅读

- [SAP PI/PO IDOC Integration Guide](https://help.sap.com/viewer/p/SAP_PI_PO)
- [EDIFACT Standard (UN/CEFACT)](https://www.unece.org/trade/documents/edifact)
- [OpenTelemetry Specification](https://opentelemetry.io/docs/)
