# OMS-WMS-TMS 系统全功能人工测试计划

> 版本：v1.0 | 日期：2026-09-09
> 适用范围：全系统 194 个 API 端点 + 2 个 WebSocket + Admin 面板

---

## 目录

1. [测试前置条件](#1-测试前置条件)
2. [认证与权限 (Auth)](#2-认证与权限)
3. [订单管理 (OMS)](#3-订单管理)
4. [仓库管理 (WMS)](#4-仓库管理)
5. [库存操作 (Stock In/Out)](#5-库存操作)
6. [运输管理 (TMS)](#6-运输管理)
7. [物流运单 (Logistics)](#7-物流运单)
8. [条码管理 (Barcode)](#8-条码管理)
9. [通知系统 (Notification)](#9-通知系统)
10. [Webhook](#10-webhook)
11. [数据分析 (Analytics)](#11-数据分析)
12. [PDA 离线同步](#12-pda-离线同步)
13. [第三方对接 (Connectors)](#13-第三方对接)
14. [CSV 导入导出](#14-csv-导入导出)
15. [Admin 管理面板](#15-admin-管理面板)
16. [健康检查与基础设施](#16-健康检查与基础设施)
17. [安全与边界测试](#17-安全与边界测试)

---

## 1. 测试前置条件

### 1.1 环境准备

| 项目 | 要求 |
|------|------|
| Python | 3.13+ |
| 数据库 | SQLite (开发) / PostgreSQL (生产) |
| Redis | 可选 (无 Redis 时自动 fallback 到内存) |
| 启动命令 | `python -m uvicorn src.main:app --reload --port 8000` |

### 1.2 测试账号

| 角色 | 用户名 | 密码 | 权限 |
|------|--------|------|------|
| 超级管理员 | admin | admin123456 | 全部权限 |
| 普通用户 | testuser | test123456 | 仅查看 |
| 未授权 | — | — | 无 Token |

### 1.3 测试工具

- **API 测试**：Postman / curl / httpie
- **WebSocket 测试**：wscat / 浏览器 DevTools
- **Admin 面板**：浏览器直接访问

### 1.4 通用响应格式

成功响应：
```json
{"success": true, "data": {...}}
```

错误响应：
```json
{"success": false, "error": {"code": "NOT_FOUND", "message": "..."}}
```

`error.code` 的取值：

| code | HTTP | 含义 |
|------|------|------|
| `AUTH_FAILED` | 401 | 缺少 Token 或 Token 无效 |
| `PERMISSION_DENIED` | 403 | 无该操作的权限 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `CONFLICT` | 409 | 资源已被并发修改（乐观锁） |
| `VALIDATION_ERROR` | 400 / 422 | 请求体或参数不合法 |
| `RATE_LIMIT_EXCEEDED` | 429 | 触发限流 |
| `INTERNAL_ERROR` | 500 | 未处理的服务端异常 |
| `APP_ERROR` / `HTTP_ERROR` | 其他 | 未归类的业务错误 / 未定义状态码 |

请求体校验失败（422 / `VALIDATION_ERROR`）时，响应另有 `errors` 数组，逐项说明哪个字段、什么问题：

```json
{"success": false, "error": {"code": "VALIDATION_ERROR", "message": "Request validation failed: hub_type: Input should be 'primary', 'secondary' or 'cargo_station' (expected 'primary', 'secondary' or 'cargo_station') — sent 'sorting'"},
 "errors": [{"field": "hub_type", "message": "Input should be 'primary', 'secondary' or 'cargo_station' (expected 'primary', 'secondary' or 'cargo_station')", "value": "sorting"}]}
```

`field` 就是客户端发送的键名（别名写入时按别名报告，例如设备注册发送 `device_code`，报错的字段名是 `device_code`）；`value` 是该键收到的原值（标量时回显，便于操作者看出是哪个框填错）；枚举取值非法时，`message` 会列出该字段接受的取值。

分页响应：
```json
{"success": true, "data": {"items": [...], "total": 100, "page": 1, "page_size": 20}}
```

---

## 2. 认证与权限

### 2.1 用户注册

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 2.1.1 | 正常注册 | `POST /api/v1/auth/register` `{"username":"newuser","email":"new@test.com","password":"pass12345"}` | 201 返回用户信息（不含密码） | P0 |
| 2.1.2 | 重复用户名 | 同上再注册一次 | 422 "Username or email already exists" | P0 |
| 2.1.3 | 密码过短 | `{"password":"123"}` | 422 密码不少于 8 位 | P1 |
| 2.1.4 | 缺少必填字段 | `{"username":"x"}` | 422 缺少 email/password | P1 |
| 2.1.5 | 限流 | 连续注册 4 次 | 第 4 次返回 429 Too Many Requests | P1 |

### 2.2 用户登录

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 2.2.1 | 正常登录 | `POST /api/v1/auth/login` `{"username":"admin","password":"admin123456"}` | 200 返回 `access_token` + `refresh_token` | P0 |
| 2.2.2 | 密码错误 | `{"password":"wrong"}` | 401 Unauthorized | P0 |
| 2.2.3 | 用户不存在 | `{"username":"nobody","password":"x"}` | 401 | P1 |
| 2.2.4 | 限流 | 连续登录 6 次 | 第 6 次返回 429 | P1 |

### 2.3 Token 刷新

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 2.3.1 | 正常刷新 | `POST /api/v1/auth/refresh` `{"refresh_token":"..."}` | 200 返回新 token 对 | P0 |
| 2.3.2 | 过期 Token | 使用已过期的 refresh_token | 401 | P1 |
| 2.3.3 | 无效 Token | `{"refresh_token":"garbage"}` | 401 | P1 |

### 2.4 登出

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 2.4.1 | 正常登出 | `POST /api/v1/auth/logout` `{"refresh_token":"..."}` | 200 成功 | P0 |
| 2.4.2 | 登出后再刷新 | 用已登出的 refresh_token 再刷新 | 401 Token 已撤销 | P1 |

### 2.5 用户信息

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 2.5.1 | 获取当前用户 | `GET /api/v1/auth/me` | 200 返回用户信息 | P0 |
| 2.5.2 | 无 Token 访问 | 不带 Authorization 头 | 401 | P0 |

### 2.6 RBAC 权限管理

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 2.6.1 | 列出所有用户 | `GET /api/v1/auth/users` (admin) | 200 返回用户列表 | P0 |
| 2.6.2 | 普通用户列用户 | `GET /api/v1/auth/users` (无 `admin.rbac.manage` 权限) | 403 Forbidden | P0 |
| 2.6.3 | 创建角色 | `POST /api/v1/auth/roles` `{"name":"operator","code":"operator","description":"操作员"}`（`code` 必填，重复 422） | 201 | P0 |
| 2.6.4 | 列出角色 | `GET /api/v1/auth/roles` | 200 | P0 |
| 2.6.5 | 更新角色 | `PUT /api/v1/auth/roles/{id}` `{"name":"operator_v2"}` | 200 | P1 |
| 2.6.6 | 删除角色 | `DELETE /api/v1/auth/roles/{id}` | 204 | P1 |
| 2.6.7 | 列出权限 | `GET /api/v1/auth/permissions` | 200 返回 4 个预设权限 | P1 |
| 2.6.8 | 创建权限 | `POST /api/v1/auth/permissions` `{"code":"order.manage","name":"订单管理"}` | 201 | P1 |
| 2.6.9 | 分配角色给用户 | `POST /api/v1/auth/users/{uid}/roles` `{"role_id":"<uuid>"}` | 200；缺 `role_id` 或写成文本 → 422 点出该键与收到的值；角色不存在 → 404 `NOT_FOUND` | P0 |
| 2.6.10 | 移除用户角色 | `DELETE /api/v1/auth/users/{uid}/roles/{rid}` | 204 | P1 |
| 2.6.11 | 分配权限给角色 | `POST /api/v1/auth/roles/{rid}/permissions` `{"permission_id":"<uuid>"}` | 200；缺键/非 uuid → 422；权限不存在 → 404 `NOT_FOUND` | P0 |
| 2.6.12 | 移除角色权限 | `DELETE /api/v1/auth/roles/{rid}/permissions/{pid}` | 204 | P1 |
| 2.6.13 | 启用/禁用用户 | `POST /api/v1/auth/users/{uid}/toggle` | 200 `is_active` 取反；`uid` 不是 uuid → 422（不再是 500） | P0 |

---

## 3. 订单管理 (OMS)

### 3.1 订单 CRUD

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 3.1.1 | 创建订单 | `POST /api/v1/orders` `{"customer_id":"...","items":[{"gtin":"1234567890123","quantity":5,"unit_price":10.5}],"priority":"high"}` | 201 返回 order_no、status="pending" | P0 |
| 3.1.2 | 创建订单-缺客户 | 不传 customer_id | 422 | P1 |
| 3.1.3 | 列出订单 | `GET /api/v1/orders?page=1&page_size=10` | 200 分页列表 | P0 |
| 3.1.4 | 按状态筛选 | `GET /api/v1/orders?status=pending` | 仅返回 pending 状态订单 | P1 |
| 3.1.5 | 按客户筛选 | `GET /api/v1/orders?customer_id=...` | 仅返回该客户订单 | P1 |
| 3.1.6 | 获取单个订单 | `GET /api/v1/orders/{id}` | 200 完整订单详情 | P0 |
| 3.1.7 | 获取不存在订单 | `GET /api/v1/orders/00000000-0000-0000-0000-000000000000` | 404 | P1 |
| 3.1.8 | 删除订单 | `DELETE /api/v1/orders/{id}` | 204 软删除成功 | P0 |
| 3.1.9 | 删除后查询 | `GET /api/v1/orders/{id}` | 404（软删除不可见） | P1 |

### 3.2 订单状态流转

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 3.2.1 | pending → confirmed | `PUT /api/v1/orders/{id}/status` `{"status":"confirmed"}` | 200 status=confirmed | P0 |
| 3.2.2 | confirmed → processing | 同上 | 200 | P0 |
| 3.2.3 | processing → picking | 同上 | 200 | P0 |
| 3.2.4 | picking → completed | 同上 | 200 | P0 |
| 3.2.5 | 非法跳转 (pending → completed) | 直接跳到 completed | 422 状态机不允许 | P0 |
| 3.2.6 | 终态后再改 | completed → confirmed | 422 | P1 |
| 3.2.7 | 取消订单 | pending → cancelled | 200 | P0 |
| 3.2.8 | 操作人记录 | 查看 `GET /api/v1/orders/{id}/history` | 最新记录 operator_id 不为空 | P1 |

### 3.3 订单拆分与合并

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 3.3.1 | 拆分订单 | `POST /api/v1/orders/{id}/split` `{"items":[...]}` | 201 返回 child_order_ids | P0 |
| 3.3.2 | 合并订单 | `POST /api/v1/orders/merge` `{"order_ids":["id1","id2"]}` | 201 返回 group_id + child_order_ids | P0 |
| 3.3.3 | 查询合并组 | `GET /api/v1/orders/merge/{group_id}` | 200 包含 child_order_ids | P1 |

### 3.4 订单历史

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 3.4.1 | 查看历史 | `GET /api/v1/orders/{id}/history` | 200 返回状态变更记录列表 | P0 |
| 3.4.2 | 无历史记录 | 新建订单立即查历史 | 200 仅包含 "Order created" 记录 | P1 |

---

## 4. 仓库管理 (WMS)

### 4.1 仓库 CRUD

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 4.1.1 | 创建仓库 | `POST /api/v1/warehouses` `{"code":"WH001","name":"主仓库","warehouse_type":"CENTER","status":"ACTIVE"}` | 201 | P0 |
| 4.1.2 | 重复编码 | 同一 code 再创建 | 422 唯一约束 | P1 |
| 4.1.3 | 列出仓库 | `GET /api/v1/warehouses?page=1&page_size=10` | 200 分页 | P0 |
| 4.1.4 | 获取单个 | `GET /api/v1/warehouses/{id}` | 200 | P0 |
| 4.1.5 | 更新仓库 | `PUT /api/v1/warehouses/{id}` `{"name":"主仓库v2"}` | 200 | P0 |
| 4.1.6 | 删除仓库 | `DELETE /api/v1/warehouses/{id}` | 204 | P1 |

### 4.2 库位管理

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 4.2.1 | 创建库位 | `POST /api/v1/warehouses/{wh_id}/locations` `{"code":"A-01-01","zone":"A","location_type":"STORAGE"}` | 201 | P0 |
| 4.2.2 | 列出库位 | `GET /api/v1/warehouses/{wh_id}/locations?page=1&page_size=10` | 200 分页 | P0 |
| 4.2.3 | 更新库位 | `PUT /api/v1/warehouses/{wh_id}/locations/{loc_id}` `{"zone":"B"}` | 200 | P1 |
| 4.2.4 | 删除库位 | `DELETE /api/v1/warehouses/{wh_id}/locations/{loc_id}` | 204 | P1 |

### 4.3 供应商管理

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 4.3.1 | 创建供应商 | `POST /api/v1/warehouses/vendors` `{"code":"V001","name":"供应商A"}` | 201 | P0 |
| 4.3.2 | 列出供应商 | `GET /api/v1/warehouses/vendors` | 200 | P0 |
| 4.3.3 | 获取单个 | `GET /api/v1/warehouses/vendors/{id}` | 200 | P1 |

### 4.4 地址管理

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 4.4.1 | 创建地址 | `POST /api/v1/warehouses/addresses` `{"entity_type":"warehouse","entity_id":"...","address_line_1":"XX路","city":"上海"}` | 201 | P1 |
| 4.4.2 | 按实体查询 | `GET /api/v1/warehouses/addresses?entity_type=warehouse&entity_id=...` | 200 | P1 |

### 4.5 采购单 (PO)

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 4.5.1 | 创建采购单 | `POST /api/v1/warehouses/purchase-orders` `{"po_number":"PO-001","vendor_id":"...","lines":[{"sku_id":"...","quantity":100,"unit_price":5.5}]}` | 201 | P0 |
| 4.5.2 | 列出采购单 | `GET /api/v1/warehouses/purchase-orders` | 200 | P0 |
| 4.5.3 | 获取详情 | `GET /api/v1/warehouses/purchase-orders/{id}` | 200 含 lines | P0 |
| 4.5.4 | 审批采购单 | `POST /api/v1/warehouses/purchase-orders/{id}/approve` | 200 status → approved | P0 |
| 4.5.5 | 收货 | `POST /api/v1/warehouses/purchase-orders/{id}/receive` | 200 status → received | P0 |
| 4.5.6 | 未审批直接收货 | draft 状态直接 receive | 422 状态不允许 | P1 |

### 4.6 发票与贷项

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 4.6.1 | 创建发票 | `POST /api/v1/warehouses/invoices` `{"invoice_number":"INV-001","entity_type":"vendor","entity_id":"...","lines":[{"description":"运费","quantity":1,"unit_price":100}]}` | 201 | P1 |
| 4.6.2 | 列出发票 | `GET /api/v1/warehouses/invoices` | 200 | P1 |
| 4.6.3 | 创建贷项 | `POST /api/v1/warehouses/credit-memos` `{"credit_memo_number":"CM-001","invoice_id":"...","lines":[...]}` | 201 | P1 |
| 4.6.4 | 列出贷项 | `GET /api/v1/warehouses/credit-memos` | 200 | P1 |

### 4.7 库存查询与调整

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 4.7.1 | 查询库存 | `GET /api/v1/warehouses/inventory?warehouse_id=...` | 200 库存列表 | P0 |
| 4.7.2 | 按 SKU 筛选 | `GET /api/v1/warehouses/inventory?sku=SKU001` | 仅匹配 SKU | P1 |
| 4.7.3 | 调整库存 | `POST /api/v1/warehouses/inventory/adjust` `{"warehouse_id":"...","sku":"SKU001","adjustments":[{"location_id":"...","quantity":10}]}` | 200 | P0 |
| 4.7.4 | 库存变动记录 | `GET /api/v1/warehouses/inventory/movements` | 200 记录列表 | P1 |
| 4.7.5 | 盘点提交 | `POST /api/v1/warehouses/inventory/count/submit` `{"warehouse_id":"...","location_id":"...","count_results":[{"sku":"SKU001","actual_qty":95}]}` | 200 系统自动调整差异 | P0 |

### 4.8 拣货波次

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 4.8.1 | 创建波次 | `POST /api/v1/warehouses/picking-waves` `{"warehouse_id":"...","wave_type":"ORDER_BASED","priority":"HIGH"}` | 201 | P0 |
| 4.8.2 | 列出波次 | `GET /api/v1/warehouses/picking-waves` | 200 | P0 |
| 4.8.3 | 开始执行 | `POST /api/v1/warehouses/picking-waves/{id}/start` | 200 status → in_progress | P0 |
| 4.8.4 | 完成波次 | `POST /api/v1/warehouses/picking-waves/{id}/complete` | 200 status → completed | P0 |
| 4.8.5 | 未开始直接完成 | pending 状态直接 complete | 422 | P1 |

### 4.9 包裹与发货

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 4.9.1 | 创建打包记录 | `POST /api/v1/warehouses/packing` `{"picking_wave_id":"<uuid>","box_count":2}` | 201，`box_count=2` | P0 |
| 4.9.1b | 打包记录（前端形状） | `{"wave_id":"<uuid>"}` — 打包记录表单只填波次ID | 201，`box_count=1` | P0 |
| 4.9.1c | 打包缺波次 / 波次号非法 | `{}`；`{"wave_id":"WAVE-0021"}` | 均 422，报 `picking_wave_id`（后者回显 `WAVE-0021`） | P0 |
| 4.9.1d | 箱数非法 | `{"wave_id":"<uuid>","box_count":"三箱"}`；`box_count:0` | 422，报 `box_count` | P1 |
| 4.9.1e | 波次未完成 / 不存在 | 对 pending 波次打包；波次 uuid 不存在 | 422「Only completed waves…」；404 | P0 |
| 4.9.2 | 创建发货单 | `POST /api/v1/warehouses/shipments` `{"order_id":"<真实订单>","warehouse_id":"<uuid>"}` | 201 `{"count":1,"shipments":[…]}`，status=`picked` | P0 |
| 4.9.2b | 多订单发货单 | `{"warehouse_id":"<uuid>","order_ids":[o1,o2]}`（发货管理文本框逐行贴） | 201，`count=2`，两条 `shipment_no` 互不相同 | P0 |
| 4.9.2c | 发货单号 | 新建后查列表 | 每条 `shipment_no` 形如 `SHIP-YYYYMMDD-XXXXXXXX`，发货管理首列有值 | P1 |
| 4.9.2d | 没有任何订单 / 缺仓库 | `{"warehouse_id":"<uuid>"}`；`{"order_ids":["ORD-2024-0001"]}` | 422，分别报 `order_ids`、`warehouse_id` | P0 |
| 4.9.2e | 订单不存在 | `order_ids:["<不存在的uuid>"]` | 404 `NOT_FOUND`，message 含该 id | P0 |
| 4.9.3 | 标记已发货 | `POST /api/v1/warehouses/shipments/{id}/ship` `{"tracking_number":"SF1234567890","carrier":"sf_express"}` | 200 status=shipped | P0 |
| 4.9.3b | 发货按钮不发 body | 同上，无 body | 200 status=shipped（运单号沿用单上已有值） | P0 |
| 4.9.3c | 重复发货 / 已取消 | 对 shipped 单再发；对 cancelled 单发货 | 422「already shipped」；422「cancelled」 | P0 |
| 4.9.4 | 列出发货单 | `GET /api/v1/warehouses/shipments` | 200，每行含 `shipment_no`/`carrier`/`tracking_number` | P0 |

### 4.10 调拨单

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 4.10.1 | 创建调拨单 | `POST /api/v1/warehouses/transfers` `{"source_warehouse_id":"...","target_warehouse_id":"...","type":"SKU","lines":[{"sku_id":"...","quantity":50}]}` | 201 status=DRAFT | P0 |
| 4.10.2 | 列出调拨单 | `GET /api/v1/warehouses/transfers` | 200 | P0 |

---

## 5. 库存操作 (Stock In/Out)

### 5.1 入库 (Stock In)

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 5.1.1 | 创建入库单 | `POST /api/v1/stock-in` `{"data":{"warehouse_id":"...","type":"PURCHASE","lines":[{"sku":"SKU001","qty_received":100}]}}` | 201 status=DRAFT | P0 |
| 5.1.2 | 列出入库单 | `GET /api/v1/stock-in` | 200 | P0 |
| 5.1.3 | 获取详情 | `GET /api/v1/stock-in/{id}` | 200 含 lines | P0 |
| 5.1.4 | 确认入库 | `PUT /api/v1/stock-in/{id}` `{"status":"CONFIRMED"}` | 200 DRAFT→CONFIRMED | P0 |
| 5.1.5 | 收货完成 | `PUT /api/v1/stock-in/{id}` `{"status":"RECEIVED"}` | 200 CONFIRMED→RECEIVED | P0 |
| 5.1.6 | 非法状态跳转 | DRAFT→RECEIVED 直接跳 | 400 | P1 |

### 5.2 出库 (Stock Out)

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 5.2.1 | 创建出库单 | `POST /api/v1/stock-out` `{"data":{"warehouse_id":"...","type":"SALE","lines":[{"sku":"SKU001","qty_shipped":10}]}}` | 201 status=DRAFT | P0 |
| 5.2.2 | 列出出库单 | `GET /api/v1/stock-out` | 200 | P0 |
| 5.2.3 | 确认出库 | `PUT /api/v1/stock-out/{id}` `{"status":"CONFIRMED"}` | 200 DRAFT→CONFIRMED | P0 |
| 5.2.4 | 标记已发货 | `PUT /api/v1/stock-out/{id}` `{"status":"SHIPPED"}` | 200 CONFIRMED→SHIPPED | P0 |

### 5.3 库存日志与调整

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 5.3.1 | 查看库存日志 | `GET /api/v1/inventory-log` | 200 操作记录列表 | P0 |
| 5.3.2 | 获取单条日志 | `GET /api/v1/inventory-log/{id}` | 200 | P1 |
| 5.3.3 | 批量调整库存 | `POST /api/v1/adjust-stock` `{"warehouse_id":"...","sku":"SKU001","adjustments":[{"location_id":"...","quantity":10,"reason":"COUNT_ERROR"}]}` | 200 正数=入库，负数=出库 | P0 |
| 5.3.4 | 调整量为零 | `{"quantity":0}` | 422 不允许零调整 | P1 |

---

## 6. 运输管理 (TMS)

### 6.1 运输单

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 6.1.1 | 创建运输单 | `POST /api/v1/transport-orders` `{"carrier_code":"sf_express","pickup_warehouse_id":"...","pickup_address":{...},"delivery_name":"张三","delivery_address":{...},"total_weight_kg":5.5,"total_volume_m3":0.01}` | 201 status=draft | P0 |
| 6.1.2 | 列出运输单 | `GET /api/v1/transport-orders?page=1&limit=10` | 200 | P0 |
| 6.1.3 | 按状态筛选 | `GET /api/v1/transport-orders?status=in_transit` | 仅返回 in_transit | P1 |
| 6.1.4 | 按承运商筛选 | `GET /api/v1/transport-orders?carrier_code=sf_express` | 仅顺丰 | P1 |
| 6.1.5 | 获取详情 | `GET /api/v1/transport-orders/{id}` | 200 | P0 |
| 6.1.6 | 状态流转 draft→dispatched | `PUT /api/v1/transport-orders/{id}/status` `{"status":"dispatched"}` | 200 | P0 |
| 6.1.7 | dispatched→in_transit | 同上 | 200 | P0 |
| 6.1.8 | in_transit→delivered | 同上 | 200 | P0 |
| 6.1.9 | 非法跳转 draft→delivered | 直接跳到 delivered | 422 | P0 |
| 6.1.10 | 不存在的运输单 | `GET /api/v1/transport-orders/000...` | 404 | P1 |

### 6.2 物流追踪

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 6.2.1 | 创建追踪事件 | `POST /api/v1/tracking-events` `{"transport_order_id":"...","event_type":"in_transit","location_name":"上海分拣中心"}` | 201 | P0 |
| 6.2.2 | 按运输单追踪 | `POST /api/v1/transport-orders/{id}/tracking-events` `{"event_type":"arrived_hub","location_name":"北京转运站"}` | 201 | P0 |
| 6.2.3 | 查询追踪记录 | `GET /api/v1/transport-orders/{id}/tracking` | 200 按时间排序 | P0 |
| 6.2.4 | 分页查询 | `GET /api/v1/transport-orders/{id}/tracking-events?skip=0&limit=5` | 200 | P1 |

### 6.3 签收证明 (POD)

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 6.3.1 | 创建 POD | `POST /api/v1/transport-orders/{id}/pod` `{"signed_by":"张三","signature_type":"digital"}` | 201 | P0 |
| 6.3.2 | 查询 POD | `GET /api/v1/transport-orders/{id}/pod` | 200 | P0 |
| 6.3.3 | 更新 POD | `PUT /api/v1/transport-orders/{id}/pod` `{"notes":"已当面签收"}` | 200 | P1 |

### 6.4 退货单

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 6.4.1 | 创建退货单 | `POST /api/v1/return-orders` `{"reason":"damaged","reason_detail":"外箱破损","pickup_address":{...}}` | 201 status=requested | P0 |
| 6.4.2 | 列出退货单 | `GET /api/v1/return-orders` | 200 | P0 |
| 6.4.3 | 获取详情 | `GET /api/v1/return-orders/{id}` | 200 | P0 |
| 6.4.4 | 更新状态 requested→cancelled | `PATCH /api/v1/return-orders/{id}/status` `{"status":"cancelled"}` | 200 | P0 |
| 6.4.5 | 状态流转 requested→in_transit_return→returned_to_warehouse | 逐步推进 | 每步 200 | P1 |
| 6.4.6 | 退货→退款→关闭 | returned_to_warehouse→refunded→closed | 每步 200 | P1 |

### 6.5 运输异常

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 6.5.1 | 报告异常 | `POST /api/v1/exceptions` `{"transport_order_id":"...","type":"delayed","description":"暴雨延误"}` | 201 status=open | P0 |
| 6.5.2 | 按运输单报告 | `POST /api/v1/transport-orders/{id}/exceptions` `{"type":"damaged_in_transit"}` | 201 | P0 |
| 6.5.3 | 列出异常 | `GET /api/v1/exceptions` | 200 默认 status=open | P0 |
| 6.5.4 | 解决异常 | `PATCH /api/v1/exceptions/{id}` `{"status":"resolved","resolution_notes":"已联系客户"}` | 200 | P0 |
| 6.5.5 | 按状态筛选 | `GET /api/v1/exceptions?status=resolved` | 仅 resolved | P1 |

### 6.6 运费估算

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 6.6.1 | 简单估算 | `POST /api/v1/freight-estimate?carrier_code=sf_express&service_type=standard&distance_km=500&weight_kg=10` | 200 返回估算费用 | P1 |
| 6.6.2 | 创建运费阶梯 | `POST /api/v1/freight-tiers` `{"carrier_code":"sf_express","rule_type":"weight_tiered","min_value":0,"max_value":5,"price_per_unit":12}` | 201 | P1 |
| 6.6.3 | 阶梯计算 | `POST /api/v1/freight/calculate` `{"carrier_code":"sf_express","weight_kg":3}` | 200 返回按阶梯计算的费用 | P1 |

### 6.7 路由规划

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 6.7.1 | 创建转运中心 | `POST /api/v1/transfer-hubs` `{"code":"HUB-SH","name":"上海中心","hub_type":"primary","city":"上海","capacity_weight_kg":50000,"contact_name":"张强"}`（`hub_type` 可写作 `type`；取值 `primary`/`secondary`/`cargo_station`，越界 422 并列出该词表） | 201 | P1 |
| 6.7.2 | 列出转运中心 | `GET /api/v1/transfer-hubs` | 200（每项字段与详情接口一致：`type`，不是 `hub_type`） | P1 |
| 6.7.2b | 编辑转运中心 | `PATCH /api/v1/transfer-hubs/{id}` `{"code":"HUB-SH2","name":"上海中心","type":"secondary","city":"上海","status":"maintenance"}` | 200，编码/名称/类型/城市/状态全部落库；改名撞上他站编码 → 422 并点出该编码 | P1 |
| 6.7.3 | 创建承运路线 | `POST /api/v1/carrier-routes` `{"carrier_code":"sf_express","origin_city":"上海","dest_city":"北京","distance_km":1200,"transit_hours":24,"base_price_per_kg":8}` | 201 | P1 |
| 6.7.4 | 创建 Hub 连接 | `POST /api/v1/hub-connections` `{"from_hub_code":"HUB-SH","to_hub_code":"HUB-BJ","distance_km":1200,"transit_hours":24}` | 201 | P1 |
| 6.7.5 | 生成路由方案 | `POST /api/v1/transport-orders/{id}/route-plans` `{"type":"auto_gen"}` | 201 返回 plan_id | P1 |
| 6.7.6 | 查询路由方案 | `GET /api/v1/route-plans/{plan_id}` | 200 含 segments | P1 |

### 6.8 运输段

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 6.8.1 | 创建运输段 | `POST /api/v1/segments` `{"transport_order_id":"...","segment_no":1,"origin_hub_code":"HUB-SH","dest_hub_code":"HUB-BJ"}` | 201 | P1 |
| 6.8.2 | 查询段 | `GET /api/v1/segments?transport_order_id=...` | 200 | P1 |
| 6.8.3 | 更新段状态 | `PATCH /api/v1/segments/{id}/status` `{"status":"in_transit"}` | 200 | P1 |

### 6.9 终端设备

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 6.9.1 | 注册设备 | `POST /api/v1/devices` `{"code":"PDA-001","name":"手持终端1","device_type":"pda","platform":"android"}` | 201 | P1 |
| 6.9.2 | 列出设备 | `GET /api/v1/devices` | 200 | P1 |
| 6.9.3 | 心跳 | `POST /api/v1/devices/{id}/heartbeat` | 201 | P2 |
| 6.9.4 | 创建会话 | `POST /api/v1/devices/{id}/sessions` | 201 返回 token | P1 |
| 6.9.5 | 列出会话 | `GET /api/v1/devices/{id}/sessions` | 200 | P2 |
| 6.9.6 | 结束会话 | `DELETE /api/v1/devices/{id}/sessions/{sid}` | 204 | P2 |
| 6.9.7 | 同步日志 | `POST /api/v1/devices/{id}/sync` + `GET /api/v1/devices/{id}/sync` | 201 + 200 | P2 |

### 6.10 需求预测 (ML)

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 6.10.1 | 记录观测值 | `POST /api/v1/forecast/observations` `{"origin_city":"上海","destination_city":"北京","count":150}` → `{"status":"ok","key":"上海-北京"}` | 200；缺 `count` 或写成文本、城市为空 → 422 点出该字段 | P2 |
| 6.10.2 | 获取预测 | `GET /api/v1/forecast?origin_city=上海&destination_city=北京&days=7` | 200 返回预测点 | P2 |
| 6.10.3 | 训练模型 | `POST /api/v1/forecast/training` `{"months":6}` | 200 `{"status":"ok","trained":n,"skipped":n}`；`months` 非数字或越出 1–36 → 422（地址无城市的订单计入 `skipped`，不进入模型） | P2 |

---

## 7. 物流运单 (Logistics)

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 7.1 | 创建运单 | `POST /api/v1/logistics/waybill/create` `{"order_id":"...","carrier_code":"SF","recipient_name":"张三","recipient_phone":"13800138000","recipient_address":"XX路XX号"}` | 201 返回 tracking_number；`tracking_source` 说明号码出处 | P0 |
| 7.1b | 号码出处标注 | 未配置 `KDNIAO_*` 时创建运单 | 201，`tracking_source == "local_placeholder"`，`tracking_source_note` 说明"快递侧没有这张面单"（标签打印出来与真号一模一样，靠这个字段区分） | P0 |
| 7.2 | 列出运单 | `GET /api/v1/logistics/waybill/list` | 200 | P0 |
| 7.3 | 按运单号查询 | `GET /api/v1/logistics/waybill/{tracking}` | 200 | P0 |
| 7.4 | 作废运单 | `POST /api/v1/logistics/waybill/{tracking}/void` | 200 status → voided | P1 |
| 7.5 | 查询物流轨迹（已配置） | `GET /api/v1/logistics/waybill/{tracking}/track`，已配置 `KDNIAO_EBUSINESS_ID`/`KDNIAO_API_KEY` | 200，`source == "kdniao"`，轨迹来自快递鸟 | P1 |
| 7.5b | 无凭据 → 明确拒绝 | 清空 `KDNIAO_*`、`LOGISTICS_MOCK_ENABLED=false` 后查轨迹 | **501** `NOT_IMPLEMENTED`，消息点名 `KDNIAO_EBUSINESS_ID`；**响应里没有任何"已签收/派送中"状态** | P0 |
| 7.5c | 演示数据必须标注 | `LOGISTICS_MOCK_ENABLED=true` 后查轨迹 | 200，`source == "mock"`，`status_detail` 以【演示数据】开头，`source_note` 说明状态由运单号哈希得出 | P0 |
| 7.5d | 承运商接口失败 → 不编造轨迹 | 配置 `CARRIER_API_ENDPOINTS` 指向不可达地址后询价/查单（`carriers.query_tracking` / `estimate_shipping`） | 抛错并渲染为 502「查单失败/询价失败」，**不回落演示数据**（演示开关开着也一样） | P0 |
| 7.6 | 标记已打印 | `POST /api/v1/logistics/waybill/{tracking}/print` | 200 print_count +1 | P1 |

---

## 8. 条码管理 (Barcode)

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 8.1 | 生成条码 | `POST /api/v1/barcode/generate` `{"gtin":"1234567890123","entity_type":"order","format":"ean13"}` | 201 | P0 |
| 8.2 | 验证条码 | `POST /api/v1/barcode/validate` `{"gtin":"1234567890123"}` | 200 valid=true | P0 |
| 8.3 | 记录扫描 | `POST /api/v1/barcode/scan` `{"gtin":"1234567890123","entity_type":"inventory"}` | 201 | P0 |
| 8.4 | Excel 批量上传 | `POST /api/v1/barcode/excel/upload` (multipart, .xlsx 文件) | 200 返回 ZIP 文件名 | P1 |
| 8.5 | 下载条码 ZIP | `GET /api/v1/barcode/download/{filename}` | 200 返回 ZIP 文件 | P1 |
| 8.6 | 创建标签模板 | `POST /api/v1/barcode/templates` `{"name":"标准标签","code":"TPL001","format":"zpl","width_mm":100,"height_mm":50}` | 201 | P1 |
| 8.7 | 列出模板 | `GET /api/v1/barcode/templates` | 200 | P1 |
| 8.8 | 按 GTIN 查询 | `GET /api/v1/barcode/{gtin}` | 200 条码记录列表 | P1 |

---

## 9. 通知系统 (Notification)

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 9.1 | 列出通知 | `GET /api/v1/notifications/` | 200 当前用户的通知 | P0 |
| 9.2 | 仅看未读 | `GET /api/v1/notifications/?unread_only=true` | 仅未读通知 | P1 |
| 9.3 | 标记已读 | `POST /api/v1/notifications/{id}/read` | 200 is_read=true | P0 |
| 9.4 | 标记不存在通知 | `POST /api/v1/notifications/99999/read` | 404 | P1 |
| 9.5 | 全部已读 | `POST /api/v1/notifications/read-all` | 200 | P0 |
| 9.6 | 获取偏好 | `GET /api/v1/notifications/preferences` | 200 | P1 |
| 9.7 | 更新偏好 | `PUT /api/v1/notifications/preferences` `{"preferences":[{"notification_type":"order_status_change","channel":"email","enabled":true}]}` | 200 | P1 |
| 9.8 | WebSocket 推送 | 连接 `ws://localhost:8000/api/v1/notifications/ws?token=...` | 连接成功，收到实时通知 | P0 |
| 9.9 | 无效 Token WS | `ws://...?token=invalid` | 连接关闭 code=4001 | P1 |

---

## 10. Webhook

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 10.1 | 创建目标 | `POST /api/v1/webhooks/` `{"name":"测试","url":"https://example.com/hook","events":["order.created","order.status_changed"],"secret":"mysecret"}` | 201 | P0 |
| 10.2 | 无效事件类型 | `{"events":["invalid.event"]}` | 422 | P1 |
| 10.3 | 列出目标 | `GET /api/v1/webhooks/` | 200 | P0 |
| 10.4 | 更新目标 | `PUT /api/v1/webhooks/{id}` `{"name":"新名称"}` | 200 | P1 |
| 10.5 | 删除目标 | `DELETE /api/v1/webhooks/{id}` | 204 | P1 |

---

## 11. 数据分析 (Analytics)

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 11.1 | 仪表盘 | `GET /api/v1/analytics/dashboard` | 200 含 stats/trends/status_dist/low_stock/recent | P0 |
| 11.2 | 订单趋势 | `GET /api/v1/analytics/order-trends?days=7` | 200 近 7 天趋势 | P1 |
| 11.3 | 状态分布 | `GET /api/v1/analytics/status-distribution` | 200 各状态占比 | P1 |
| 11.4 | 低库存预警 | `GET /api/v1/analytics/low-stock` | 200 低于最小库存的 SKU 列表 | P0 |

---

## 12. PDA 离线同步

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 12.1 | 提交离线变更 | `POST /pda/mutations` `{"device_id":"PDA-001","entity_type":"order","entity_id":"...","operation":"update","payload":"{...}"}` | 201 | P0 |
| 12.2 | 列出待同步 | `GET /pda/mutations` | 200 | P0 |
| 12.3 | 批量同步 | `POST /pda/sync` | 200 返回 processed/succeeded/failed 计数 | P0 |
| 12.4 | WebSocket 实时同步 | 连接 `ws://localhost:8000/pda/ws?client_id=PDA-001&token=...` | 连接成功，实时推送 | P1 |
| 12.5 | 无效 Token WS | `ws://...?client_id=x&token=bad` | 连接关闭 code=4001 | P2 |

---

## 13. 第三方对接 (Connectors)

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 13.1 | Shopify 订单 Webhook | `POST /api/v1/connectors/shopify/webhook` + `X-Shopify-Hmac-Sha256` header + `X-Shopify-Topic: orders/create` body | 200 创建内部订单 | P1 |
| 13.2 | 无效 HMAC | 不带/错误 HMAC 头 | 401 | P1 |
| 13.3 | Amazon 订单导入 | `POST /api/v1/connectors/amazon/orders`，body 为 SP-API 原始 `Order` 对象（`AmazonOrderId` + `OrderItems[{SellerSKU,QuantityOrdered,ItemPrice}]`） | 201 `{"status":"imported","order_no":"ORD-…","line_count":1,"total_amount":"150.00"}` | P1 |
| 13.3b | 导入无订单号 | 同上但 `AmazonOrderId` 为空 | 422，报出 `AmazonOrderId`（不再产生"无主"订单） | P1 |
| 13.3c | 导入无商品行 | `"OrderItems": []` | 422「没有商品行的订单不能被拣货、发货、开票」 | P1 |
| 13.3d | 行内无商品标识 | 行内既无 `SellerSKU`/`ASIN` 也无条码 | 422，点名是第几行 | P1 |
| 13.3e | 数量/价格写法异常 | `QuantityOrdered: "2 items"` 或 `-2`；`ItemPrice.Amount: "seventy five"` | 422 报出该行与原始值（不再 500） | P1 |
| 13.3f | null 字段 | `ShippingAddress: null`、`OrderTotal: null`（未发货单常见） | 201，金额按商品行合计 | P1 |
| 13.3g | FBA 行 | 行内只有 `ASIN` 无 `SellerSKU` | 201，`sku` 取 ASIN，`gtin` 列**不写入** ASIN | P2 |
| 13.4 | Amazon 发货交接 | `POST /api/v1/connectors/amazon/tracking` `{amazon_order_id, carrier_code, tracking_number}` | 200 `{status:"received", sync_status:"not_configured"}` | P2 |
| 13.4b | 交接缺字段/空 body | 少任一必填项（含控制台的不带 body 提交） | 422 点名缺哪一项（不再对空壳回 `received`） | P1 |
| 13.4c | 交接键名写法 | `amazonOrderId`/`trackingNumber` 驼峰、`{"data":{…}}` 信封 | 200，同上 | P2 |
| 13.4d | 契约外键 | body 带 `shipment_id` 等未定义键 | 422 | P2 |
| 13.5 | 连接器列表 | `GET /api/v1/connectors/status` | 200，只有 `amazon` 与 `shopify`，每项能力标 `implemented`/`not_implemented`/`not_available` | P1 |
| 13.5b | 列表路由不被 id 路由吃掉 | 同上 | 200 且返回数组（`/status` 声明在 `/{connector_id}` 之前） | P2 |
| 13.5c | 不回传密钥值 | 同上，检查响应正文 | 无 `SECRET_KEY` 的值；凭据项只有 `env` + `set`，`value` 为 null（区域 `AMAZON_SP_API_REGION` 作为选择项可显示） | P0 |
| 13.5d | 凭据状态跟随配置 | 未配置 Amazon 凭据时查看 | `configured: false`、`status: "not_configured"` | P2 |
| 13.6 | 单个连接器 | `GET /api/v1/connectors/amazon`（`Shopify` 大写亦可） | 200 | P2 |
| 13.6b | 不存在的连接器 | `GET /api/v1/connectors/sap` / `oracle` / `erp` | 404，message 说明"the connectors here are amazon and shopify" | P1 |
| 13.7 | Amazon 同步 | `POST /api/v1/connectors/amazon/sync` | 501 `NOT_IMPLEMENTED`，说明未实现并指向 `/connectors/amazon/orders` | P1 |
| 13.7b | Shopify 同步 | `POST /api/v1/connectors/shopify/sync` | 422 `VALIDATION_ERROR`，说明推送式对接无可拉取数据 | P1 |
| 13.7c | 未知连接器同步 | `POST /api/v1/connectors/sap/sync` | 404 `NOT_FOUND` | P2 |
| 13.8 | 配置页只读 | 打开 `/connectors/manage` → 配置说明 | 页面显示配置项名与"已配置/未配置"；无密钥输入框，不发 POST/PUT（旧版收集 AWS Access Key、Shopify Admin API Token 并提交到不存在的端点，已移除） | P1 |
| 13.8b | 「同步」按钮已移除 | `/connectors/manage` | 无「同步」按钮（旧版点了只会 404 后弹一句无原因的"同步失败"） | P2 |
| 13.8c | 列表加载失败可见 | 断开后端后打开 `/connectors/manage` | 页面出现告警条与错误提示（旧版只写 `console.warn`，操作员看到"暂无连接器数据"） | P2 |

---

## 14. CSV 导入导出

### 14.1 API 导入

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 14.1.1 | 导入订单 CSV | `POST /api/v1/import/orders` (multipart, .csv) | 200 `{"success": N, "errors": []}` | P0 |
| 14.1.2 | 导入库存 CSV | `POST /api/v1/import/inventory` (multipart, .csv) | 200 | P0 |
| 14.1.3 | 超大文件 | >10MB 文件 | 413 | P1 |

### 14.2 Admin 导出

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 14.2.1 | 导出订单 CSV | `GET /admin/export/orders` | 200 CSV 下载 | P0 |
| 14.2.2 | 导出库存 CSV | `GET /admin/export/inventory` | 200 CSV 下载 | P0 |
| 14.2.3 | 导出运输单 CSV | `GET /admin/export/transport-orders` | 200 CSV 下载 | P1 |
| 14.2.4 | 导出退货 CSV | `GET /admin/export/returns` | 200 CSV 下载 | P1 |
| 14.2.5 | 导出异常 CSV | `GET /admin/export/exceptions` | 200 CSV 下载 | P1 |
| 14.2.6 | 导出路由 CSV | `GET /admin/export/route-plans` | 200 CSV 下载 | P2 |

---

## 15. Admin 管理面板

> 通过浏览器访问 `http://localhost:8000/admin/`

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 15.1 | 仪表盘 | 访问 `/admin/` | 显示统计图表 | P0 |
| 15.2 | 订单列表 | `/admin/orders` | 显示订单列表 | P0 |
| 15.3 | 订单详情 | `/admin/orders/{id}` | 显示订单详情+历史 | P0 |
| 15.4 | 创建订单 | 表单提交 | 创建成功并跳转列表 | P1 |
| 15.5 | 修改订单状态 | 表单提交 | 状态更新并跳转详情 | P1 |
| 15.6 | 用户列表 | `/admin/users` | 显示用户列表（无密码） | P0 |
| 15.7 | 创建用户 | 表单提交 | 创建成功 | P1 |
| 15.8 | 启用/禁用用户 | Toggle 按钮 | 状态切换 | P0 |
| 15.9 | 仓库管理 | `/admin/warehouses` | 列表+编辑 | P0 |
| 15.10 | 库存管理 | `/admin/inventory` | 库存列表 | P0 |
| 15.11 | 运输单管理 | `/admin/transport-orders` | 运输单列表 | P0 |
| 15.12 | 退货管理 | `/admin/returns` | 退货单列表 | P1 |
| 15.13 | 异常管理 | `/admin/exceptions` | 异常列表 | P1 |
| 15.14 | 设备管理 | `/admin/devices` | 终端设备列表 | P2 |
| 15.15 | Webhook 管理 | `/admin/webhooks` | Webhook 列表 | P1 |
| 15.16 | 预测管理 | `/admin/forecast` | 预测页面 | P2 |
| 15.17 | CSV 导入 | `/admin/import` | 上传表单 | P1 |
| 15.18 | CSRF Token | 检查页面源码 | 每个表单包含 csrf_token 隐藏字段 | P0 |

---

## 16. 健康检查与基础设施

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 16.1 | 根级健康检查 | `GET /health` | 200 或 503 | P0 |
| 16.2 | API 健康检查 | `GET /api/v1/health` | 200 `{"status":"healthy","checks":{"database":"ok"}}` | P0 |
| 16.3 | 就绪检查 | `GET /api/v1/ready` | 200 DB+Redis 均可用时 | P0 |
| 16.4 | DB 不可用时 | 停止数据库后访问 `/health` | 503 `{"status":"degraded"}` | P1 |
| 16.5 | Prometheus 指标 | `GET /metrics` | 200 Prometheus 格式 | P2 |

---

## 17. 安全与边界测试

### 17.1 认证安全

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 17.1.1 | 无 Token 访问受保护端点 | 不带 Authorization 头 | 401 | P0 |
| 17.1.2 | 过期 Token | 使用过期 access_token | 401 | P0 |
| 17.1.3 | 篡改 Token | 修改 token payload | 401 | P0 |
| 17.1.4 | Bearer 前缀缺失 | `Authorization: token_value` (无 Bearer) | 401 | P1 |

### 17.2 RBAC 安全

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 17.2.1 | 无权限访问管理端点 | 普通用户调 `/api/v1/auth/users` | 403 | P0 |
| 17.2.2 | 无权限导出 | 普通用户调 `/admin/export/orders` | 403 | P0 |
| 17.2.3 | 无权限管理 Webhook | 普通用户调 `/admin/webhooks` | 403 | P0 |
| 17.2.4 | 无权限用户管理 | 普通用户调 `/admin/users/{id}/delete` | 403 | P0 |

### 17.3 输入验证

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 17.3.1 | SQL 注入 | username 字段输入 `' OR 1=1 --` | 422 或注册成功但无注入 | P0 |
| 17.3.2 | XSS 攻击 | name 字段输入 `<script>alert(1)</script>` | 原样存储或转义，不执行 | P0 |
| 17.3.3 | 路径遍历 | barcode download filename 字段输入 `../../etc/passwd` | 400 或忽略路径穿越 | P0 |
| 17.3.4 | 超大 payload | 提交 10MB+ JSON body | 413 或截断 | P1 |
| 17.3.5 | UUID 格式错误 | 传非 UUID 字符串作为 id | 422 格式错误 | P1 |

### 17.4 并发安全

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 17.4.1 | 并发创建同名订单号 | 10 个并发请求创建订单 | 全部成功，order_no 均唯一 | P0 |
| 17.4.2 | 并发库存扣减 | 10 个并发请求扣减同一 SKU | 最终库存正确，不超卖 | P0 |
| 17.4.3 | 乐观锁冲突 | 两个请求同时修改同一订单 | 一个成功一个失败（version 冲突） | P1 |

### 17.5 速率限制

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 17.5.1 | 注册限流 | 1 小时内注册 4 次 | 第 4 次 429 | P1 |
| 17.5.2 | 登录限流 | 1 分钟内登录 6 次 | 第 6 次 429 | P0 |

### 17.6 敏感信息保护

| # | 测试用例 | 操作 | 预期结果 | 优先级 |
|---|---------|------|---------|--------|
| 17.6.1 | 响应不含密码 | `GET /api/v1/auth/me` | 无 hashed_password 字段 | P0 |
| 17.6.2 | 错误响应不含堆栈 | 触发 500 错误 | 无 traceback 信息泄露 | P0 |
| 17.6.3 | 日志脱敏 | 查看日志中登录请求 | password 字段显示为 `***REDACTED***` | P1 |
| 17.6.4 | Server 头隐藏 | 检查响应头 | 无 `Server: uvicorn` 头 | P1 |
| 17.6.5 | CORS 头 | 跨域请求 | 无 `Access-Control-Allow-Origin: *` (生产环境) | P1 |

---

## 测试用例统计

| 模块 | P0 | P1 | P2 | 合计 |
|------|----|----|----|----|
| 认证与权限 | 8 | 9 | 0 | 17 |
| 订单管理 (OMS) | 11 | 7 | 0 | 18 |
| 仓库管理 (WMS) | 16 | 12 | 0 | 28 |
| 库存操作 (Stock) | 6 | 4 | 0 | 10 |
| 运输管理 (TMS) | 15 | 18 | 3 | 36 |
| 物流运单 | 3 | 3 | 0 | 6 |
| 条码管理 | 3 | 5 | 0 | 8 |
| 通知系统 | 3 | 5 | 0 | 8 |
| Webhook | 2 | 3 | 0 | 5 |
| 数据分析 | 2 | 2 | 0 | 4 |
| PDA 同步 | 3 | 1 | 1 | 5 |
| 第三方对接 | 0 | 3 | 1 | 4 |
| CSV 导入导出 | 2 | 4 | 0 | 6 |
| Admin 面板 | 9 | 7 | 2 | 18 |
| 健康检查 | 3 | 1 | 1 | 5 |
| 安全边界 | 10 | 7 | 0 | 17 |
| **合计** | **96** | **91** | **8** | **195** |

### 建议执行顺序

1. **第一轮（冒烟测试）**：所有 P0 用例 — 约 96 项，预计 4-6 小时
2. **第二轮（功能回归）**：所有 P1 用例 — 约 91 项，预计 3-4 小时
3. **第三轮（补充验证）**：所有 P2 用例 — 约 8 项，预计 1 小时

### 测试通过标准

- P0 用例通过率 = **100%**（零容忍）
- P1 用例通过率 ≥ **95%**
- P2 用例通过率 ≥ **80%**
- 无 P0/P1 级别的数据丢失或安全漏洞
