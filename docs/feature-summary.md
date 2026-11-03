# OMS-WMS-TMS 功能总结

## 项目概述

OMS-WMS-TMS 是一套一体化物流管理平台，覆盖订单管理（OMS）、仓储管理（WMS）、运输管理（TMS）三大核心业务域，集成条码、移动端 PDA、物流追踪、数据分析等能力。前端采用 Vue 3 + TypeScript + Element Plus，后端采用 FastAPI + SQLAlchemy async + PostgreSQL + Redis + Celery。

---

## 一、认证与权限（Auth）

| 功能 | 说明 |
|------|------|
| JWT 登录/刷新 | `/api/v1/auth/login`、`/refresh`、`/logout`，支持 access + refresh token |
| RBAC 角色权限 | `Role`、`Permission`、`UserRole`、`RolePermission` 四表模型，角色可分配细粒度权限 |
| 用户管理 | CRUD 用户、分配角色、密码重置 |
| Token 存储 | Redis 内存双层缓存，支持 TOCTOU 安全检查、过期清理 |

---

## 二、订单管理（OMS）

| 功能 | 说明 |
|------|------|
| 订单 CRUD | 创建/查询/更新/取消，支持按状态、客户、日期过滤 |
| 订单状态流转 | 状态日志记录（`OrderStatusLog`），完整审计轨迹 |
| 订单拆分/合并 | 按数量拆分订单；合并多个订单到 `MergeGroup` |
| 优先级标记 | 支持 URGENT 紧急订单标识 |
| 合并组管理 | `GET /merge/{group_id}` 查看合并组详情 |

---

## 三、仓储管理（WMS）

| 功能 | 说明 |
|------|------|
| 仓库管理 | 仓库 CRUD、仓库容量、启用/禁用 |
| 库位管理 | 多层级库位（A-01-01 格式），支持区域/通道/货架/层，按仓库查询 |
| 库存管理 | SKU 级库存记录，含数量/最小库存/锁定数量，支持盘点调整 |
| 拣货服务（Picking） | FEFO 先入先出拣货、按库位分配拣货任务、拣货完成确认、自动补货建议 |
| 供应商管理 | 供应商 CRUD，采购订单关联 |
| 采购订单 | PO 创建/查询/状态流转，关联供应商和 SKU |
| 发货管理 | 发货单创建/查询，关联订单和物流单号 |
| 发票/贷项单 | 供应商发票、贷项单管理 |
| SKU 管理 | SKU 基本信息、重量/体积属性 |
| 库存分析 | ABC/XYZ 分类分析，ABC 品类覆盖率 |

---

## 四、运输管理（TMS）

| 功能 | 说明 |
|------|------|
| 运输单管理 | 运输单 CRUD，关联承运商配置、仓库 |
| 运单管理 | Waybill 创建/查询/状态更新 |
| 退货单管理 | 退货单创建/查询/状态流转 |
| 异常管理 | 运输异常记录/查询/处理 |
| 路线规划 | RoutePlan 路线方案管理 |
| 运价管理 | FreightTier 分层运价体系 |
| 承运商配置 | CarrierConfig 管理承运商信息（唯一主键，carrier_code 唯一约束） |
| ML 预测 | 训练需求预测模型、预测未来需求量（Pydantic schema 校验） |
| ERP 对接 | TMS 侧 ERP connector（报文构造/序列化，无对外传输端点） |

---

## 五、条码系统（Barcode）

| 功能 | 说明 |
|------|------|
| 条码生成 | 按模板批量生成条码，支持 Code128/QR |
| 条码验证 | 校验条码格式与唯一性 |
| 扫码查询 | PDA 扫码后返回对应业务对象 |
| 模板管理 | 条码打印模板 CRUD |
| Excel 批量生成 | 批量导出条码到 Excel 文件 |

---

## 六、物流追踪（Logistics）

| 功能 | 说明 |
|------|------|
| 物流状态追踪 | 快递鸟轨迹查询；响应带 `source` 说明轨迹出处：已配置 → `kdniao`；**未配置 → 501**（不再按运单号哈希编造 已揽收/运输中/已签收） |
| 面单号出处 | `POST /waybill/create` 响应带 `tracking_source`：`kdniao`（快递鸟给的号）/ `local_placeholder`（本机拼的号，快递侧没有这张面单） |
| 演示数据 | 需显式 `LOGISTICS_MOCK_ENABLED=true` 才启用；每条轨迹/每条报价都标 `source: mock` + 演示数据说明，用于开发界面而非答复客户 |
| 承运商集成 | 多承运商 API 接入（`CARRIER_API_ENDPOINTS`），成功 → `source: carrier_api`；调用失败 → 抛错（路由渲染 502），不回落演示数据，也没有自动重试 |
| 运费询价 | 同上：端点报价为准，内置费率表只在演示开关开启时可用并标注"演示费率" |

---

## 七、通知系统（Notification）

| 功能 | 说明 |
|------|------|
| WebSocket 实时推送 | `/ws` 端点，事件驱动实时通知 |
| 邮件通知 | SMTP 邮件发送服务 |
| 通知模板 | 按事件类型配置通知模板 |
| Firebase 推送 | 可选集成 Firebase Cloud Messaging |

---

## 八、数据对接（Connectors）

| 功能 | 说明 |
|------|------|
| Shopify Webhook | 接收 Shopify 订单事件（HMAC 签名校验），`orders/create` → OMS 订单，`orders/fulfilled` → 运单号消息 |
| Amazon SP-API | 订单导入（SP-API 原始 `Order` 对象）+ 发货交接记录；**出站动作（状态轮询/运单号上传/库存同步）未接入**，返回 `not_implemented` |
| ERP 连接器 | 导入 ERP 订单到 OMS（`import_erp_order`）；SAP/X12 报文模型与序列化，无对外传输端点 |
| 连接器注册表 | `GET /connectors/status`、`GET /connectors/{id}`：列出本构建的连接器（只有 amazon、shopify）、逐项能力（已实现/未实现/不适用）与凭据是否已配置；**只回报变量名，不回报密钥值**，凭据写在服务器 `.env`，无网页配置 CRUD（旧版的 AWS Access Key / Shopify Admin Token 表单指向不存在的端点，已移除） |
| 「同步」 | 无：`POST /connectors/amazon/sync` → 501（出站未实现），`/shopify/sync` → 422（推送式对接无可拉取数据） |

---

## 九、数据导入导出

| 功能 | 说明 |
|------|------|
| CSV 订单导入 | 上传 CSV 文件 → 解析 → 逐行创建订单（调用 `oms_service.create_order`） |
| CSV 库存导入 | 上传 CSV → 校验 SKU/仓库 → 创建或更新库存记录 |
| CSV 数据导出 | 订单/库存数据导出为 CSV |
| 事件 Outbox | 异步事件可靠派发（HTTP dispatch），支持重试和标记完成/失败 |

---

## 十、离线同步（Offline / PDA）

| 功能 | 说明 |
|------|------|
| PDA 离线操作 | 移动端离线状态下操作入队（SyncQueue） |
| 同步队列 | `SyncQueueService` 管理离线变更，支持查询待同步、标记同步完成/失败 |
| PDA WebSocket | PDA 设备实时通信 |
| PDA API | 移动端专属接口（`/api/v1/mobile`） |

---

## 十一、管理后台（Admin）

| 功能 | 说明 |
|------|------|
| HTML 管理页面 | 仓库列表、订单管理、库存管理等 HTML 页面 |
| 用户管理 | 用户列表/创建/编辑/删除 |
| 仪表盘 | 数据概览（订单量、库存状态、运输进度等） |

---

## 十二、数据分析（Analytics）

| 功能 | 说明 |
|------|------|
| 仪表盘统计 | 各业务域汇总数据 |
| 趋势分析 | 订单/运输趋势图表 |
| ABC/XYZ 分析 | 库存品类分析 |

---

## 十三、定时任务（Celery）

| 任务 | 说明 |
|------|------|
| `cleanup_old_sync_logs` | 清理 30 天前的同步日志 |
| `cleanup_expired_tokens` | 清理过期 token 缓存 |
| `dispatch_outbox_events` | 定时派发 Outbox 事件 |
| `daily_aggregation` | 每日数据汇总 |
| `compute_abc_xyz_analysis` | ABC/XYZ 分析计算 |
| 库存预警 | 低于最小库存阈值时触发通知 |
| 订单状态同步 | 定时同步订单状态 |

---

## 十四、基础设施

| 组件 | 说明 |
|------|------|
| 健康检查 | `/api/v1/health`（DB/Redis 检查）、`/api/v1/ready`（readiness probe） |
| 速率限制 | 可配置阈值/窗口，支持 `settings.testing` 绕过 |
| CSRF 保护 | 表单 Content-Type 校验，防止跨站请求伪造 |
| 请求链路追踪 | OpenTelemetry TraceContext 注入，RequestID 中间件 |
| 审计日志 | 所有 API 调用记录到 AuditLog |
| 错误追踪 | Sentry 集成（可选） |
| CORS 配置 | 可配置允许源列表 |

---

## 十五、前端（Vue 3）

| 功能 | 说明 |
|------|------|
| 路由 | 33 条路由，覆盖全部业务页面 |
| 状态管理 | Pinia store |
| UI 组件 | Element Plus 2.14 |
| PWA | vite-plugin-pwa 支持离线访问 |
| TypeScript | 完整 TS 类型覆盖 |
| 构建 | Vite 8，支持 dev/build/preview |

---

## 十六、移动端（React Native / Expo）

| 功能 | 说明 |
|------|------|
| PDA 扫码 | 扫码入库/出库/盘点 |
| 离线模式 | AsyncStorage 替代 localStorage，离线操作队列 |
| Expo 导出 | `expo export --platform android` 验证通过 |

---

## 十七、CI/CD

| 阶段 | 说明 |
|------|------|
| CI (ci.yml) | lint (ruff + mypy) → test (PG 16 + Redis 7 + alembic migrate + pytest) → frontend build |
| CD (deploy.yml) | test → Docker build → GHCR push → Helm deploy (placeholder) |
| Docker | 多阶段构建，Nginx 反向代理前端，Uvicorn 运行后端 |
| Helm Chart | 完整 K8s 部署：Deployment + Service + Ingress + HPA + Secret + ConfigMap + Migration Job + Backup CronJob |

---

## API 端点统计

| 域 | 端点数 |
|----|--------|
| Auth | ~8 |
| OMS | ~10 |
| WMS | ~15 |
| TMS | ~25 |
| Barcode | ~6 |
| Logistics | 6 |
| Analytics | ~5 |
| Admin | ~10 |
| Connectors | ~6 |
| Notification | ~3 |
| Mobile | ~8 |
| Health | 2 |
| **合计** | **~104** |

## 测试覆盖

- 后端 pytest：2540 passed / 2 skipped / 0 failed（`python -m pytest tests`）
- 前端 vitest：80 passed / 2 skipped（`npm test`），`npm run build` 含 `vue-tsc` 类型检查通过
- 覆盖模块：认证、订单、仓储、运输、条码、通知、导入导出、离线同步、定时任务、Picking、ML 模型、连接器、物流面单出处（轨迹/面单号的 source 契约）
