# OMS-WMS-TMS 岗位操作手册（SOP）

> **版本**: 1.0.0
> **更新日期**: 2026-08
> **适用对象**: 订单员、仓管员、运输调度员、系统管理员
> **配套文档**: 接口细节见 [`docs/operations-manual.md`](./operations-manual.md)

---

## 一、手册定位

本手册是**面向业务操作人员的作业指导书**,按岗位角色和端到端业务流程组织,回答"我每天要做什么、按什么顺序做"。它不重复 API 参数细节（见配套接口文档），而是聚焦：

- **业务主链路**:订单 → 仓库作业 → 运输 → 签收的完整流转
- **岗位分工**:每个角色负责哪些操作
- **状态机**:单据在什么状态下可以做什么、不能做什么
- **异常处理**:出错了怎么办

---

## 二、业务总览：一张图看懂全链路

```
┌─────────┐   拆单/合并   ┌─────────┐   波次拣货   ┌─────────┐
│ OMS 订单 │ ───────────→ │ WMS 仓库 │ ───────────→ │ WMS 发货 │
│ (接单)   │              │ 拣/包/发 │              │ 交接承运 │
└─────────┘              └─────────┘              └────┬────┘
        ↑                                               ↓
   电商对接(Amazon/      盘点/调拨/采购               ┌─────────┐
   Shopify)                                          │ TMS 运输 │
                                                       │ 追踪/签收│
                                                       └────┬────┘
                                                            ↓
                                                     退货 / 异常处理
```

**三条单据流**:

| 流 | 起点 | 终点 | 负责系统 |
|------|------|------|------|
| 订单流 | 电商平台/手工录入 | 已完成/已取消 | OMS |
| 库存流 | 采购入库 → 销售出库 | 盘点平账 | WMS |
| 运输流 | 发货交接 | 签收(POD) / 退货 | TMS + Logistics |

---

## 三、订单员（OMS）作业流程

### 3.1 接单

外部订单有两种来源：

1. **电商对接**:Shopify 由 Webhook 主动推送（带 HMAC 签名）自动生成 OMS 订单；Amazon 在「电商对接」页把 SP-API 的 `Order` 对象粘贴导入，或调用 `POST /connectors/amazon/orders`
2. **手工录入**:`/admin/orders` 或 `POST /orders`,填写客户、优先级（普通/加急 URGENT）、商品明细

**Amazon 导入必须带上的内容**（缺任一项都会 422 并点名缺什么，不再是"导入成功"的空单）：

- `AmazonOrderId`：亚马逊订单号，追踪回传/对账/工单都靠它
- `OrderItems`：至少一行，且每行要有 `SellerSKU`（FBA 行可用 `ASIN`）或条码
- 数量为 ≥1 的整数、单价是金额（亚马逊把套装数量写成 `"2 items"` 时会拒收并指出是第几行）

> 加急单（URGENT）会进入高优先级队列，拣货波次优先分配。

> **尚未接入**：Amazon 订单状态轮询、库存同步、追踪自动回传（需要 SP-API 凭据）。
> 发货交接用 `POST /connectors/amazon/tracking` 在本地记录（单号+承运商+运单号三项必填），
> 页面会明确标出"未配置凭据，未回传亚马逊"，不要当作已同步。

> **看连接器状态**：侧边栏「连接器管理」列出本系统有哪些连接器（只有 amazon 与
> shopify）、每项能力是"已实现/未实现/不适用"、以及凭据是否已配置。
> SP-API 凭据写在服务器 `.env`（`AMAZON_SP_API_CLIENT_ID/CLIENT_SECRET/REFRESH_TOKEN/REGION`，
> 是 LWA 的密钥，不是 AWS Access Key），网页不输入也不显示密钥值。
> 页面上的「同步」按钮已删除——两个连接器都没有可拉取的一侧，接口只会回答
> 501（Amazon 未实现）/422（Shopify 是推送式），以前那个按钮弹出来的"同步成功"
> 没有任何同步发生过。

### 3.2 订单状态机

```
pending ──确认──→ confirmed ──处理──→ processing ──拣货──→ picking ──完成──→ completed
   │                │                  │                  │
   └──────取消/失败────────────────────┴──────────────────┘ (cancelled / failed)
```

| 状态 | 含义 | 允许的操作 |
|------|------|-----------|
| `pending` | 待确认 | 确认、删除 |
| `confirmed` | 已确认，等待处理 | 进入 processing |
| `processing` | 处理中 | 开始拣货 |
| `picking` | 拣货中 | 完成 |
| `completed` | 已完成（终态） | 无，可发货转 TMS |
| `cancelled` / `failed` | 终态 | 不可再流转 |

### 3.3 拆单与合并

**拆单**(`POST /{order_id}/split`):当单个订单的商品分布在多个仓库、或库存不足时，拆分为多个履约子单，指定每个子单的发货仓库。

- 场景:客户下一单买了 A 仓和 B 仓各一部分货 → 拆成两单分别发货
- 结果:生成合并组（merge group），可用 `GET /merge/{group_id}` 查看关联关系

**合并**(`POST /orders/merge`):同一客户的多个订单合并为一批次发货，节省运费。

- 场景:客户多次下单未付款/未发货，合并后统一打包
- 输入:待合并的 order_ids + 目标仓库

### 3.4 订单员每日检查清单

- [ ] 处理 `pending` 状态的新订单（确认或取消）
- [ ] 检查加急单是否已进入拣货波次
- [ ] 核对拆单/合并组是否正确关联
- [ ] 通过 `/admin/orders` 导出昨日订单对账

---

## 四、仓管员（WMS）作业流程

### 4.1 仓库与库位初始化（一次性配置）

1. **创建仓库**:`POST /warehouses`,填写编码、名称、类型（中心仓/分拨/前置仓）、地址
2. **建库位**:`POST /warehouses/{wh_id}/locations`,按"区-巷道-层-格架-仓位"五级定位建立库位，标注容量与类型（存储/拣选/收货）

> 库位是后续拣货路径优化的空间基础。

### 4.2 入库流程（采购到货）

```
采购单 PO 创建 → 审批 → 收货(receive) → 上架(库存增加) → 盘点
```

1. **建采购单**:`POST /purchase-orders`,选供应商、预计到货日、商品行（SKU/数量/单价）
2. **审批**:`POST /purchase-orders/{po_id}/approve`
3. **收货入库**:`POST /purchase-orders/{po_id}/receive` → 库存自动增加
4. 或直接 `POST /warehouses/inventory/items` 对单个 SKU 入库（带批次号、有效期）

### 4.3 出库流程（销售发货）

```
订单 confirmed → 拣货波次 → 拣货 → 打包 → 创建发货单 → 交接承运(ship)
```

1. **创建拣货波次**:`POST /warehouses/picking-waves`,选一个或多个已确认订单合并拣货
2. **开始/完成拣货**:`/{wave_id}/start` → `/{wave_id}/complete`
3. **打包**:`POST /warehouses/packing`,记录箱数、打包人。波次必须已完成（未完成 422）;箱数 ≥1 的整数;波次用 `picking_wave_id` 或 `wave_id` 都行
4. **创建发货单**:`POST /warehouses/shipments`,填承运商、运单号。`order_ids` 是**逐单成单**——列 5 个订单就出 5 条发货单，每条有唯一发货单号 `shipment_no`;订单必须真实存在（不存在 404）
5. **标记已发货**:`POST /shipments/{id}/ship` → 触发 TMS 运输流。body 可空（沿用单上已有运单号/承运商）;**已发货或已取消的单再点会被 422 拒绝**，不会重复记一次交接

### 4.4 库存调整与盘点

| 操作 | 说明 |
|------|------|
| `inventory/adjust` | 单个 SKU 出入库调整（正数入、负数出），需填原因和关联单号 |
| `adjust-stock-count` | 盘点录入：实际清点数量 vs 系统数量，自动算差异 |
| `/routes/stock` 的 stock-in / stock-out / adjust-stock | 入库单/出库单/调拨调整单据流 |

**盘点节奏建议**:日常循环盘点（高价值 A 类周盘）+ 季度全盘。

### 4.5 调拨与供应商结算

- **调拨**:`POST /warehouses/transfers`,A 仓 → B 仓移货
- **发票**:`POST /invoices`、**红冲**:`POST /credit-memos`,与采购单配对做应付结算

### 4.6 仓管员每日检查清单

- [ ] 处理当日 `confirmed` 订单，生成拣货波次
- [ ] 核对低库存预警（`/analytics/low-stock`），触发补货/采购
- [ ] 完成到货收货上架
- [ ] 盘点差异单跟进处理

---

## 五、运输调度员（TMS）作业流程

### 5.1 运输状态机

```
draft ──发车──→ dispatched ──取件完成──→ pickup_completed
                            │
                            └──在途──→ in_transit ──派件中──→ out_for_delivery ──送达──→ delivered
                                                              │
                                                            exception（异常）/ cancelled
```

| 状态 | 含义 |
|------|------|
| `draft` | 运单草稿 |
| `dispatched` / `pickup_completed` | 已发车 / 承运已取件 |
| `in_transit` | 运输途中 |
| `out_for_delivery` | 最后一程派件中 |
| `delivered` | 已送达（终态） |
| `exception` | 出现异常（延误/破损/丢失） |

### 5.2 创建运单与签收（POD）

1. **创建运单**:`POST /transport-orders`,选承运商（SF Express 等）、收发地址、运费
2. **记录跟踪事件**:`POST /tracking-events` 或 `/{order_id}/tracking-events`,录入每个节点（取件/中转/派送）
3. **电子签收 POD**:`POST /{order_id}/pod`,记录签收人、签名方式（物理/电子）、送货照片

> POD 是运费结算和争议处理的法律凭证。

### 5.3 Hub-and-Spoke 路由规划

TMS 采用**轴辐式（Hub-and-Spoke）**网络，用 Dijkstra 算法自动规划最优路径：

```
创建枢纽 TransferHub → 建枢纽间连接 HubConnection(图边) → 生成 RoutePlan
```

- **枢纽**:`POST /transfer-hubs`,如"上海分拨中心",标注类型（只有 primary 主站 / secondary 副站 / cargo_station 货运站三个词，其他值 422）和容量；改资料用 `PATCH /transfer-hubs/{id}`,编码/名称/类型/城市/状态都会落库
- **枢纽连接**:`POST /hub-connections`,定义 A 枢纽→B 枢纽的距离/时效（这是路由图的边）
- **运输段**:`TransportSegment` 是计划中的有序路段；`CarrierRoute` 是承运商定价路线
- **生成计划**:`POST /transport-orders/{order_id}/route-plans?type=auto_gen`,算法基于图自动算最短/最快路径

> 若规划无结果：检查枢纽连接图是否连通（from/to 是否有边）。

### 5.4 运费计算

`POST /freight/calculate`:输入承运商、服务类型、重量(kg)、里程(km),按**阶梯费率 FreightTier** 自动算运费。
先通过 `/freight-tiers` 维护各承运商的计费档位。

### 5.5 异常与退货（逆向物流）

| 场景 | 操作 |
|------|------|
| 运输延误/破损/丢失 | `POST /exceptions` 上报 → `PATCH /exceptions/{id}/resolve` 处理（如安排补发） |
| 客户退货 | `POST /return-orders` 建退回单 → `PATCH /return-orders/{id}/status` 跟踪退回状态 |

### 5.6 运输员每日检查清单

- [ ] 核对当日发货运单是否已创建、承运商已取件
- [ ] 跟进在途异常，及时上报/处理
- [ ] 确认送达运单的 POD 签收凭证已上传
- [ ] 处理退回单进展

---

## 六、物流运单（Logistics）作业流程

面向**电子面单**打印场景（对接快递鸟 KDNDIAO，需要 `KDNIAO_EBUSINESS_ID` / `KDNIAO_API_KEY`）：

1. **创建电子运单**:`POST /logistics/waybill/create`,填收发件信息与内装物品
2. **查询/跟踪**:`GET /logistics/waybill/{tracking}` + `/{tracking}/track`（实时拉取快递轨迹）
3. **打印**:`/{tracking}/print`、**作废**:`/{tracking}/void`

> 电子运单号与 TMS 运单号可关联，用于面单打印与快递对账。

### 6.1 打印与转述客户之前，先看号码与轨迹的出处

`POST /logistics/waybill/create` 的响应带 `tracking_source`：

| `tracking_source` | 打印前要知道的事 |
|---|---|
| `kdniao` | 号码由快递鸟返回，快递系统里有这张面单，可正常打印交接 |
| `local_placeholder` | 未配置快递鸟凭据，号码是本机拼出来的，**快递侧没有这张面单**：打印出去就是贴一个查不到的号码，应先补配置 |

`GET /logistics/waybill/{tracking}/track` 的响应带 `source`：`kdniao` = 快递鸟答的；`mock` = 演示数据（行首写着【演示数据】，由运单号哈希得出，与真实快递无关）。
**未配置快递鸟凭据时该接口返回 501** —— 没有凭据就没有轨迹可读，向客户转述"派送中/已签收"之前先确认 `source` 不是 `mock`。
承运商接口调用失败返回 502「查单失败」，失败不会给你一条演示轨迹。

---

## 七、条码员（Barcode）作业流程

1. **生成条码**:`POST /barcode/generate`(EAN-13/UPC,自动计算校验位)
2. **验证 GTIN**:`POST /barcode/validate` — 输入一串数字，判断是否合法 EAN/UPC
3. **扫码入库/盘点**:`POST /barcode/scan` — PDA 扫码枪扫描录入
4. **批量生成**:`POST /barcode/excel/upload` — Excel 导入批量出条码
5. **标签模板**:`POST /barcode/templates` — 定义打印标签尺寸与字段（GTIN/名称/价格）

> EAN-13/UPC 校验位采用右向左迭代算法，确保生成的条码可被标准扫码枪识别。

---

## 八、PDA 现场作业（移动端）

仓管员用 PDA（Expo 移动端）在货架旁作业，**离线优先**:

```
扫码盘点 / 拣货 / 入库 → 本地入队(mutations) → 联网后 sync 同步到服务器
```

- **离线入队**:`POST /pda/mutations`,网络不可用先存本地
- **同步**:`POST /pda/sync`，返回 processed/succeeded/failed 计数
- **实时推送**:`ws://host/api/v1/pda/ws`,接收调度指令

> 仅 mutation（增删改）入队，纯查询不离线；4xx 业务错误不入队。

---

## 九、通知与监控

### 9.1 通知类型（自动触发）

| 事件 | 触发时机 |
|------|------|
| `order_created` | 新订单 |
| `order_status_change` | 订单状态变更 |
| `low_stock_alert` | 库存低于阈值 |
| `transport_status_change` | 运输状态变更 |
| `delivery_confirmed` | 签收确认 |
| `exception_occurred` | 异常发生 |

**渠道**:WebSocket（实时，默认）、Email、移动端 Push（需 Firebase）。各用户可在 `/notifications/preferences` 设置偏好。

### 9.2 健康检查（运维）

| 端点 | 用途 |
|------|------|
| `GET /health` | 存活探针 |
| `GET /api/v1/health` | 完整健康（DB + Redis + readiness） |
| `GET /api/v1/ready` | Kubernetes 就绪探针 |

---

## 十、系统管理员（Admin）作业流程

### 10.1 后台管理入口

浏览器访问 `/admin/`(Jinja2 服务端渲染页面),涵盖：

| 模块 | 路径 | 职责 |
|------|------|------|
| 仪表盘 | `/admin/` | 统计概览、库存预警 |
| 订单 | `/admin/orders` (+`/{id}`) | 列表/详情/状态变更 |
| 用户 | `/admin/users` | 增删改、启用/禁用 |
| 仓库 | `/admin/warehouses` | CRUD |
| 库存 | `/admin/inventory` | 查询 |
| 设备 | `/admin/devices` | PDA 设备 |
| 标签模板 | `/admin/templates` | 条码标签 |
| 运输单/路由/退货/异常 | `/admin/{transport-orders,route-plans,returns,exceptions}` | 查看 |
| 需求预测 | `/admin/forecast`、`/admin/ml/forecast` | ML 训练与查询 |
| 导入导出 | `/admin/import` + `/admin/export/*` | CSV 批量导入、各类数据导出 |
| Webhook | `/admin/webhooks` | 订阅配置 |

### 10.2 RBAC 权限模型

```
User ──N:M── Role ──N:M── Permission   （权限码格式：{resource}.{action}）
```

管理员通过 `/api/v1/auth/roles`、`/{role_id}/permissions`、`/users/{user_id}/roles` 配置角色与授权。常用权限码：`order.view/create`、`warehouse.manage`、`transport.manage`、`admin.user/manage`。

### 10.3 CSV 导入导出

- **导入**:`POST /admin/import/orders`（订单）、`/admin/import/inventory`（库存）
- **导出**:`GET /admin/export/{orders,inventory,transport-orders,returns,exceptions,route-plans,ml-forecast}`

---

## 十一、端到端演练：一个订单的旅程

以"上海客户下单，跨仓发货并送达"为例：

1. **接单**(订单员):Amazon 订单由「电商对接」页粘贴 SP-API 的 `Order` 对象导入 OMS（`POST /connectors/amazon/orders`，无自动拉取），状态 `pending`
2. **确认**(订单员):审核 → `confirmed`;商品分占沪/苏两仓 → **拆单**
3. **拣货**(仓管员):为每个子单生成 picking-wave → 拣货 → 打包
4. **发货**(仓管员):创建 shipment，填顺丰运单号 → `ship`
5. **运输**(调度员):TMS 建 transport-order，Dijkstra 规划沪→京路由（经枢纽中转）
6. **追踪**:途中录入 transit 事件；客户可在前端查看轨迹
7. **签收**(调度员):送达 → POD 电子签收（含照片）
8. **售后**:若破损 → 上报 exception + 建 return-order 逆向退货
9. **结算**:采购侧发票/invoice、红冲/credit-memo 对账

---

## 十二、常见问题速查

| 现象 | 排查方向 |
|------|---------|
| 订单状态无法流转 | 检查当前状态是否允许该操作（见各状态机表） |
| Dijkstra 路由无结果 | 枢纽连接图不连通，补 `hub-connections` 边 |
| PDA 同步失败数 > 0 | 查看 sync 返回的 failed 明细，多为业务校验错误（4xx） |
| 条码扫码枪不识别 | GTIN 校验位算法需右向左迭代，用 `/barcode/validate` 复核 |
| 通知未收到 | 检查用户 notification preferences 与 WebSocket 连接 |
| 登录 401 | 用户名/密码、is_active、密码长度（≥8） |
| 请求 429 | 超过限流（默认 100 次/60s），或设 `TESTING=true` |

---

## 附录：岗位—模块对照表

| 岗位 | 核心系统 | 关键操作 |
|------|---------|---------|
| 订单员 | OMS | 接单确认、拆单合并、状态流转 |
| 仓管员 | WMS | 库位管理、入库/出库、盘点、拣货波次、发货 |
| 运输调度员 | TMS + Logistics | 运单、路由规划、追踪、POD 签收、异常退货 |
| 条码员 | Barcode | 生成/验证/扫码/批量出码、标签模板 |
| PDA 作业员 | PDA | 离线盘点/拣货、扫码入队同步 |
| 系统管理员 | Admin + Auth | 用户角色、数据导入导出、预测训练、Webhook |
