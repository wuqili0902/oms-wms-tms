# OMS-WMS-TMS 操作手册

## 一、项目概述

本项目是一套面向电商物流场景的 **订单 — 仓储 — 运输**（OMS → WMS → TMS）一体化管理系统，由三个子系统组成：

| 模块 | 全称 | 职责 |
|------|------|------|
| OMS | Order Management System | 接收外部电商平台订单，进行订单拆单、合并、履约路由 |
| WMS | Warehouse Management System | 管理仓库入库、拣货、出库、盘点等仓储作业 |
| TMS | Transport Management System | 管理承运商调度、路线规划（Hub-and-Spoke）、包裹追踪、POD 签收和逆向物流 |

> **注意**：TMS 前身是 Terminal Management System（终端设备管理），现已升级为完整的运输管理系统。旧的终端设备模型保留向后兼容。

## 二、技术栈

| 层级 | 技术选型 |
|------|----------|
| Web 框架 | FastAPI (ASGI) + Uvicorn |
| Python | 3.12+ |
| ORM | SQLAlchemy 2.x (AsyncSession, DeclarativeBase) |
| 数据库 | PostgreSQL (UUID 主键、JSONB、PostGIS 扩展可选) |
| 缓存 / 消息队列 | Redis + Celery |
| API Schema | Pydantic v2 |
| 认证授权 | JWT Bearer + `src/auth` 模块 |
| 代码质量 | Ruff (lint/format), mypy, pytest, coverage |

## 三、目录结构

```
oms-wms-tms/
├── src/                        # 源码根目录
│   ├── __init__.py             # 命名空间包
│   └── models/                 # 共享 Base + Mixin (SoftDeleteMixin, TimestampMixin, UUIDMixin)
│       ├── base.py             # DeclarativeBase、BaseModel 等
│       └── mixins.py           # 软删除 / 时间戳 / UUID mixin
│   ├── api/v1/                 # API Router
│   │   ├── __init__.py         # include_router 组装 v1 router
│   │   └── health.py           # /api/v1/health → {"status": "ok"}
│   ├── auth/                   # JWT token 签发 & 验证
│   ├── wms/                    # WMS: 仓库、货位、入库单、出库单、拣货单等
│   │   └── models.py           # Warehouse, Location, InboundOrder, OutboundOrder, PickList, ...
│   ├── oms/                    # OMS: 外部订单 & 内部履约单
│   │   ├── models.py           # ExternalOrder, FulfillmentOrder
│   │   └── service.py          # 拆单 / 合并 / 路由逻辑
│   ├── tms/                    # TMS: 运输管理 (原 Terminal Management System)
│   │   ├── __init__.py         # exports CarrierCode, TransportStatus, ...
│   │   ├── models.py           # TransportOrder, TrackingEvent, POD, Hub, RoutePlan, ReturnOrder, ...
│   │   └── schemas.py          # Pydantic schema (TransportOrderCreate/Update/ListResponse)
│   ├── logistics/              # 承运商集成 & 追踪
│   │   ├── carriers.py         # CarrierCode, query_tracking(), estimate_shipping()
│   │   └── waybills.py         # 电子面单管理
│   ├── barcode/                # 条码工具 (Zint CLI wrapper)
│   ├── ml/                     # ML: 智能推荐 / 异常检测
│   ├── admin/                  # 后台管理 & 审计日志
│   ├── core/                   # 共享配置 & 常量
│   └── tasks/                  # Celery Task 定义 (wms/tms/ml task)
├── alembic/                    # Alembic DB migration
├── tests/                      # pytest + coverage
├── Dockerfile
├── docker-compose.yml          # dev/prod profile
└── pyproject.toml              # 依赖 & uv 配置
```

## 四、核心数据模型速览

### WMS — Warehouse Management System

**仓库与货位**
- `Warehouse` — 仓库主数据 (id, code, name, address, contact_*, settings)
- `Location` — 库位 (warehouse_id, zone, aisle, row, level, capacity_weight/volume)

**入库管理 (Inbound)**
- `InboundOrder` — 采购/调拨入库单 (order_no, supplier_id, warehouse_id, status, items[])
- `InboundItem` — 入库明细 (sku_code, qty, batch_no)

**出库管理 (Outbound)**
- `OutboundOrder` — 销售出库 / 调拨出库 (order_no, source_warehouse_id, dest_*, status, items[])
- `PickList` — 拣货单 (outbound_order_id, wave_id, assigned_to, status)

**库存管理**
- `InventoryTransaction` — 库存流水记录
- `StockAdjustment` — 盘点调整单 (adjust_type: INCREASE / DECREASE)

### OMS — Order Management System

**订单模型**
- `ExternalOrder` — 外部电商订单 (platform_id, platform_order_no, status, items[])
- `FulfillmentOrder` — 履约订单，由拆单服务生成并关联 WMS OutboundOrder

### TMS — Transport Management System

> **TMS 前身是 Terminal Management System（终端设备管理系统），现已扩展为完整的运输管理系统。**

**运输主单**
- `TransportOrder` — 承运商运输合同 (transport_no, status, carrier_code, shipment_id)
- `TrackingEvent` — 物流追踪事件 (event_type: CREATED → PICKUP_COMPLETED → IN_TRANSIT → DELIVERED)

**POD（电子签收）**
- `ProofOfDelivery` — ePOD (signed_by, signature_type: PHYSICAL / DIGITAL, delivery_photo_urls[])

**Hub-and-Spoke 路由**
- `TransferHub` — 转运枢纽 (primary/secondary/cargo_station)
- `CarrierRoute` — 承运商路线定价 (origin_city → dest_city)
- `TransportSegment` — 运输段 (segment_no: 0-based position in plan)
- `HubConnection` — 图边 (from_hub_code → to_hub_code, Dijkstra 路径规划)
- `RoutePlan` — 路由计划 (type: AUTO_GEN / MANUAL)

**逆向物流 & 异常**
- `ReturnOrder` — 退货单 (return_no, reason, transport_order_id)
- `TransportException` — 运输异常事件 (DELAYED / DAMAGED_IN_TRANSIT / LOST)

**运费结算**
- `FreightRule` + `FreightTier` — 阶梯计费规则 (weight/distance/volume based)

**遗留模型（向后兼容）**
- `TerminalDevice`, `DeviceSession`, `SyncLog` — PDA/手机设备会话管理

## 五、API 端点

所有 API 挂载在 `/api/v1` 下，通过 JWT Bearer Token 鉴权。

| Method | Path | Description |
|--------|------|-------------|
| GET    | /health          | 健康检查，返回 `{"status": "ok"}` |
| POST   | /auth/login      | JWT token 签发 |
| POST   | /wms/inbounds    | 创建入库单 |
| PUT    | /wms/inbounds/{id}/confirm | 确认收货 |
| GET    | /wms/outbounds?status=... | 查询出库单 |
| POST   | /wms/stock-adjustment | 盘点调整 |
| GET    | /oms/orders      | 外部订单列表 |
| POST   | /tms/transports  | 创建运输单 |
| PUT    | /tms/transports/{id}/track | 更新追踪信息 |
| GET    | /tms/routes?origin=&destination= | 路线规划 (Dijkstra) |

> **详细端点定义**：各模块的 `service.py` 和 API router 文件中注释了每个端点的请求/响应格式。

## 六、构建与运行

### 环境要求
- Python ≥ 3.12（项目使用 `uv` 管理依赖）
- PostgreSQL ≥ 14
- Redis ≥ 7.0 (可选，用于 Celery broker)

### 本地开发启动

```bash
# 安装依赖
uv sync

# 配置环境变量 (.env 或 .env.development)
cp env.example .env

# 迁移数据库
alembic upgrade head

# 启动 API 服务
uv run uvicorn src.api:v1.app --reload
```

### Docker Compose（开发环境）

```bash
docker compose up -d   # 自动拉起 postgres + redis + app
```

## 七、测试

```bash
pytest tests/ -v
pytest tests/ --cov=src --cov-report=term-missing
```

- `tests/wms/test_models.py` — WMS 数据模型单元测试
- `tests/tms/test_models.py` — TMS 路由规划 / POD 模型
- `tests/logistics/` — 承运商追踪、面单逻辑

## 八、代码规范

| 工具 | 用途 |
|------|------|
| Ruff | lint + auto-format (替代 Flake8 + isort) |
| mypy --strict | 类型检查，所有文件必须 `pass` |
| pytest + coverage ≥ 80% | 测试覆盖率门禁 |

```bash
ruff check .          # lint
ruff format .         # format
mypy src/             # type-check
pytest tests/         # test
```

## 九、迁移管理 (Alembic)

```bash
# 生成 migration（基于 models.py 变更）
alembic revision --autogenerate -m "add transport_orders table"

# 应用所有未应用的 migration
alembic upgrade head

# 回滚一步
alembic downgrade -1
```

## 十、运维说明

### 日志 & 监控
- 使用 Python `logging` + `structlog`，输出 JSON 格式便于 ELK/EFK 收集。

### CI / CD
- `.github/workflows/ci.yml` — PR 合并前自动跑 lint + typecheck + tests
- Docker build → push ECR → deploy via ECS/AWS

## 十一、常见问题排查

| 问题 | 可能原因 & 解决 |
|------|------------------|
| Alembic migration 失败 | 检查 models.py 中是否有未声明外键的 `relationship()` |
| TMS TransportOrder 创建报错 | 确认 carrier_code 在 CarrierCode enum 中存在 |
| Hub-and-Spoke Dijkstra 无结果 | 检查 hub_connections 表中 from/to 是否连通 |

## 十二、开发约定

1. **模型变更**：修改 `src/models/*.py` → `alembic revision --autogenerate -m "..."` → `alembic upgrade head`
2. **API 新增端点**：在对应模块的 service + router 中实现，保持 Pydantic schema 与 ORM model 分离
3. **Celery Task**：写入 `src/tasks/`，通过 `celery -A worker.celery worker --loglevel=info` 启动
