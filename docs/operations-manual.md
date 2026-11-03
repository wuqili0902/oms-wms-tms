# OMS-WMS-TMS 一体化物流平台 — 操作手册（API 参考）

> **版本**: 0.1.0
> **更新日期**: 2026-09-14
> **适用环境**: 开发 / 测试 / 生产
> **配套文档**：岗位作业流程见 [`docs/operations-sop.md`](./operations-sop.md)（按订单员/仓管员/调度员/管理员角色组织）

> 本手册聚焦 **API 接口细节**（请求/响应格式、参数）。若你关心"每天要做什么业务、按什么顺序操作",请阅读 `operations-sop.md`。

---

## 目录

1. [系统概述](#1-系统概述)
2. [环境与部署](#2-环境与部署)
3. [认证与权限](#3-认证与权限)
4. [订单管理 (OMS)](#4-订单管理-oms)
5. [仓库管理 (WMS)](#5-仓库管理-wms)
6. [运输管理 (TMS)](#6-运输管理-tms)
7. [物流运单](#7-物流运单)
8. [条码管理](#8-条码管理)
9. [PDA 离线同步](#9-pda-离线同步)
10. [通知系统](#10-通知系统)
11. [数据分析](#11-数据分析)
12. [电商对接](#12-电商对接)
13. [Webhook 配置](#13-webhook-配置)
14. [后台管理 (Admin)](#14-后台管理-admin)
15. [健康检查与监控](#15-健康检查与监控)
16. [常见问题](#16-常见问题)

---

## 1. 系统概述

本平台集成 **OMS（订单管理）**、**WMS（仓库管理）**、**TMS（运输管理）** 三大核心模块，提供从订单接入、仓库作业、运输调度到签收跟踪的全链路物流管理能力。

### 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | FastAPI + SQLAlchemy async |
| 数据库 | PostgreSQL 16 |
| 缓存/消息 | Redis 7 |
| 异步任务 | Celery + Redis broker |
| 前端 | Vue 3 + TypeScript + Element Plus |
| 容器化 | Docker + Docker Compose |
| 编排 | Kubernetes (Helm Chart) |
| CI/CD | GitHub Actions → GHCR → Helm deploy |

### 模块架构

```
┌─────────────────────────────────────────────────────┐
│                    Nginx 反向代理                      │
├─────────────────────────────────────────────────────┤
│  /admin/*    →  Admin HTML UI (Jinja2)              │
│  /api/v1/*   →  REST API                            │
│  /docs       →  Swagger UI (DEBUG 模式)              │
├─────────────────────────────────────────────────────┤
│  认证层: JWT + RBAC (User → Role → Permission)       │
├──────────┬──────────┬──────────┬────────────────────┤
│   OMS    │   WMS    │   TMS    │  Logistics/Barcode │
│  订单管理 │  仓库管理 │  运输管理 │   运单/条码         │
├──────────┴──────────┴──────────┴────────────────────┤
│  Core: Outbox / Cache / Notification / Webhooks     │
├─────────────────────────────────────────────────────┤
│  PostgreSQL  │  Redis  │  Celery Worker/Beat         │
└─────────────────────────────────────────────────────┘
```

---

## 2. 环境与部署

### 2.1 本地开发环境

```bash
# 1. 克隆代码
git clone https://github.com/wuqili0902/oms-wms-tms.git
cd oms-wms-tms

# 2. 复制环境变量
cp .env.example .env

# 3. 启动依赖服务
docker compose up -d postgres redis

# 4. 安装 Python 依赖
pip install -r requirements.txt

# 5. 执行数据库迁移
alembic upgrade head

# 6. 启动开发服务器
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### 2.2 Docker Compose 部署

```bash
# 完整启动（含 Nginx）
docker compose up -d

# 服务列表
# - postgres:5432  (PostgreSQL)
# - redis:6379     (Redis)
# - app:8000       (FastAPI)
# - nginx:80       (反向代理)
```

### 2.3 生产部署

```bash
# 使用生产配置
cd deploy
cp .env.production.example .env.production
# 编辑 .env.production 填入生产密钥

docker compose -f docker-compose.prod.yml up -d
```

### 2.4 Kubernetes 部署

```bash
# 安装 Helm Chart
helm install tms deploy/helm/tms/ \
  --namespace tms \
  --create-namespace \
  --set image.repository=ghcr.io/wuqili0902/oms-wms-tms \
  --set image.tag=latest

# 查看状态
kubectl get pods -n tms
helm status tms -n tms
```

### 2.5 环境变量说明

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `SECRET_KEY` | 是 | - | JWT 签名密钥（最少 32 字符） |
| `DATABASE_URL` | 生产必填 | sqlite+aiosqlite:///./dev.db | 数据库连接串 |
| `REDIS_URL` | 否 | redis://localhost:6379/0 | Redis 地址 |
| `DEBUG` | 否 | false | 开启 Swagger/ReDoc |
| `CORS_ORIGINS` | 否 | ["*"] | 允许的前端域名 |
| `RATE_LIMIT_REQUESTS` | 否 | 100 | 限流窗口内最大请求数 |
| `RATE_LIMIT_WINDOW` | 否 | 60 | 限流窗口（秒） |
| `LOG_LEVEL` | 否 | info | 日志级别 |
| `SENTRY_DSN` | 否 | - | Sentry 错误追踪 |
| `TESTING` | 否 | false | 测试模式（跳过限流） |

---

## 3. 认证与权限

### 3.1 认证流程

```
注册 → 登录 → 获取 Token → 请求携带 Header
```

#### 注册用户

```http
POST /api/v1/auth/register
Content-Type: application/json

{
  "username": "operator01",
  "email": "op01@example.com",
  "password": "secureP@ss123"
}
```

**响应** (201):
```json
{
  "id": "uuid",
  "username": "operator01",
  "email": "op01@example.com",
  "is_active": true
}
```

#### 登录获取 Token

```http
POST /api/v1/auth/login
Content-Type: application/json

{
  "username": "operator01",
  "password": "secureP@ss123"
}
```

**响应**:
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

#### 使用 Token

所有需要认证的请求携带：
```
Authorization: Bearer <access_token>
```

#### 刷新 Token

```http
POST /api/v1/auth/refresh
Content-Type: application/json

{
  "refresh_token": "eyJ..."
}
```

**Token 有效期**:
- Access Token: 60 分钟
- Refresh Token: 7 天

### 3.2 RBAC 权限模型

```
User ──N:M── Role ──N:M── Permission
```

#### 权限代码格式

`{resource}.{action}`

常用权限：
| 权限代码 | 说明 |
|----------|------|
| `admin.rbac.manage` | 管理角色权限 |
| `admin.user.manage` | 管理用户 |
| `order.view` | 查看订单 |
| `order.create` | 创建订单 |
| `warehouse.manage` | 仓库管理 |
| `transport.manage` | 运输管理 |

#### 角色管理示例

```http
# 创建角色
POST /api/v1/auth/roles
{
  "name": "仓库管理员",
  "code": "wh_admin",
  "description": "仓库管理操作员"
}

# 分配权限
POST /api/v1/auth/roles/{role_id}/permissions
{
  "permission_id": "perm-uuid"
}

# 绑定用户
POST /api/v1/auth/users/{user_id}/roles
{
  "role_id": "role-uuid"
}
```

---

## 4. 订单管理 (OMS)

### 4.1 订单状态机

```
draft → confirmed → processing → picking → completed
  ↓         ↓           ↓          ↓
cancelled cancelled  cancelled  cancelled
```

**状态说明**:
| 状态 | 说明 |
|------|------|
| `draft` | 草稿，可修改/删除 |
| `confirmed` | 已确认，等待处理 |
| `processing` | 处理中 |
| `picking` | 拣货中 |
| `completed` | 已完成（终态） |
| `cancelled` | 已取消（终态） |
| `failed` | 失败（终态） |

### 4.2 创建订单

```http
POST /api/v1/orders
Authorization: Bearer <token>
Content-Type: application/json

{
  "customer_id": "CUST-001",
  "priority": "high",
  "notes": "加急订单",
  "items": [
    {
      "sku": "SKU-A001",
      "product_name": "产品A",
      "quantity": 10,
      "unit_price": "25.50",
      "gtin": "6901234567890"
    },
    {
      "sku": "SKU-B002",
      "product_name": "产品B",
      "quantity": 5,
      "unit_price": "18.00"
    }
  ]
}
```

### 4.3 查询订单

```http
# 列表查询（分页）
GET /api/v1/orders?page=1&page_size=20&status=confirmed

# 单个查询
GET /api/v1/orders/{order_id}

# 状态变更历史
GET /api/v1/orders/{order_id}/history
```

### 4.4 更新订单状态

```http
PUT /api/v1/orders/{order_id}/status
Content-Type: application/json

{
  "target": "confirmed"
}
```

### 4.5 订单拆分与合并

```http
# 拆分订单
POST /api/v1/orders/{order_id}/split
{
  "splits": [
    {"items": [{"sku": "SKU-A001", "quantity": 3}],
     "warehouse_id": "wh-001"},
    {"items": [{"sku": "SKU-A001", "quantity": 7}],
     "warehouse_id": "wh-002"}
  ],
  "reason": "分仓发货"
}

# 合并订单
POST /api/v1/orders/merge
{
  "order_ids": ["order-1", "order-2"],
  "code": "MERGE-001",
  "warehouse_id": "wh-001",
  "note": "同客户合并"
}
```

---

## 5. 仓库管理 (WMS)

### 5.1 仓库与库位

```http
# 创建仓库
POST /api/v1/warehouses
{
  "code": "WH-SH-01",
  "name": "上海主仓",
  "type": "center",
  "address": {"city": "上海", "district": "浦东新区"}
}

# 创建库位
POST /api/v1/warehouses/{wh_id}/locations
{
  "zone": "A",
  "aisle": "01",
  "shelf": "03",
  "bin": "05",
  "location_type": "storage",
  "capacity": 500
}
```

### 5.2 入库操作

```http
# 单个 SKU 入库
POST /api/v1/warehouses/inventory/items?warehouse_id={wh_id}
{
  "sku": "SKU-A001",
  "quantity": 100,
  "batch_no": "BATCH-20260914",
  "expiry_date": "2027-09-14"
}

# 库存查询
GET /api/v1/warehouses/inventory?warehouse_id={wh_id}&sku=SKU-A001
```

### 5.3 出库操作

```http
POST /api/v1/warehouses/inventory/adjust
{
  "warehouse_id": "wh-uuid",
  "location_id": "loc-uuid",
  "sku": "SKU-A001",
  "quantity": -10,
  "reason": "销售出库",
  "batch_no": "BATCH-20260914",
  "picking_strategy": "fefo"
}
```

> `quantity` 带符号:正数入库、负数出库。出库时若不填 `batch_no`,按
> `picking_strategy`(`fefo` 默认 / `fifo` / `batch`)自动选批。
> 请求体即 `src/wms/schemas.py` 的 `InventoryAdjust`;`reference_no` 一类的单据号
> 不是该模型的字段,服务端不读它,请写进 `reason`。

### 5.4 盘点操作

```http
POST /api/v1/warehouses/inventory/adjust-stock-count
{
  "warehouse_id": "wh-uuid",
  "location_id": "loc-uuid",
  "count_results": [
    {"sku": "SKU-A001", "actual_qty": 95},
    {"sku": "SKU-B002", "actual_qty": 50}
  ]
}
```

### 5.5 拣货波次

```http
# 创建拣货波次
POST /api/v1/warehouses/picking-waves
{
  "warehouse_id": "wh-uuid",
  "order_ids": ["order-1", "order-2"]
}

# 开始拣货
POST /api/v1/warehouses/picking-waves/{wave_id}/start

# 完成拣货
POST /api/v1/warehouses/picking-waves/{wave_id}/complete
```

### 5.6 包装与发货

```http
# 创建包装记录（波次必须已 complete）
POST /api/v1/warehouses/packing
{
  "picking_wave_id": "3f0a1b2c-9d8e-4f7a-8b6c-1d2e3f4a5b6c",
  "packed_by": "张三",
  "box_count": 2
}
# 波次也可以写成 "wave_id"（前端「打包记录」表单就是这个键）；两个键都认。
# 422 的情形：缺波次 → 报 picking_wave_id；"wave-0021" 这类不是 id 的值 → 422 并回显该值；
# box_count 非整数或 <1 → 422；波次未完成 → 422「Only completed waves can be packed」。
# 404：波次不存在。

# 创建发货单（order_ids 逐个订单各生成一条发货单；order_id 单条亦可）
POST /api/v1/warehouses/shipments
{
  "order_ids": ["订单uuid-1", "订单uuid-2"],
  "warehouse_id": "仓库uuid 或 仓库编码",
  "tracking_number": "SF1234567890",
  "carrier": "sf_express"
}
# 返回 {"count": 2, "shipments": [ … ]}：发货管理页的「订单ID列表」文本框逐行贴几个订单，
# 就生成几条发货单。每条都带 shipment_no（发货单号，SHIP-YYYYMMDD-XXXXXXXX，唯一）。
# 422：缺 warehouse_id / 没有任何订单 / 订单号不是 uuid → 报 order_ids 并回显该值；
# 404：仓库不存在、订单不存在、packing_record_id 不存在。

# 标记已发货（前端「发货」按钮不发 body，两个字段都可省）
POST /api/v1/warehouses/shipments/{shipment_id}/ship
{
  "tracking_number": "SF1234567890",
  "carrier": "sf_express"
}
# 不发的字段沿用发货单上已有的值；已 shipped/delivered 再点一次 → 422「already shipped」，
# 已 cancelled → 422；shipment_id 不是 uuid → 404。
```

### 5.7 调拨管理

```http
# 创建调拨单
POST /api/v1/warehouses/transfers
{
  "source_warehouse_id": "wh-001",
  "target_warehouse_id": "wh-002",
  "type": "SKU",
  "items": [{"sku": "SKU-A001", "quantity": 20}]
}

# 调拨单列表(含行项目)
GET /api/v1/warehouses/transfers?warehouse_id={wh_id}
```

> 请求体是 `src/wms/schemas.py` 的 `TransferOrderCreate`:
> - **两端都必填**,而且都是仓库 —— 值可以是仓库 UUID,也可以是仓库编码(如 `wh-001`);
>   既不是 UUID 也不是已知编码时,响应会在 `detail` 里点名是哪个字段写错了。
> - 源仓库不能等于目标仓库。
> - `source_warehouse_id` / `source_warehouse_code` / `source_location` 是同一个字段的
>   三种拼法(`source_location` 是移动端 `TransferOrderScreen` 一直在发的键);
>   `target_warehouse_id` / `destination_warehouse_id` 同理。
> - 行数组 `lines` 与 `items` 同义;每行用 `sku`(商品编码)或 `sku_id`(SKU 表 id)
>   点名商品,`quantity` 必须为正数。
> - 这个 API 目前只**创建**和**列出**调拨单:`TransferOrder.status` 停在 `DRAFT`。
>   没有 `PATCH /transfer-orders/{id}/status`,也没有任何调拨状态端点 —— 移动端
>   与旧版前端服务层调用它的代码都已删除,调拨的确认/发运/收货尚未实现。

### 5.8 采购单管理

```http
# 创建采购单
POST /api/v1/warehouses/purchase-orders
{
  "po_number": "PO-20260914-001",
  "vendor_id": "vendor-uuid",
  "expected_date": "2026-10-01",
  "lines": [
    {"sku_id": "sku-uuid", "description": "原料A", "quantity": 100, "unit_price": "15.00"}
  ]
}

# 审批
POST /api/v1/warehouses/purchase-orders/{po_id}/approve

# 收货
POST /api/v1/warehouses/purchase-orders/{po_id}/receive
```

---

## 6. 运输管理 (TMS)

### 6.1 运单状态机

```
draft → dispatched → in_transit → out_for_delivery → delivered
  ↓                                          ↓
cancelled                               exception
```

### 6.2 创建运单

```http
POST /api/v1/transport-orders
{
  "order_no": "ORD-20260914-001",
  "carrier_code": "sf_express",
  "pickup_address": {
    "name": "张三",
    "phone": "13800138000",
    "city": "上海",
    "address": "浦东新区XX路XX号"
  },
  "delivery_address": {
    "name": "李四",
    "phone": "13900139000",
    "city": "北京",
    "address": "朝阳区XX路XX号"
  },
  "freight_amount": "25.00"
}
```

### 6.3 运单跟踪

```http
# 记录跟踪事件
POST /api/v1/tracking-events
{
  "transport_order_id": "order-uuid",
  "event_type": "pickup",
  "location_code": "SH-HUB",
  "latitude": 31.2304,
  "longitude": 121.4737
}

# 查询跟踪事件
GET /api/v1/transport-orders/{order_id}/tracking
```

### 6.4 签收确认 (POD)

```http
POST /api/v1/transport-orders/{order_id}/pod
{
  "signed_by": "李四",
  "signature_type": "digital",
  "signature_image_url": "https://...",
  "delivery_photo_urls": ["https://..."]
}
```

### 6.5 异常处理

```http
# 上报异常
POST /api/v1/exceptions
{
  "transport_order_id": "order-uuid",
  "type": "damage",
  "description": "货物破损",
  "severity": "high"
}

# 解决异常
PATCH /api/v1/exceptions/{exception_id}/resolve
{
  "resolution_notes": "已安排补发"
}
```

### 6.6 退回单

```http
# 创建退回单
POST /api/v1/return-orders
{
  "transport_order_id": "order-uuid",
  "reason": "damaged",
  "carrier_code": "sf_express"
}

# 更新状态
PATCH /api/v1/return-orders/{return_id}/status
{
  "target": "inspected"
}
```

### 6.7 路由规划

```http
# 生成路由计划
POST /api/v1/transport-orders/{order_id}/route-plans?type=auto_gen

# 查询路由计划
GET /api/v1/route-plans/{plan_id}
```

### 6.8 运费计算

```http
POST /api/v1/freight/calculate
{
  "carrier_code": "sf_express",
  "service_type": "standard",
  "weight_kg": 5.0,
  "distance_km": 1200
}
```

### 6.9 中转枢纽

```http
# 创建枢纽
# hub_type（控制台亦写作 type）只接受 primary / secondary / cargo_station；
# 其他值返回 422 并在 errors 里列出该词表。capacity_weight_kg 不得为负。
POST /api/v1/transfer-hubs
{
  "code": "HUB-SH-01",
  "name": "上海分拨中心",
  "hub_type": "primary",
  "city": "上海",
  "capacity_weight_kg": 50000,
  "contact_name": "张强",
  "contact_phone": "13800000000"
}

# 创建枢纽连接（图边）
POST /api/v1/hub-connections
{
  "from_hub_code": "HUB-SH-01",
  "to_hub_code": "HUB-BJ-01",
  "distance_km": 1200,
  "transit_hours": 18
}
```

---

## 7. 物流运单

### 7.1 创建电子运单

```http
POST /api/v1/logistics/waybill/create
{
  "order_id": "order-uuid",
  "carrier_code": "sf",
  "sender_name": "张三",
  "sender_phone": "13800138000",
  "sender_address": "上海市浦东新区XX路",
  "receiver_name": "李四",
  "receiver_phone": "13900139000",
  "receiver_address": "北京市朝阳区XX路",
  "items": [
    {"name": "产品A", "quantity": 2, "weight_kg": 1.5}
  ]
}
```

> **面单号是谁给的**：响应里的 `tracking_source` 说明这一件事，因为两种情况下标签打印出来一模一样。
>
> | `tracking_source` | 含义 |
> | --- | --- |
> | `kdniao` | 配置了 `KDNIAO_EBUSINESS_ID` / `KDNIAO_API_KEY`，面单号由快递鸟返回（`tracking_source_note`：面单号由快递鸟返回） |
> | `local_placeholder` | 未配置快递鸟凭据：面单号由本机按前缀 + 日期 + 订单号哈希拼出，**快递侧没有这张面单**，轨迹查询与运单追踪均不可用 |
>
> 打印 `local_placeholder` 面单前请先确认这一点：贴出去的就是一个快递系统里不存在的号码。

### 7.2 运单查询与跟踪

```http
# 查询运单
GET /api/v1/logistics/waybill/SF1234567890

# 物流跟踪
GET /api/v1/logistics/waybill/SF1234567890/track
```

> 跟踪接口回答"这条轨迹是从哪来的"，没有凭据时它不回答：
>
> | 情况 | 响应 |
> | --- | --- |
> | 配置了快递鸟凭据 | 200，`source: "kdniao"`（快递鸟的轨迹） |
> | 未配置凭据 + `LOGISTICS_MOCK_ENABLED=true` | 200，`source: "mock"`，`status_detail` 以 **【演示数据】** 开头，`source_note` 说明状态由运单号哈希得出 |
> | 未配置凭据 + 未开演示开关 | **501 `NOT_IMPLEMENTED`**，消息点名要配置的 `KDNIAO_EBUSINESS_ID` / `KDNIAO_API_KEY` |
> | 承运商接口（`CARRIER_API_ENDPOINTS`）调用失败 | 502「查单失败：…」——失败的调用不会退回演示数据 |
>
> 旧版本在没有凭据时按运单号哈希给出 已揽收 / 运输中 / 派送中 / 已签收（还带一条"到达上海转运中心"）。
> 按 SOP，客服会把这条状态转述给客户，所以那是一次不存在的签收被说成发生了。
> 演示开关只用于开发界面：`LOGISTICS_MOCK_ENABLED=true`，返回的每一行都标着 演示数据 / `source: "mock"`。

### 7.3 运单作废与打印

```http
# 作废运单
POST /api/v1/logistics/waybill/SF1234567890/void

# 标记已打印
POST /api/v1/logistics/waybill/SF1234567890/print
```

---

## 8. 条码管理

### 8.1 生成条码

```http
POST /api/v1/barcode/generate
{
  "gtin_prefix": "12345678901",
  "entity_type": "product",
  "entity_id": "sku-uuid",
  "format": "ean13"
}
```

### 8.2 验证 GTIN

```http
POST /api/v1/barcode/validate
{
  "gtin": "6901234567890"
}

# 响应
{
  "valid": true,
  "gtin": "6901234567890",
  "format": "ean13"
}
```

### 8.3 批量生成（Excel 上传）

```http
POST /api/v1/barcode/excel/upload
Content-Type: multipart/form-data

file: barcodes.xlsx
```

### 8.4 标签模板

```http
# 创建模板
POST /api/v1/barcode/templates
{
  "name": "标准标签",
  "code": "STD-LABEL",
  "format": "zpl",
  "width_mm": 50,
  "height_mm": 30,
  "content": {
    "fields": ["gtin", "name", "price"]
  }
}

# 查询模板
GET /api/v1/barcode/templates
```

---

## 9. PDA 离线同步

### 9.1 离线操作入队

```http
POST /api/v1/pda/mutations
{
  "device_id": "PDA-001",
  "entity_type": "inventory",
  "entity_id": "inv-uuid",
  "operation": "UPDATE",
  "payload": {"quantity": 50}
}
```

### 9.2 同步处理

```http
POST /api/v1/pda/sync

# 响应
{
  "processed": 10,
  "succeeded": 9,
  "failed": 1
}
```

### 9.3 WebSocket 实时同步

```
ws://host/api/v1/pda/ws?client_id=PDA-001&token=eyJ...
```

---

## 10. 通知系统

### 10.1 通知类型

| 类型 | 说明 |
|------|------|
| `order_status_change` | 订单状态变更 |
| `order_created` | 新订单创建 |
| `low_stock_alert` | 库存预警 |
| `transport_status_change` | 运输状态变更 |
| `delivery_confirmed` | 签收确认 |
| `exception_occurred` | 异常发生 |
| `system_alert` | 系统告警 |

### 10.2 通知渠道

- **WebSocket**: 实时推送（默认）
- **Email**: 邮件通知
- **Push**: 移动端推送（需 Firebase 配置）

### 10.3 偏好设置

```http
# 查询偏好
GET /api/v1/notifications/preferences

# 更新偏好
PUT /api/v1/notifications/preferences
[
  {
    "notification_type": "order_status_change",
    "channel": "websocket",
    "enabled": true
  },
  {
    "notification_type": "low_stock_alert",
    "channel": "email",
    "enabled": true
  }
]
```

### 10.4 WebSocket 推送

```
ws://host/api/v1/notifications/ws?token=eyJ...
```

---

## 11. 数据分析

### 11.1 仪表盘

```http
GET /api/v1/analytics/dashboard

# 响应
{
  "stats": {
    "order_count": 1250,
    "user_count": 15,
    "inventory_count": 3200,
    "warehouse_count": 5
  },
  "order_trends": [...],
  "status_distribution": [...],
  "low_stock": [...],
  "recent_orders": [...]
}
```

### 11.2 趋势分析

```http
GET /api/v1/analytics/order-trends?days=30
GET /api/v1/analytics/status-distribution
GET /api/v1/analytics/low-stock
```

### 11.3 ABC-XYZ 库存分析

```http
# ABC 分析（按消耗价值分类）
GET /api/v1/analytics/abc-analysis?months=6

# XYZ 分析（按需求波动分类）
GET /api/v1/analytics/xyz-analysis?months=6

# ABC-XYZ 矩阵
GET /api/v1/analytics/abc-xyz-matrix?months=6
```

**分类说明**:
| ABC | 含义 | XYZ | 含义 |
|-----|------|-----|------|
| A | 高价值（前 20% SKU，占 80% 价值） | X | 稳定需求（CV < 0.5） |
| B | 中价值（次 30% SKU） | Y | 中等波动（0.5 ≤ CV < 1.0） |
| C | 低价值（后 50% SKU） | Z | 不规则需求（CV ≥ 1.0） |

---

## 12. 电商对接

### 12.1 Shopify Webhook

```http
POST /api/v1/connectors/shopify/webhook
X-Shopify-Hmac-Sha256: <hmac-signature>
Content-Type: application/json

{
  "id": 12345,
  "email": "customer@example.com",
  "line_items": [...],
  "total_price": "99.00"
}
```

### 12.2 Amazon SP-API

#### 导入订单 `POST /api/v1/connectors/amazon/orders`

body 就是 **SP-API 自己返回的 `Order` 对象**（PascalCase 键名），原样粘贴即可，
不需要改名。旧文档写的 `amazon_order_id` / `items` 小写写法服务端**不认**，
按旧文档发会得到 422。

```http
POST /api/v1/connectors/amazon/orders
{
  "AmazonOrderId": "111-1234567-1234567",
  "PurchaseDate": "2026-09-14T10:00:00Z",
  "OrderStatus": "Unshipped",
  "BuyerEmail": "buyer@example.com",
  "OrderTotal": { "Amount": "150.00", "CurrencyCode": "CNY" },
  "ShippingAddress": { "Name": "...", "City": "Shanghai", "CountryCode": "CN" },
  "OrderItems": [
    { "SellerSKU": "SKU-BOLT-100", "Title": "M8 Bolt", "QuantityOrdered": 2,
      "ItemPrice": { "Amount": "75.00" }, "ASIN": "B0ABCDEF12" }
  ]
}

201 Created
{
  "status": "imported",
  "order_id": "9f0c...",                       // OMS 订单 UUID
  "order_no": "ORD-20260914-1A2B3C4D",         // 单据上印的订单号
  "amazon_order_id": "111-1234567-1234567",
  "line_count": 1,
  "total_amount": "150.00"                     // 按行算：2 × 75.00
}
```

要点（都是 422/404，不再是 500，也不再"导入成功"）：

| 情况 | 结果 |
|------|------|
| 无 `AmazonOrderId` | 422，报出 `AmazonOrderId`（没有这个号，追踪回传/对账/亚马逊工单都无从谈起） |
| 无 `OrderItems` | 422「没有商品行的订单不能被拣货、发货、开票」 |
| 某行既无 SKU 又无条码 | 422，报出是第几行 `OrderItems[i]` |
| `QuantityOrdered` 是文本（如 `"2 items"`）或 ≤ 0 | 422，报出该行与原始值 |
| `ItemPrice.Amount` 不是金额 | 422，报出该行 |
| `ShippingAddress`/`OrderTotal` 为 null（未发货单常见） | 正常导入，金额按行合计 |
| FBA 行没有 `SellerSKU` | 用 `ASIN` 作为 sku；`ASIN` **不会**写进 `gtin` 列（扫码枪按 EAN 读它） |

订单总价按**商品行**算，不用亚马逊的 `OrderTotal`（后者含亚马逊向买家收的运费）。
导入的订单状态为 `pending`，优先级 `medium`，备注写来源。

#### 记录发货交接 `POST /api/v1/connectors/amazon/tracking`

```http
POST /api/v1/connectors/amazon/tracking
{
  "amazon_order_id": "111-1234567-1234567",   // 必填；amazonOrderId 也可
  "carrier_code": "SF",                        // 必填；Amazon 认可的承运商编码
  "tracking_number": "SF1234567890",           // 必填
  "status": "Shipped"                          // 可省略
}

200 OK
{
  "status": "received",
  "amazon_order_id": "111-1234567-1234567",
  "carrier_code": "SF",
  "tracking_number": "SF1234567890",
  "sync_status": "not_configured"              // queued = 已排队回传
}
```

- 三项缺一律 422 并点名缺哪一项；空 body 也照样告诉你缺什么（以前空 body 也回
  `received`，屏幕上看起来"已同步"，其实传出去的是一个空壳）。
- `sync_status`：**未配置 SP-API 凭据时是 `not_configured`**——交接已在本地记录，
  但没有回传亚马逊。填好 `AMAZON_SP_API_CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN`
  后为 `queued`。
- `{"data": {...}}` 信封格式同样接受；契约外的键 422。

#### 支持的能力范围

已实现：**订单导入**、**发货交接记录**。
未实现（函数返回 `{implemented: false, status: "not_implemented"}` 并说明需要哪个
SP-API 调用，不返回看似成功的假数据，且**没有任何路由调用它们**）：订单状态轮询
`poll_order_status`、状态回写 `sync_order_status`、追踪上传
`upload_tracking_to_amazon`、FBA 发货标记 `mark_fba_shipped`、库存同步
`sync_inventory_to_amazon`。控制台上已标注，不要在排产/对账里依赖这些能力。

### 12.3 连接器管理接口

侧边栏「连接器管理」（`/connectors/manage`）读取下面三个端点。旧版页面构建在
`GET /connectors/status` 与 `POST /connectors/{id}/sync` 上，而这两个 URL
在服务端**从来不存在**：页面只会显示"暂无连接器数据"（失败只写进
`console.warn`，操作员看不到），每个「同步」按钮都是 404。

#### 连接列表 `GET /api/v1/connectors/status`

```http
GET /api/v1/connectors/status
200 OK
[
  {
    "id": "amazon", "name": "Amazon SP-API", "type": "amazon",
    "status": "not_configured",          // active | not_configured | disabled
    "configured": false,
    "last_sync": null,
    "capabilities": {
      "order_import": "implemented",
      "tracking_handover_record": "implemented",
      "tracking_upload": "not_implemented",
      "order_status_poll": "not_implemented",
      "inventory_sync": "not_implemented"
    },
    "credentials": [
      { "env": "AMAZON_SP_API_CLIENT_ID", "set": false },
      { "env": "AMAZON_SP_API_REFRESH_TOKEN", "set": false },
      { "env": "AMAZON_SP_API_REGION", "value": "us" }
    ],
    "note": "凭据写在服务器配置（.env / 环境变量）里，不经网页传输；此接口只回报是否已配置，不回传密钥值。"
  },
  { "id": "shopify", ... "capabilities": { "order_push": "implemented", "order_pull": "not_available", ... } }
]
```

- 注册表是**代码**，不是数据表：本系统的连接器只有 `amazon` 与 `shopify`。
  SAP / Oracle / EDI 连接器**不存在**（README 与功能表已改口：那些只有报文模型与
  序列化，没有对外传输端点）。
- `capabilities` 逐项说明这个构建里到底做不做：`implemented` / `not_implemented`
  / `not_available`。
- `credentials` 只回报**变量名**与**是否已配置**，绝不回传密钥值。凭据写在服务器
  `.env` / 环境变量里；配置页（`/connectors/amazon-config/:id`、
  `/connectors/shopify-config/:id`）已改为只读的"配置说明"，不再让操作员往网页里
  输入 AWS Access Key 或 Shopify Admin API Token——SP-API 用 LWA 的
  client id/secret + refresh token 认证，Shopify 用应用自己的 `SECRET_KEY`
  做 HMAC 验签，那两个字段本系统都用不上，也没有端点接收它们。

#### 单个连接器 `GET /api/v1/connectors/{id}`

`amazon` / `shopify`（大小写不敏感）；其他 id 一律 404，并在 message 里说明
"the connectors here are amazon and shopify"。

#### 同步 `POST /api/v1/connectors/{id}/sync`

**没有可"同步"的东西，这个端点不会返回 200。**

| 调用 | 结果 |
|------|------|
| `POST /connectors/amazon/sync` | 501 `NOT_IMPLEMENTED`：拉单/状态轮询/库存同步需要 SP-API 调用，本系统未实现；并指向可用的 `POST /connectors/amazon/orders`（导入）与 `/tracking`（交接记录） |
| `POST /connectors/shopify/sync` | 422 `VALIDATION_ERROR`：Shopify 是推送式对接，没有可拉取的数据 |
| `POST /connectors/{未知}/sync` | 404 `NOT_FOUND` |

界面上已删除「同步」按钮——它以前点下去就是一句"同步成功/失败"，而失败的原因
（接口不存在）操作员看不到，成功的语义（同步真的发生了）也不存在。
---

## 13. Webhook 配置

### 13.1 创建 Webhook 目标

```http
POST /api/v1/webhooks
{
  "name": "订单通知",
  "url": "https://your-system.com/webhook",
  "secret": "your-webhook-secret",
  "events": ["order.created", "order.status_changed"]
}
```

### 13.2 支持的事件

| 事件 | 说明 |
|------|------|
| `order.created` | 新订单创建 |
| `order.status_changed` | 订单状态变更 |
| `order.cancelled` | 订单取消 |
| `inventory.low_stock` | 库存预警 |
| `transport.status_changed` | 运输状态变更 |
| `delivery.confirmed` | 签收确认 |

### 13.3 签名验证

Webhook 请求头包含：
```
X-Webhook-Event: order.created
X-Webhook-Signature: <hmac-sha256-signature>
X-Webhook-Timestamp: <unix-timestamp>
```

验证方式：
```python
import hmac, hashlib
msg = f"{timestamp}:{payload}"
expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
```

---

## 14. 后台管理 (Admin)

### 14.1 访问地址

```
http://your-domain/admin/
```

### 14.2 功能模块

| 页面 | 路径 | 说明 |
|------|------|------|
| 仪表盘 | `/admin/` | 统计概览、图表、库存预警 |
| 订单管理 | `/admin/orders` | 订单列表、详情、状态变更 |
| 仓库管理 | `/admin/warehouses` | 仓库 CRUD |
| 库存管理 | `/admin/inventory` | 库存查询 |
| 设备管理 | `/admin/devices` | PDA 设备管理 |
| 标签模板 | `/admin/templates` | 条码标签模板 |
| 用户管理 | `/admin/users` | 用户列表、创建、启禁用 |
| 运输管理 | `/admin/transport-orders` | 运单列表 |
| 路由计划 | `/admin/route-plans` | 路由规划 |
| 退回管理 | `/admin/returns` | 退回单列表 |
| 异常管理 | `/admin/exceptions` | 运输异常 |
| 需求预测 | `/admin/forecast` | 需求预测 |
| ML 预测 | `/admin/ml/forecast` | 机器学习预测 |
| 数据导入 | `/admin/import` | CSV 导入订单/库存 |
| Webhook | `/admin/webhooks` | Webhook 管理 |

### 14.3 CSV 导出

```
GET /admin/export/orders          → 订单导出
GET /admin/export/inventory       → 库存导出
GET /admin/export/transport-orders → 运单导出
GET /admin/export/returns         → 退回单导出
GET /admin/export/exceptions      → 异常导出
GET /admin/export/route-plans     → 路由计划导出
GET /admin/export/ml-forecast     → 预测数据导出
```

---

## 15. 健康检查与监控

### 15.1 健康探针

```http
# 存活探针
GET /health
→ 200 OK

# 完整健康检查（含数据库）
GET /api/v1/health
→ 200 OK

# 就绪探针（数据库 + Redis）
GET /api/v1/ready
→ 200 OK
```

### 15.2 监控端点

```http
# Prometheus 指标
GET /metrics
→ Prometheus 文本格式

# OpenAPI 文档（DEBUG 模式）
GET /docs      → Swagger UI
GET /redoc     → ReDoc
GET /openapi.json → OpenAPI JSON
```

### 15.3 日志格式

生产环境使用 JSON 格式：
```json
{
  "ts": "2026-09-14T10:00:00.000Z",
  "level": "info",
  "logger": "src.oms.router",
  "message": "Order created",
  "extra": {
    "order_id": "uuid",
    "user_id": "uuid"
  }
}
```

### 15.4 数据库迁移

```bash
# 查看当前版本
alembic current

# 升级到最新
alembic upgrade head

# 回滚一步
alembic downgrade -1

# 生成迁移脚本
alembic revision --autogenerate -m "description"
```

---

## 16. 常见问题

### Q1: 登录返回 401 Invalid credentials

**检查**:
1. 用户名/密码是否正确
2. 用户是否被禁用 (`is_active = false`)
3. 密码是否满足最小 8 位要求

### Q2: 请求返回 429 Rate limit exceeded

**原因**: 超过限流阈值（默认 100 次/60 秒）

**解决**:
- 等待窗口重置
- 联系管理员调整 `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW`
- 开发环境可设置 `TESTING=true` 跳过限流

### Q3: 数据库迁移失败 "column already exists"

**原因**: Alembic 迁移链断裂

**解决**:
```bash
# 查看现有迁移
alembic history

# 手动标记为已应用
alembic stamp head

# 重新生成迁移
alembic revision --autogenerate -m "fix"
```

### Q4: WebSocket 连接断开

**检查**:
1. Token 是否过期
2. 网络是否支持 WebSocket
3. Nginx 配置是否支持 WebSocket 代理

```nginx
# Nginx WebSocket 配置
location /api/v1/notifications/ws {
    proxy_pass http://app;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

### Q5: Celery 任务不执行

**检查**:
```bash
# 查看 Worker 状态（-A 指向 src.celeryconf；src.tasks 里没有 Celery app 对象）
celery -A src.celeryconf inspect active
celery -A src.celeryconf inspect registered

# 查看 beat 安排了什么（表在 src/celery_app.py 的 beat_schedule，清单见部署指南 2.3.1）
celery -A src.celeryconf inspect scheduled

# 启动 worker / beat
celery -A src.celeryconf worker --loglevel=info --concurrency=4
celery -A src.celeryconf beat --loglevel=info
```

> 任务没跑起来时先看这两条：`inspect registered` 里有没有那个任务名，`inspect scheduled` 里 beat 排的是不是同一个名字。
> 名字对不上就是"调度了一个没注册的任务"——beat 只会打一行 `Received unregistered task`，界面与接口都不会有任何异常。

### Q6: Redis 连接失败

**检查**:
```bash
# 测试连接
redis-cli ping

# 查看 Redis 信息
redis-cli info server
```

### Q7: 前端跨域错误

**解决**:
1. 检查 `CORS_ORIGINS` 环境变量
2. 确保前端域名在允许列表中
3. 开发环境可设为 `["*"]`

---

## 附录: API 快速参考

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/register` | 注册 |
| POST | `/api/v1/auth/login` | 登录 |
| POST | `/api/v1/auth/refresh` | 刷新 Token |
| GET | `/api/v1/auth/me` | 当前用户 |

### OMS

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/orders` | 创建订单 |
| GET | `/api/v1/orders` | 订单列表 |
| GET | `/api/v1/orders/{id}` | 订单详情 |
| PUT | `/api/v1/orders/{id}/status` | 更新状态 |
| DELETE | `/api/v1/orders/{id}` | 删除订单 |

### WMS

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/warehouses` | 创建仓库 |
| GET | `/api/v1/warehouses` | 仓库列表 |
| POST | `/api/v1/warehouses/inventory/items` | 入库 |
| POST | `/api/v1/warehouses/inventory/adjust` | 出库调整 |
| POST | `/api/v1/warehouses/inventory/adjust-stock-count` | 盘点 |
| POST | `/api/v1/warehouses/picking-waves` | 创建拣货波次 |
| POST | `/api/v1/warehouses/shipments` | 创建发货单 |

### TMS

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/transport-orders` | 创建运单 |
| GET | `/api/v1/transport-orders` | 运单列表 |
| PUT | `/api/v1/transport-orders/{id}/status` | 更新状态 |
| POST | `/api/v1/tracking-events` | 记录跟踪 |
| POST | `/api/v1/transport-orders/{id}/pod` | 签收确认 |
| POST | `/api/v1/exceptions` | 上报异常 |

### 物流

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/logistics/waybill/create` | 创建运单（`tracking_source` = `kdniao` / `local_placeholder`，见 7.1） |
| GET | `/api/v1/logistics/waybill/list` | 运单列表 |
| GET | `/api/v1/logistics/waybill/{tracking}` | 查询运单 |
| GET | `/api/v1/logistics/waybill/{tracking}/track` | 物流跟踪：`source` 说明轨迹出处；无快递鸟凭据 → **501**，承运商接口调用失败 → 502（见 7.2） |
| POST | `/api/v1/logistics/waybill/{tracking}/void` | 作废运单 |
| POST | `/api/v1/logistics/waybill/{tracking}/print` | 标记已打印并返回取图地址 |

### 条码

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/barcode/generate` | 生成条码 |
| POST | `/api/v1/barcode/validate` | 验证 GTIN |
| POST | `/api/v1/barcode/scan` | 扫码记录 |

### 通知

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/notifications` | 通知列表 |
| PUT | `/api/v1/notifications/preferences` | 偏好设置 |
| WS | `/api/v1/notifications/ws` | WebSocket 推送 |

### 分析

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/analytics/dashboard` | 仪表盘 |
| GET | `/api/v1/analytics/order-trends` | 趋势分析 |
| GET | `/api/v1/analytics/low-stock` | 库存预警 |
