# 手工验证指南 — oms-wms-tms

API 基础路径：`http://localhost:8000/api/v1`  
认证方式：`Authorization: Bearer <token>`（除注册/登录外所有接口都需要）

可以用 `curl`、`httpie`、Postman 或浏览器 DevTools 测试。

---

## 1. 前期准备 — 注册 & 登录

### 1.1 注册用户

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "email": "admin@test.com",
    "password": "test123456"
  }'
```

**期望响应：** 201 Created
```json
{
  "id": "uuid-...",
  "username": "admin",
  "email": "admin@test.com",
  "is_active": true
}
```

### 1.2 登录获取 Token

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "test123456"
  }'
```

**期望响应：** 200 OK
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

将 `access_token` 设为环境变量方便后续使用（Windows PowerShell）：
```powershell
$token = "Bearer eyJhbGciOiJIUzI1NiIs..."
```

---

## 2. 认证模块 — Auth

### 2.1 重复注册 → 400

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "email": "dup@test.com", "password": "test123456"}'
```
**期望：** 400 Bad Request，内容包含 `already exists`

### 2.2 错误密码 → 401

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "wrongpassword"}'
```
**期望：** 401 Unauthorized

### 2.3 获取当前用户 /me

```bash
curl http://localhost:8000/api/v1/auth/me -H "Authorization: $token"
```
**期望：** 200，返回 `{"username": "admin", ...}`

### 2.4 无 Token 访问 → 401

```bash
curl http://localhost:8000/api/v1/auth/me
```
**期望：** 401

### 2.5 用户列表

```bash
curl http://localhost:8000/api/v1/auth/users -H "Authorization: $token"
```
**期望：** 200，用户数组

### 2.6 创建角色

```bash
curl -X POST http://localhost:8000/api/v1/auth/roles \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "仓库管理员",
    "code": "wh_manager",
    "description": "管理仓库作业"
  }'
```
**期望：** 201 Created

### 2.7 重复角色 → 422

```bash
curl -X POST http://localhost:8000/api/v1/auth/roles \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{"name": "其他", "code": "wh_manager"}'
```
**期望：** 422

### 2.8 角色列表

```bash
curl http://localhost:8000/api/v1/auth/roles -H "Authorization: $token"
```
**期望：** 200，列表中包含 `wh_manager`

### 2.9 权限列表

```bash
curl http://localhost:8000/api/v1/auth/permissions -H "Authorization: $token"
```
**期望：** 200，权限数组

### 2.10 Token 刷新

```bash
# 先用登录拿到 refresh_token
$result = curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "test123456"}'
$refresh = ($result | ConvertFrom-Json).refresh_token

curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\": \"$refresh\"}"
```
**期望：** 200，返回新的 `access_token` + `refresh_token`

### 2.11 错误 Refresh → 401

```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "garbage-token"}'
```
**期望：** 401

### 2.12 登出

```bash
curl -X POST http://localhost:8000/api/v1/auth/logout \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\": \"$refresh\"}"
```
**期望：** 200，`{"message": "Logged out successfully"}`

登出后该 refresh_token 立即失效，再次 refresh 应返回 401。

---

## 3. 仓储管理 — WMS

> 以下请求都需要 `Authorization: Bearer <token>` 头，省略不写。

### 3.1 创建仓库

```bash
curl -X POST http://localhost:8000/api/v1/warehouses \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "WH-001",
    "name": "主仓库",
    "address": "上海市浦东新区XX路100号",
    "type": "center"
  }'
```
**期望：** 201，返回 warehouse ID

记下返回的 `id` 为 `$wh_id`。

### 3.2 重复仓库编码 → 422

```bash
curl -X POST http://localhost:8000/api/v1/warehouses \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{"code": "WH-001", "name": "重复仓库"}'
```
**期望：** 422

### 3.3 仓库列表

```bash
curl http://localhost:8000/api/v1/warehouses -H "Authorization: $token"
```
**期望：** 200，仓库数组

### 3.4 按 ID 获取仓库

```bash
curl http://localhost:8000/api/v1/warehouses/$wh_id -H "Authorization: $token"
```
**期望：** 200，返回该仓库详情

### 3.5 不存在的仓库 → 404

```bash
curl http://localhost:8000/api/v1/warehouses/00000000-0000-0000-0000-000000000000 \
  -H "Authorization: $token"
```
**期望：** 404

### 3.6 创建库位

```bash
curl -X POST "http://localhost:8000/api/v1/warehouses/$wh_id/locations" \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{
    "zone": "A",
    "aisle": "01",
    "shelf": "02",
    "bin": "03",
    "type": "storage"
  }'
```
**期望：** 201，返回库位详情

字段说明：
- `zone`：库区
- `aisle`：巷道
- `shelf`：货架
- `bin`：货位
- `type`：取值 `storage|picking|receiving|shipping|damage`

记下返回的库位 `id` 为 `$loc_id`。

### 3.7 库位列表

```bash
curl "http://localhost:8000/api/v1/warehouses/$wh_id/locations" \
  -H "Authorization: $token"
```
**期望：** 200，库位数组

### 3.8 库存调整（入库 +100）

```bash
curl -X POST http://localhost:8000/api/v1/warehouses/inventory/adjust \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d "{
    \"warehouse_id\": \"$wh_id\",
    \"location_id\": \"$loc_id\",
    \"sku\": \"SKU-001\",
    \"quantity\": 100,
    \"reason\": \"采购入库\"
  }"
```
**期望：** 200，返回 `{"quantity": 100, "reserved_qty": 0, ...}`

字段说明：
- `warehouse_id` / `location_id`：刚才创建的值
- `sku`：商品编码
- `quantity`：正数=入库，负数=出库
- `reason`：调整原因

### 3.9 库存调整（出库 -30）

```bash
curl -X POST http://localhost:8000/api/v1/warehouses/inventory/adjust \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d "{
    \"warehouse_id\": \"$wh_id\",
    \"location_id\": \"$loc_id\",
    \"sku\": \"SKU-001\",
    \"quantity\": -30,
    \"reason\": \"拣货出库\"
  }"
```
**期望：** 200，`{"quantity": 70, ...}`（100 - 30 = 70）

### 3.10 库存查询

```bash
curl "http://localhost:8000/api/v1/warehouses/inventory?sku=SKU-001" \
  -H "Authorization: $token"
```
**期望：** 200，`{"quantity": 70, "available_qty": 70, ...}`

### 3.11 移库记录

```bash
curl "http://localhost:8000/api/v1/warehouses/inventory/movements?warehouse_id=$wh_id" \
  -H "Authorization: $token"
```
**期望：** 200，至少有 2 条移库记录（入库+出库）

### 3.12 创建拣货波次

```bash
curl -X POST http://localhost:8000/api/v1/warehouses/picking-waves \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d "{
    \"warehouse_id\": \"$wh_id\",
    \"order_ids\": [\"$wh_id\"]
  }"
```
**期望：** 200 或 201（取决于后端逻辑）

### 3.13 拣货波次列表

```bash
curl "http://localhost:8000/api/v1/warehouses/picking-waves?warehouse_id=$wh_id" \
  -H "Authorization: $token"
```
**期望：** 200

---

## 4. 终端管理 — TMS

### 4.1 注册设备

```bash
curl -X POST http://localhost:8000/api/v1/devices \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "PDA-001",
    "name": "扫描枪 #1",
    "device_type": "pda",
    "platform": "android",
    "os_version": "14.0",
    "app_version": "2.1.0",
    "config": {"scan_modes": ["barcode", "qrcode"]}
  }'
```
**期望：** 201

记下返回的 `id` 为 `$dev_id`。

### 4.2 重复设备编码 → 422

```bash
curl -X POST http://localhost:8000/api/v1/devices \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{"code": "PDA-001", "device_type": "phone", "platform": "ios"}'
```
**期望：** 422，含 `already exists`

### 4.3 设备列表

```bash
curl http://localhost:8000/api/v1/devices -H "Authorization: $token"
```
**期望：** 200，设备数组

### 4.4 按类型过滤

```bash
curl "http://localhost:8000/api/v1/devices?device_type=pda" \
  -H "Authorization: $token"
```
**期望：** 200

### 4.5 获取单个设备

```bash
curl http://localhost:8000/api/v1/devices/$dev_id -H "Authorization: $token"
```
**期望：** 200

### 4.6 不存在的设备 → 404

```bash
curl http://localhost:8000/api/v1/devices/00000000-0000-0000-0000-000000000000 \
  -H "Authorization: $token"
```
**期望：** 404

### 4.7 更新设备

```bash
curl -X PATCH http://localhost:8000/api/v1/devices/$dev_id \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "扫描枪 #1（已更新）",
    "app_version": "2.2.0"
  }'
```
**期望：** 200，name 和 app_version 已更新

### 4.8 设备心跳

```bash
curl -X POST "http://localhost:8000/api/v1/devices/$dev_id/heartbeat" \
  -H "Authorization: $token"
```
**期望：** 200，`{"status": "online", ...}`

### 4.9 创建设备会话

```bash
curl -X POST "http://localhost:8000/api/v1/devices/$dev_id/sessions" \
  -H "Authorization: $token"
```
**期望：** 201，`logout_at` 为 null

记下返回的 `id` 为 `$sess_id`。

### 4.10 会话列表

```bash
curl "http://localhost:8000/api/v1/devices/$dev_id/sessions" \
  -H "Authorization: $token"
```
**期望：** 200，含刚创建的会话

### 4.11 结束会话

```bash
curl -X DELETE "http://localhost:8000/api/v1/devices/$dev_id/sessions/$sess_id" \
  -H "Authorization: $token"
```
**期望：** 200，`logout_at` 不为 null

### 4.12 记录同步日志

```bash
curl -X POST "http://localhost:8000/api/v1/devices/$dev_id/sync" \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{
    "sync_type": "download",
    "status": "completed",
    "records_count": 42
  }'
```
**期望：** 201

### 4.13 同步日志列表

```bash
curl "http://localhost:8000/api/v1/devices/$dev_id/sync" \
  -H "Authorization: $token"
```
**期望：** 200，含 records_count=42 的记录

---

## 5. 条码模块 — Barcode

### 5.1 创建标签模板

```bash
curl -X POST http://localhost:8000/api/v1/barcode/templates \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "标准托盘标签",
    "code": "PALLET-ZPL",
    "format": "zpl",
    "width_mm": 100,
    "height_mm": 75,
    "content": {"fields": ["sku", "qty", "location"]},
    "is_default": true
  }'
```
**期望：** 201

### 5.2 标签模板列表

```bash
curl http://localhost:8000/api/v1/barcode/templates -H "Authorization: $token"
```
**期望：** 200

### 5.3 生成条码

```bash
curl -X POST http://localhost:8000/api/v1/barcode/generate \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{
    "gtin_prefix": "8901234567",
    "entity_type": "inventory",
    "entity_id": "00000000-0000-0000-0000-000000000001",
    "format": "code128"
  }'
```
**期望：** 201，返回 13 位 GTIN

### 5.4 校验条码（有效）

```bash
curl -X POST http://localhost:8000/api/v1/barcode/validate \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{"gtin": "6901234567892"}'
```
**期望：** 200，`{"valid": true}`

### 5.5 校验条码（无效）

```bash
curl -X POST http://localhost:8000/api/v1/barcode/validate \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{"gtin": "6901234567890"}'
```
**期望：** 200，`{"valid": false}`

### 5.6 扫描记录

```bash
curl -X POST http://localhost:8000/api/v1/barcode/scan \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{
    "raw_data": "8901234567890",
    "scanner_id": "SCAN-001",
    "location_id": "'$loc_id'"
  }'
```
**期望：** 201

### 5.7 按 GTIN 查询

```bash
curl http://localhost:8000/api/v1/barcode/8901234567890 -H "Authorization: $token"
```
**期望：** 200，条码记录数组

---

## 6. 订单管理 — OMS

### 6.1 创建订单

```bash
curl -X POST http://localhost:8000/api/v1/orders \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "CUST-001",
    "priority": "high",
    "notes": "加急订单",
    "items": [
      {
        "gtin": "6901234567890",
        "sku": "SKU-001",
        "product_name": "Widget Pro",
        "quantity": 10,
        "unit_price": "29.99",
        "subtotal": "299.90"
      },
      {
        "gtin": "6901234567891",
        "sku": "SKU-002",
        "product_name": "Widget Lite",
        "quantity": 5,
        "unit_price": "14.99",
        "subtotal": "74.95"
      }
    ]
  }'
```
**期望：** 201

返回示例：
```json
{
  "id": "uuid-...",
  "order_no": "ORD-20260604-0001",
  "status": "draft",
  "customer_id": "CUST-001",
  "items": [...],
  "total_amount": "374.85",
  "priority": "high",
  "notes": "加急订单",
  "created_at": "..."
}
```

记下 `id` 为 `$order_id`。

### 6.2 获取订单

```bash
curl "http://localhost:8000/api/v1/orders/$order_id" -H "Authorization: $token"
```
**期望：** 200

### 6.3 不存在的订单 → 404

```bash
curl http://localhost:8000/api/v1/orders/00000000-0000-0000-0000-000000000000 \
  -H "Authorization: $token"
```
**期望：** 404

### 6.4 订单列表

```bash
curl "http://localhost:8000/api/v1/orders" -H "Authorization: $token"
```
**期望：** 200，分页结构 `{"items": [...], "total": 1, "page": 1, "page_size": 20}`

### 6.5 按客户过滤

```bash
curl "http://localhost:8000/api/v1/orders?customer_id=CUST-001&page_size=5" \
  -H "Authorization: $token"
```
**期望：** 200

### 6.6 **订单状态流转**

按顺序执行，每次检查状态：

```
draft → confirmed → processing → completed
                                   ↕
                              picking
                                  ↕
                              cancelled
```

#### 6.6.1 draft → confirmed

```bash
curl -X PUT "http://localhost:8000/api/v1/orders/$order_id/status" \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{"status": "confirmed"}'
```
**期望：** 200，`{"status": "confirmed", ...}`

#### 6.6.2 confirmed → processing

```bash
curl -X PUT "http://localhost:8000/api/v1/orders/$order_id/status" \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{"status": "processing"}'
```
**期望：** 200，`{"status": "processing"}`

#### 6.6.3 可选：继续流转

```bash
curl -X PUT "http://localhost:8000/api/v1/orders/$order_id/status" \
  -H "Authorization: $token" \
  -H "Content-Type: application/json" \
  -d '{"status": "completed"}'
```
**期望：** 200 或 422（取决于状态机实现）

### 6.7 订单历史

```bash
curl "http://localhost:8000/api/v1/orders/$order_id/history" \
  -H "Authorization: $token"
```
**期望：** 200，状态变更记录数组

### 6.8 删除订单

```bash
curl -X DELETE "http://localhost:8000/api/v1/orders/$order_id" \
  -H "Authorization: $token"
```
**期望：** 204 No Content

### 6.9 删除后查询 → 404

```bash
curl "http://localhost:8000/api/v1/orders/$order_id" -H "Authorization: $token"
```
**期望：** 404（已软删除）

---

## 7. 管理后台（浏览器访问）

> 管理后台使用 Jinja2 模板渲染，需浏览器访问。

| URL | 说明 | 需要 |
|-----|------|------|
| `http://localhost:8000/admin/` | 仪表盘 | Auth |
| `http://localhost:8000/admin/orders` | 订单管理 | Auth |
| `http://localhost:8000/admin/warehouses` | 仓库管理 | Auth |
| `http://localhost:8000/admin/devices` | 设备管理 | Auth |
| `http://localhost:8000/admin/barcodes` | 条码管理 | Auth |

在浏览器中打开任意管理页面时会跳转到登录页，先通过 `/api/v1/auth/login` 获取 token，
然后在请求头中附加 `Authorization: Bearer <token>`（通过浏览器扩展或 API 测试工具）。

---

## 8. 健康检查（无需认证）

```bash
curl http://localhost:8000/api/v1/health
```
**期望：** 200

---

## 完整测试流程速查表

| 步骤 | 接口 | 方法 | 状态码 |
|------|------|------|--------|
| 1 | `/auth/register` | POST | 201 |
| 2 | `/auth/login` | POST | 200 |
| 3 | `/auth/me` | GET | 200 |
| 4 | `/auth/users` | GET | 200 |
| 5 | `/auth/roles` | POST | 201 |
| 6 | `/auth/refresh` | POST | 200 |
| 7 | `/auth/logout` | POST | 200 |
| 8 | `/warehouses` | POST | 201 |
| 9 | `/warehouses/{id}` | GET | 200 |
| 10 | `/warehouses/{id}/locations` | POST | 201 |
| 11 | `/warehouses/inventory/adjust` | POST | 200 |
| 12 | `/warehouses/inventory` | GET | 200 |
| 13 | `/devices` | POST | 201 |
| 14 | `/devices/{id}/heartbeat` | POST | 200 |
| 15 | `/devices/{id}/sessions` | POST | 201 |
| 16 | `/devices/{id}/sync` | POST | 201 |
| 17 | `/barcode/templates` | POST | 201 |
| 18 | `/barcode/generate` | POST | 201 |
| 19 | `/barcode/validate` | POST | 200 |
| 20 | `/barcode/scan` | POST | 201 |
| 21 | `/orders` | POST | 201 |
| 22 | `/orders/{id}/status` | PUT | 200 |
| 23 | `/orders/{id}` | DELETE | 204 |
