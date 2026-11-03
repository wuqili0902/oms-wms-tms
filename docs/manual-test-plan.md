# 手工测试计划 — OMS-WMS-TMS

## 环境准备

### 1. 启动本地开发环境

```bash
# 方式一：docker compose（推荐）
cd deploy && docker compose -f docker-compose.prod.yml up -d

# 方式二：Helm（K8s 集群）
helm install oms-wms-tms ./deploy/helm/tms --set image.tag=latest
```

### 2. 验证基础服务

- [ ] PostgreSQL 连接正常，数据库 schema 已迁移 (`alembic upgrade head`)
- [ ] Redis 连接正常（用于 TokenStore、RateLimiter）
- [ ] Nginx 反向代理前端正常访问
- [ ] Uvicorn 后端 API 可访问 `http://localhost:8000/api/v1/health`

### 3. 准备测试数据

- [ ] 创建至少 2 个仓库（启用状态）
- [ ] 每个仓库添加 5+ 个库位（A-01-01 格式）
- [ ] 录入 10+ SKU（含重量/体积属性）
- [ ] 创建 3+ 供应商
- [ ] 配置 2+ 承运商（TMS → CarrierConfig）

---

## 一、认证与权限 (Auth) — ~8 端点

### 登录流程
- [ ] POST `/api/v1/auth/login` — 用户名密码正确 → 返回 access_token + refresh_token
- [ ] POST `/api/v1/auth/refresh` — 使用 refresh_token 获取新 token
- [ ] POST `/api/v1/auth/logout` — 清除当前 token

### RBAC 权限验证
- [ ] 创建用户并分配不同角色（admin / operator / viewer）
- [ ] 普通用户访问管理员页面 → 应返回 403
- [ ] Token 过期后请求 API → 应返回 401 + refresh_token 刷新流程

### 安全验证
- [ ] 使用无效 token 调用受保护接口 → 应被拦截
- [ ] TokenStore TOCTOU 竞态条件 — 并发刷新同一 token → 不应出现数据不一致

---

## 二、订单管理 (OMS) — ~10 端点

### CRUD 操作
- [ ] POST `/api/v1/orders` — 创建新订单（含 SKU、数量、客户信息）
- [ ] GET `/api/v1/orders` — 按状态/客户/日期过滤查询
- [ ] PUT `/api/v1/orders/{id}` — 更新订单信息
- [ ] DELETE `/api/v1/orders/{id}` — 取消订单

### 业务逻辑验证
- [ ] 订单拆分 — 将一个大订单拆分为多个子订单（数量限制触发）
- [ ] 订单合并 — 选择多个订单合并到 MergeGroup
- [ ] URGENT 紧急订单标记 — 创建时设置优先级，列表中应高亮显示
- [ ] 状态日志 — 每次状态变更应在 OrderStatusLog 中有记录

### 数据一致性
- [ ] 删除订单后关联的库存/物流记录是否级联清理
- [ ] 并发修改同一订单 → 不应出现数据覆盖

---

## 三、仓储管理 (WMS) — ~15 端点

### 仓库与库位
- [ ] POST `/api/v1/warehouses` — 创建仓库（含容量限制）
- [ ] PUT `/api/v1/warehouses/{id}` — 启用/禁用仓库
- [ ] POST `/api/v1/locations` — 创建多层级库位（区域→通道→货架→层）

### 库存管理
- [ ] POST `/api/v1/inventory` — 录入初始库存（SKU + 数量）
- [ ] PUT `/api/v1/inventory/{id}` — 盘点调整（增加/减少）
- [ ] GET `/api/v1/inventory?warehouse_id=X` — 按仓库查询库存

### Picking 拣货服务
- [ ] POST `/api/v1/picking/tasks` — 创建拣货任务
- [ ] FEFO 逻辑验证 — 先入先出拣货时，最早入库的 SKU 优先被拣选
- [ ] 拣货完成确认 → 库存应自动扣减

### 采购与供应商
- [ ] POST `/api/v1/suppliers` — 创建供应商
- [ ] POST `/api/v1/purchase-orders` — 创建 PO（关联供应商 + SKU）
- [ ] PO 状态流转：DRAFT → CONFIRMED → RECEIVED → CLOSED

### 发货管理
- [ ] POST `/api/v1/shipments` — 创建发货单（关联订单 + 物流单号）
- [ ] 发货单状态：PENDING → SHIPPED → DELIVERED

### SKU 管理
- [ ] CRUD SKU 基本信息
- [ ] 修改 SKU 重量/体积属性 → 影响运费计算

---

## 四、运输管理 (TMS) — ~25 端点

### 运输单
- [ ] POST `/api/v1/transport-orders` — 创建运输单（关联承运商 + 仓库）
- [ ] GET `/api/v1/transport-orders` — 按状态/日期过滤
- [ ] PUT `/api/v1/transport-orders/{id}` — 更新运输单状态

### 运单管理
- [ ] POST `/api/v1/waybills` — 创建运单（关联承运商配置）
- [ ] 运单状态流转：CREATED → IN_TRANSIT → DELIVERED / EXCEPTION

### 退货单
- [ ] POST `/api/v1/returns` — 创建退货申请
- [ ] 退货审批流程 → 状态更新

### 异常管理
- [ ] POST `/api/v1/exceptions` — 记录运输异常（破损、延误等）
- [ ] 异常处理 → 标记为 RESOLVED

### 路线规划
- [ ] POST `/api/v1/route-plans` — 创建路线方案
- [ ] RoutePlan 关联多个运输单

### 运价管理
- [ ] POST `/api/v1/freight-tiers` — 配置分层运价（按重量/距离）
- [ ] 运费计算验证 — 输入不同参数 → 返回正确运费

### ML 预测
- [ ] POST `/api/v1/ml/train` — 训练需求预测模型
- [ ] POST `/api/v1/ml/predict` — 预测未来需求量（传入时间范围）
- [ ] 验证预测结果合理性（不应为负数或异常大值）

---

## 五、条码系统 (Barcode) — ~6 端点

### 条码生成
- [ ] POST `/api/v1/barcode/generate` — 按模板批量生成 Code128/QR 码
- [ ] 生成的条码在 PDA 上可扫描识别

### 条码验证
- [ ] POST `/api/v1/barcode/validate` — 校验格式与唯一性
- [ ] 重复条码 → 应返回错误

### Excel 导出
- [ ] POST `/api/v1/barcode/excel` — 批量导出到 Excel
- [ ] 下载的文件可正常打开，内容正确

---

## 六、物流运单 (Logistics) — 6 端点

### 快递鸟集成
- [ ] POST `/api/v1/logistics/waybill/create` — 创建面单；响应 `tracking_source` = `kdniao`（已配置）/ `local_placeholder`（未配置：快递侧没有这张面单，标签打印出来却一模一样）
- [ ] GET `/api/v1/logistics/waybill/{tracking}/track` — 查询快递轨迹（`POST /api/v1/logistics/track` 这个端点不存在，别按它测）
- [ ] 已配置快递鸟凭据 → 200，`source: kdniao`，轨迹时间线连贯
- [ ] 未配置凭据 → **501** `NOT_IMPLEMENTED`，消息点名 `KDNIAO_EBUSINESS_ID`；界面上不得出现"派送中/已签收"
- [ ] `LOGISTICS_MOCK_ENABLED=true` → 200，`source: mock`，每一行以【演示数据】开头

### 承运商 API
- [ ] `CARRIER_API_ENDPOINTS` 配置多个承运商 → 查单/询价路由到对应端点，响应 `source: carrier_api`
- [ ] 端点调用失败 → 502「查单失败/询价失败」，**不会**回落成演示轨迹或演示费率（演示开关开着也一样；本系统没有自动重试，失败就是失败）
- [ ] 未配置端点且未开演示开关 → 501，消息点名 `CARRIER_API_ENDPOINTS`

---

## 七、通知系统 (Notification) — ~3 端点

### WebSocket 实时推送
- [ ] WS `/ws` 连接建立成功
- [ ] 触发事件（如订单状态变更）→ 前端应收到实时推送
- [ ] 断线重连 → 应能恢复订阅

### 邮件通知
- [ ] SMTP 配置正确 → 发送测试邮件
- [ ] 模板变量替换正确（订单号、客户名等）

---

## 八、数据对接 (Connectors) — ~6 端点

### Shopify Webhook
- [ ] POST `/api/v1/connectors/shopify/webhook` — 模拟 Shopify 推送
- [ ] 接收到的事件是否正确处理（订单创建/库存变更）

### Amazon SP-API
- [ ] 「电商对接」页粘贴 SP-API `Order` 对象 → 导入订单（返回 `order_no`、行数、金额）
- [ ] 缺 `AmazonOrderId` / 无 `OrderItems` → 422 并点名缺什么（不产生订单）
- [ ] 记录发货交接（单号+承运商+运单号）→ 200，`sync_status: not_configured`
- [ ] （未实现，勿作为验收项）拉取订单/状态轮询/OAuth2 授权流程 — 出站动作返回 `not_implemented`

### ERP 连接器
- [ ] 无对外导入端点：ERP 订单经 `import_erp_order` 由调用方（脚本/集成服务）写入
- [ ] 通过 `import_erp_order` 导入后 OMS 中应出现对应订单记录（无商品行会被 422 拒收）

### 连接器管理（侧边栏 `/connectors/manage`）
- [ ] 列表显示 amazon 与 shopify，逐项标出能力"已实现/未实现/不适用"
- [ ] 凭据列显示变量名与"已配置/未配置"，**不显示密钥值**
- [ ] 断网后打开此页 → 页面出现告警条与错误提示（不是"暂无连接器数据"）
- [ ] 无「同步」按钮（旧版每个按钮都 404，且弹一句无原因的"同步失败"）
- [ ] 「配置说明」页只读：无 AWS Access Key / Shopify Admin API Token 输入框，不发保存请求
- [ ] GET `/api/v1/connectors/sap` → 404 并说明本系统只有 amazon 与 shopify

---

## 九、数据导入导出 — Import/Export

### CSV 导入
- [ ] 上传订单 CSV → 解析 → 逐行创建订单（调用 oms_service.create_order）
- [ ] 上传库存 CSV → 校验 SKU/仓库 → 创建或更新库存记录
- [ ] 错误行应有明确提示，不中断整体流程

### CSV 导出
- [ ] 导出订单数据为 CSV — 字段完整、格式正确
- [ ] 导出库存数据为 CSV — 包含所有必要信息

### Outbox 事件派发
- [ ] 触发业务操作 → Outbox 表应记录事件
- [ ] Celery task `dispatch_outbox_events` 定时执行 → HTTP dispatch 成功
- [ ] 失败事件应有重试机制

---

## 十、离线同步 (Offline / PDA) — SyncQueue

### PDA 离线操作
- [ ] PDA 设备断网后操作入库/出库 → SyncQueue 应入队
- [ ] SQLite 本地数据库 (`wms_pda.db`) 写入正常
- [ ] 网络恢复后同步队列 → 变更正确应用到主库

### PDA WebSocket
- [ ] PDA 设备连接 WS `/ws/pda` — 实时通信正常
- [ ] 推送消息到指定 PDA 设备

---

## 十一、管理后台 (Admin) — HTML 页面

### 仪表盘
- [ ] 数据概览正确（订单量、库存状态、运输进度）
- [ ] 图表渲染正常（趋势图、饼图等）

### 用户管理
- [ ] 用户列表 → 创建/编辑/删除
- [ ] 分配角色 → 权限生效验证

### 仓库/订单/库存管理页面
- [ ] 各模块 HTML 页面可正常加载
- [ ] CRUD 操作通过后端 API 正确执行

---

## 十二、数据分析 (Analytics) — ~5 端点

### 仪表盘统计
- [ ] GET `/api/v1/analytics/dashboard` — 返回汇总数据
- [ ] 各业务域数据准确（与数据库实际值一致）

### ABC/XYZ 分析
- [ ] POST `/api/v1/analytics/compute-abc-xyz` — 触发计算
- [ ] 结果分类合理（A类=高价值，X类=稳定需求等）

---

## 十三、定时任务 (Celery)

### 验证 Celery Worker 启动
- [ ] `celery -A src.celery_app worker` 正常启动
- [ ] Beat scheduler 正常运行

### 各 Task 验证
| Task | 验证方法 |
|------|----------|
| `cleanup_old_sync_logs` | 手动插入 30+ 天前的 sync_log → 执行任务 → 确认删除 |
| `cleanup_expired_tokens` | 插入过期 token → 执行任务 → 确认清理 |
| `dispatch_outbox_events` | 手动插入 outbox event → 执行任务 → 确认 dispatch |
| `daily_aggregation` | 触发聚合计算 → 验证汇总数据正确性 |
| `compute_abc_xyz_analysis` | 触发分析 → 验证分类结果 |
| 库存预警 | 设置低库存 SKU → 验证通知触发 |
| 订单状态同步 | 模拟状态变更 → 验证同步结果 |

---

## 十四、基础设施验证

### 健康检查
- [ ] GET `/api/v1/health` — DB + Redis 检查通过
- [ ] GET `/api/v1/ready` — readiness probe 返回 200

### 速率限制
- [ ] 短时间内发送大量请求 → 应被限流（429）
- [ ] `settings.testing` 模式下应绕过限流

### CSRF 保护
- [ ] POST 表单请求缺少 CSRF token → 应被拦截
- [ ] GET/PUT/DELETE 不受影响

### OpenTelemetry TraceContext
- [ ] API 调用返回 trace_id — 可在日志中追踪链路
- [ ] RequestID 中间件正确注入

### Sentry 错误追踪（可选）
- [ ] 触发异常 → Sentry 后台应有对应事件

---

## 十五、前端 (Vue 3 SPA) — 页面浏览测试

### 路由遍历
逐一访问以下页面，确认无白屏/报错：
- [ ] `/` — 首页/仪表盘
- [ ] `/orders` — 订单列表 + 详情
- [ ] `/inventory` — 库存管理
- [ ] `/warehouses` — 仓库管理
- [ ] `/suppliers` — 供应商管理
- [ ] `/transport-orders` — 运输单管理
- [ ] `/waybills` — 运单管理
- [ ] `/returns` — 退货管理
- [ ] `/barcode` — 条码生成/查询
- [ ] `/analytics` — 数据分析
- [ ] `/admin/users` — 用户管理
- [ ] `/settings` — 系统设置

### PWA 功能
- [ ] 离线访问 → Service Worker 缓存生效
- [ ] 重新上线 → 自动同步数据

---

## 十六、移动端 (React Native Expo) — PDA 设备测试

### 扫码功能
- [ ] PDA 扫描条码 → 返回对应业务对象（SKU/订单）
- [ ] Code128 / QR 码均能识别

### 离线模式
- [ ] 断网状态下操作入库/出库 → 数据写入本地 AsyncStorage
- [ ] 网络恢复 → 自动同步到服务器

### Expo 导出验证
- [ ] `expo export --platform android` — 构建成功
- [ ] APK/IPA 安装后功能正常

---

## 十七、部署验证 (Docker + Helm)

### Docker Compose
- [ ] `docker compose -f docker-compose.prod.yml up` — 所有容器启动成功
- [ ] Nginx → Uvicorn → PostgreSQL/Redis 链路通畅
- [ ] 日志输出正常（JSON 格式）

### Helm Chart (K8s)
- [ ] `helm install oms-wms-tms ./deploy/helm/tms` — 部署成功
- [ ] Deployment + Service + Ingress + HPA 均正常运行
- [ ] Migration Job 执行数据库迁移
- [ ] Backup CronJob 按计划触发

### CI/CD Pipeline
- [ ] Push code → GitHub Actions 自动触发
- [ ] lint (ruff + mypy) — 通过
- [ ] test (PG16 + Redis7 + alembic + pytest) — 207 passed / 0 failed
- [ ] Docker build → GHCR push — 成功
- [ ] Helm deploy — Pod 启动正常

---

## 十八、安全验证（渗透测试基础）

### 认证绕过
- [ ] 直接访问管理页面（无 token）→ 应返回 401
- [ ] 使用过期 token → 应被拒绝

### SQL Injection / XSS
- [ ] 输入 `' OR 1=1 --` — 不应执行恶意 SQL
- [ ] 输入 `<script>alert(1)</script>` — 不应执行脚本

### CORS 配置
- [ ] 非允许源请求 API → 应被拒绝
- [ ] `debug=true` + `CORS_ORIGINS=["*"]` → 应有警告日志

---

## 十九、性能与压力测试（可选）

### API 响应时间
| 接口 | 预期 |
|------|------|
| `/api/v1/health` | < 50ms |
| `/api/v1/orders?page=1&size=20` | < 200ms |
| `/api/v1/inventory?warehouse_id=X` | < 300ms |

### 并发测试
- [ ] 100 用户同时登录 → TokenStore 无竞态
- [ ] 50 用户同时查询库存 → 数据库连接池不耗尽

---

## 二十、数据迁移验证 (Alembic)

- [ ] `alembic upgrade head` — 所有 migration 执行成功
- [ ] `alembic downgrade base` — 回滚正常（开发环境）
- [ ] 新增字段 → 旧版本代码不崩溃（向后兼容）

---

## 测试记录模板

每次手工测试后，请记录：

```markdown
### [模块名] - [日期]
- [x] 测试项1 — 通过 / 失败: [原因]
- [ ] 测试项2 — 跳过: [原因]
- [ ] 测试项3 — 待验证
```

---

## 优先级建议

**P0（必须验证）**：登录认证、订单 CRUD、库存管理、PDA 扫码、部署启动  
**P1（重要）**：RBAC 权限、拣货服务、条码生成/验证、物流追踪、Celery 任务  
**P2（次要）**：ML 预测、ABC/XYZ 分析、邮件通知、WebSocket 推送  
**P3（可选）**：Amazon SP-API、Shopify Webhook、Sentry 集成
