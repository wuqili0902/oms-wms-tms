# 管理员操作手册

## 目录

1. [系统登录](#1-系统登录)
2. [用户与角色管理](#2-用户与角色管理)
3. [仓库管理](#3-仓库管理)
4. [库存管理](#4-库存管理)
5. [订单管理](#5-订单管理)
6. [采购与供应商管理](#6-采购与供应商管理)
7. [运输管理](#7-运输管理)
8. [条码管理](#8-条码管理)
9. [数据导入导出](#9-数据导入导出)
10. [通知与告警](#10-通知与告警)
11. [系统监控](#11-系统监控)

---

## 1. 系统登录

### 登录流程

```
POST /api/v1/auth/login
Body: { "username": "admin", "password": "***" }
Response: { "access_token": "eyJ...", "refresh_token": "eyJ...", "token_type": "bearer" }
```

### 权限说明

| 角色 | 权限范围 |
|------|---------|
| admin | 全部模块读写权限 |
| warehouse_manager | WMS 全部 + OMS 只读 |
| operator | 当前仓库的库存/拣货操作 |
| viewer | 全部模块只读 |

### Token 刷新

access_token 过期后使用 refresh_token 获取新 token：

```
POST /api/v1/auth/refresh
Body: { "refresh_token": "eyJ..." }
```

---

## 2. 用户与角色管理

### 创建用户

```
POST /api/v1/auth/register
Body: { "username": "zhangsan", "password": "***", "email": "zhang@co.com" }
# 注册体没有 role_ids：角色在注册后用下面的分配接口挂上去
```

### 分配角色

```
POST /api/v1/auth/users/{user_id}/roles
Body: { "role_id": "b6c1…-uuid" }
# role_id 必填且必须是 uuid：缺键 → 422 点出 role_id；
# 不是 uuid（旧书签里的半截 id）→ 422；角色不存在 → 404
```

### 创建角色

```
POST /api/v1/auth/roles
Body: { "name": "wms_operator", "code": "wms_operator", "description": "仓储操作员" }
# code 必填且唯一
```

### 为角色分配权限

```
POST /api/v1/auth/roles/{role_id}/permissions
Body: { "permission_id": "9a2f…-uuid" }
# 同上：缺键 / 非 uuid → 422 点出 permission_id；权限不存在 → 404
```

### 权限清单

| 模块 | 权限示例 |
|------|---------|
| OMS | `order:create`, `order:read`, `order:update`, `order:delete`, `order:merge` |
| WMS | `warehouse:manage`, `inventory:adjust`, `picking:assign`, `picking:complete` |
| TMS | `transport:manage`, `waybill:create`, `exception:handle` |
| Barcode | `barcode:generate`, `barcode:scan` |
| Admin | `user:manage`, `role:manage`, `system:config` |

---

## 3. 仓库管理

### 创建仓库

```
POST /api/v1/warehouses
Body: { "name": "华东一号仓", "code": "WH-001", "address": "上海市..." }
```

### 管理库位

```
# 创建库位（A-01-01 格式：区域-通道-货架-层）
POST /api/v1/warehouses/{warehouse_id}/locations
Body: { "code": "A-01-01", "zone": "A", "aisle": "01", "rack": "01", "level": 1 }

# 查询仓库所有库位
GET /api/v1/warehouses/{warehouse_id}/locations?page=1&size=50
```

### 库位命名规则

```
区域(字母) - 通道(数字) - 货架(数字) - 层(数字)
  A      -   01     -   01     -  1
```

- 区域：A=存储区, B=拣货区, C=出库暂存区, D=入库暂存区
- 每个区域独立编号

---

## 4. 库存管理

### 手动盘点调整

```
POST /api/v1/inventory/adjust
Body: {
  "warehouse_id": "uuid",
  "sku_id": "uuid",
  "location_id": "uuid",
  "quantity": 100,
  "adjust_type": "increase",
  "reason": "月度盘点"
}
```

### 查询库存

```
GET /api/v1/inventory?warehouse_id=uuid&sku_id=uuid&page=1&size=20
```

### 库存预警

系统自动检测低于最小库存阈值的 SKU，触发通知：

```
# 预警规则
inventory.quantity <= inventory.min_qty  → 触发告警通知
```

### ABC/XYZ 分析

```
# 手动触发分析
POST /api/v1/analytics/abc-xyz

# 分析结果
- A 类：高价值（前 20% SKU，贡献 80% 出库金额）
- B 类：中等价值
- C 类：低价值
- X 类：需求稳定（变异系数 < 0.5）
- Y 类：需求波动
- Z 类：需求极不稳定
```

---

## 5. 订单管理

### 创建订单

```
POST /api/v1/orders
Body: {
  "customer_id": "uuid",
  "items": [
    { "sku_id": "uuid", "quantity": 10, "unit_price": 25.50 }
  ],
  "priority": "urgent",
  "shipping_address": "..."
}
```

### 订单状态流转

```
CREATED → CONFIRMED → ALLOCATED → PICKING → PACKED → SHIPPED → DELIVERED
    ↓                                                                    ↓
  CANCELLED                                                           RETURNED
```

### 拆分订单

当订单包含多 SKU 或数量较大时，可拆分为子订单：

```
POST /api/v1/orders/{order_id}/split
Body: { "items": [{ "sku_id": "uuid", "quantity": 5 }] }
```

### 合并订单

将多个订单合并为一个发货组：

```
POST /api/v1/orders/merge
Body: { "order_ids": ["uuid1", "uuid2", "uuid3"] }
Response: { "group_id": "uuid", "merged_orders": [...] }
```

### 查询合并组

```
GET /api/v1/orders/merge/{group_id}
```

---

## 6. 采购与供应商管理

### 创建供应商

```
POST /api/v1/wms/vendors
Body: { "name": "供应商A", "code": "V-001", "contact": "李四", "phone": "138..." }
```

### 创建采购订单

```
POST /api/v1/wms/purchase-orders
Body: {
  "vendor_id": "uuid",
  "items": [{ "sku_id": "uuid", "quantity": 200, "unit_price": 10.00 }],
  "expected_date": "2026-09-01"
}
```

### 采购单状态

```
PENDING → APPROVED → ORDERED → RECEIVED → CLOSED
```

### 入库操作

采购单到货后，确认收货并更新库存：

```
POST /api/v1/wms/shipments
Body: { "purchase_order_id": "uuid", "received_items": [...] }
```

---

## 7. 运输管理

### 创建运输单

```
POST /api/v1/tms/transport-orders
Body: {
  "order_id": "uuid",
  "carrier_config_id": "uuid",
  "warehouse_id": "uuid",
  "destination": "..."
}
```

### 创建运单

```
POST /api/v1/tms/waybills
Body: { "transport_order_id": "uuid", "carrier_code": "SF" }
```

### 处理异常

```
POST /api/v1/tms/exceptions
Body: {
  "waybill_id": "uuid",
  "exception_type": "damage",
  "description": "货物破损",
  "images": ["url1", "url2"]
}
```

### 退货处理

```
POST /api/v1/tms/return-orders
Body: { "waybill_id": "uuid", "reason": "质量问题", "items": [...] }
```

### 承运商配置

```
POST /api/v1/tms/carrier-configs
Body: {
  "carrier_code": "SF",
  "carrier_name": "顺丰速运",
  "api_endpoint": "https://...",
  "api_key": "..."
}
```

---

## 8. 条码管理

### 生成条码

```
POST /api/v1/barcode/generate
Body: { "type": "product", "data": "SKU-001", "format": "CODE128" }
```

### 批量生成

```
POST /api/v1/barcode/batch
Body: { "type": "product", "items": ["SKU-001", "SKU-002", ...], "format": "QR" }
```

### 扫码查询

```
POST /api/v1/barcode/scan
Body: { "code": "SKU-001" }
Response: { "type": "product", "sku_id": "uuid", "name": "产品名称", ... }
```

### 打印模板

```
POST /api/v1/barcode/templates
Body: { "name": "产品标签", "fields": ["name", "sku", "barcode"], "size": "A4" }
```

---

## 9. 数据导入导出

### CSV 导入订单

```
POST /api/v1/import/orders
Content-Type: multipart/form-data
Body: file=@orders.csv

CSV 格式：
order_no,customer_name,items
ORD-001,张三,"SKU-001:10,SKU-002:5"
```

### CSV 导入库存

```
POST /api/v1/import/inventory
Content-Type: multipart/form-data
Body: file=@inventory.csv

CSV 格式：
warehouse_code,sku_code,quantity,min_qty
WH-001,SKU-001,100,10
WH-001,SKU-002,200,20
```

导入规则：
- 仓库编码不存在 → 跳过该行
- SKU 编码不存在 → 跳过该行
- 库存记录已存在 → 更新数量
- 库存记录不存在 → 创建新记录

### CSV 导出

```
GET /api/v1/export/orders?format=csv&date_from=2026-08-01&date_to=2026-08-17
GET /api/v1/export/inventory?warehouse_id=uuid&format=csv
```

---

## 10. 通知与告警

### WebSocket 实时通知

```
连接: ws://host/ws?token=eyJ...
```

支持事件：
- `order.status_changed` — 订单状态变更
- `inventory.low_stock` — 库存预警
- `transport.exception` — 运输异常
- `picking.task_assigned` — 拣货任务分配

### 邮件通知配置

在 `.env` 中配置：

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=noreply@example.com
SMTP_PASSWORD=***
SMTP_FROM=noreply@example.com
```

### Firebase 推送（可选）

```env
FIREBASE_ENABLED=true
FIREBASE_CREDENTIALS_PATH=/path/to/firebase-service-account.json
```

---

## 11. 系统监控

### 健康检查

```
GET /api/v1/health
Response: {
  "status": "healthy",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}

GET /api/v1/ready
Response: { "status": "ready" }
```

### 日志查看

日志格式为 JSON，默认输出到 stdout：

```bash
# 查看 app 日志
docker logs oms-wms-tms-app -f

# 查看 worker 日志
docker logs oms-wms-tms-celery_worker -f
```

### Celery 任务监控

```bash
# 查看活跃任务
docker exec oms-wms-tms-celery_worker celery -A src.celeryconf inspect active

# 查看计划任务
docker exec oms-wms-tms-celery_worker celery -A src.celeryconf inspect scheduled
```

### 数据库维护

```bash
# 备份数据库
PGPASSWORD=*** pg_dump -h localhost -U postgres oms_wms_tms | gzip > backup_$(date +%Y%m%d).sql.gz

# 恢复数据库
gunzip < backup_20260817.sql.gz | PGPASSWORD=*** psql -h localhost -U postgres oms_wms_tms

# 手动执行迁移
alembic upgrade head

# 查看迁移版本
alembic current

# 回滚一步
alembic downgrade -1
```

### Redis 维护

```bash
# 查看 Redis 信息
docker exec oms-wms-tms-redis redis-cli INFO

# 清理过期 key
docker exec oms-wms-tms-redis redis-cli KEYS "*" | head -20

# 内存使用情况
docker exec oms-wms-tms-redis redis-cli MEMORY USAGE
```

### 定时任务一览

| 任务 | 频率 | 说明 |
|------|------|------|
| `dispatch_outbox_events` | 每 30 秒 | 派发 Outbox 事件 |
| `cleanup_old_sync_logs` | 每小时 | 清理 30 天前同步日志 |
| `cleanup_expired_tokens` | 每小时 | 清理过期 token |
| `daily_aggregation` | 每日 00:00 | 每日数据汇总 |
| `compute_abc_xyz_analysis` | 每周一 02:00 | ABC/XYZ 分析 |
| 库存预警检查 | 每 15 分钟 | 低于最小库存告警 |

---

## 常见问题

### Q: 忘记管理员密码

```bash
# 通过 Python 脚本重置
python -c "
import asyncio
from src.core.database import get_async_session
from src.auth.service import AuthService
async def reset():
    async for db in get_async_session():
        await AuthService.reset_password(db, 'admin', 'new_password')
        print('密码已重置')
asyncio.run(reset())
"
```

### Q: 数据库连接数满了

检查 `DB_POOL_SIZE` 和 `DB_MAX_OVERFLOW` 配置，适当调整：

```env
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
```

### Q: Celery 任务不执行

1. 检查 Redis 连接：`redis-cli ping`
2. 检查 Worker 状态：`docker logs oms-wms-tms-celery_worker`
3. 手动触发任务测试：

```python
from src.tasks.maintenance import cleanup_old_sync_logs
result = cleanup_old_sync_logs.delay()
print(result.get(timeout=10))
```

### Q: 前端页面空白

1. 确认后端 API 正常运行
2. 检查 `CORS_ORIGINS` 配置是否包含前端域名
3. 检查浏览器控制台是否有 401/403 错误
