# MVP 开发任务清单 — oms-wms-tms

**目标**: 完成电子面单 + 打单发货，达到可交付给真实客户的最小可用产品。  
**预计周期**: 3-4 周（单人） / 1.5-2 月（2 人并行）。

---

## Phase 6 — 生产加固（Week 1-2）

### 6.1 基础设施降级
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 6.1.1 | Redis 降级为内存缓存 | `src/cache/redis_client.py` | 无 Redis 时回退到 `dict`，避免依赖外部服务 |
| 6.1.2 | Outbox 定时轮询派发 | `src/core/outbox.py` + `src/tasks/outbox.py` | 用 DB 表存储待发消息，Celery 定时任务轮询 HTTP 派发 |
| 6.1.3 | PostgreSQL → SQLite（开发模式） | `src/core/database.py` + `docker-compose.dev.yml` | 开发/演示时可免安装数据库 |

### 6.2 统一错误处理
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 6.2.1 | 前端全覆盖（搜索 `catch {`） | `InventoryList.vue`, `AddressList.vue`, `ImportCsv.vue` 等 | 替换为 `ElMessage.error(...)` + 日志输出 |
| 6.2.2 | 后端全覆盖（搜索 `except:`） | `routes/stock.py`, `wms/service.py` 等 | 统一用 `NotFoundException` / `HTTPException(404, ...)` |

### 6.3 库存 UI 补全
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 6.3.1 | 入库页面（采购入库 + 手动入库） | `frontend/src/views/stock/StockIn.vue`（新建） | 表单弹窗 + 预览 + API 调用 |
| 6.3.2 | 出库页面（销售出库 + 调拨出库） | `frontend/src/views/stock/StockOut.vue`（新建） | 同上 |
| 6.3.3 | 库存调整页面（盘盈/盘亏） | `frontend/src/views/stock/AdjustStock.vue`（新建） | 输入数量变化 + 原因选择 |
| 6.3.4 | 注册路由 | `router/index.ts` | 添加 `/stock/in`, `/stock/out`, `/stock/adjust` 三条路由 |

### 6.4 Amazon/Shopify 配置页面
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 6.4.1 | Amazon Config 页（Access Key / Secret / Marketplaces） | `frontend/src/views/connectors/AmazonConfig.vue`（新建） | 表单 + 保存 + 状态显示 |
| 6.4.2 | Shopify Config 页（Shop URL / API Token） | `frontend/src/views/connectors/ShopifyConfig.vue`（新建） | 同上 |
| 6.4.3 | 注册路由 | `router/index.ts` | `/connectors/amazon-config`, `/connectors/shopify-config` |

### 6.5 前端 chunk 优化
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 6.5.1 | 按需导入 Element Plus | `vite.config.ts` + `unplugin-element-plus` | 确保 main chunk < 300KB |

---

## Phase 7 — 电子面单（Week 3-4）

### 7.1 快递鸟 SDK
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 7.1.1 | 下单接口封装 | `src/logistics/kdniao.py`（新建） | 电子面单 API：`create_waybill`, `get_tracking_number` |
| 7.1.2 | 查单接口封装 | `src/logistics/kdniao.py` | `query_tracking` |
| 7.1.3 | 打印回调处理 | `src/logistics/kdniao.py` | `print_callback_url`（快递鸟提供） |

### 7.2 电子面单路由
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 7.2.1 | POST /logistics/waybill/create | `src/logistics/router.py`（新建） | 下单并返回面单号 + 打印 URL |
| 7.2.2 | GET /logistics/{tracking}/track | `src/logistics/router.py` | 查单 |
| 7.2.3 | POST /logistics/{tracking}/print | `src/logistics/router.py` | 调用快递鸟打印回调 |

### 7.3 前端打单页面
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 7.3.1 | 面单预览 + 打印 | `frontend/src/views/transport/WaybillPrint.vue`（新建） | 调用快递鸟回调 URL，浏览器打印 |
| 7.3.2 | 批量打单 | `frontend/src/views/transport/BatchPrint.vue`（新建） | 选中运单 → 批量下单 → 批量打印 |

### 7.4 面单模板管理
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 7.4.1 | 模板 CRUD | `frontend/src/views/barcode/LabelTemplates.vue`（完善） | 按快递公司管理模板，支持上传 PDF/TIFF |

### 7.5 运费试算（可选 MVP 范围外，但建议包含）
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| 7.5.1 | 前端运费试算 UI | `frontend/src/views/transport/FreightQuote.vue`（新建） | 发货地→目的地→重量 → 实时报价 |

---

## 测试清单

### 单元测试
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| T1 | Kdniao 下单接口 | `tests/test_kdniao.py`（新建） | mock 快递鸟 API，验证返回结构 |
| T2 | 路由集成测试 | `tests/test_logistics_router.py`（新建） | FastAPI TestClient 调用 `/logistics/waybill/create` |

### E2E 测试（Playwright）
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| T3 | 下单→打印流程 | `tests/test_e2e/test_waybill_flow.py`（新建） | 登录 → 创建运单 → 调用打单接口 → 浏览器打印预览 |

### 前端组件测试
| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| T4 | WaybillPrint.vue 渲染 | `frontend/src/views/transport/__tests__/WaybillPrint.test.ts`（新建） | 确保模板正确加载，打印按钮触发回调 URL |

---

## 文档更新

| # | 任务 | 文件 | 说明 |
|---|------|------|------|
| D1 | README.md — 新增电子面单章节 | `README.md` | 说明快递鸟 API Key 配置方式、打印流程 |
| D2 | docker-compose.yml — 添加环境变量示例 | `docker-compose.yml` | 增加 `KDNIAO_API_KEY` 等说明 |

---

## 验收标准（每个任务完成后需满足）

1. ✅ `pytest tests/` 新增用例全部通过（0 失败，0 skip）
2. ✅ Vue component linting (`vue-tsc --noEmit`) 无 error
3. ✅ API 接口文档同步更新（FastAPI Swagger UI）
4. ✅ Git commit message 遵循 Conventional Commits 格式

---

## 硬件 & 服务成本估算

| 项目 | 方案 | 月费/年费 |
|------|------|----------|
| 服务器 | 4C8G 云服务器（阿里云/腾讯云） | ~300 元/月 |
| 快递鸟 | 电子面单 + 物流查询 | ~2000 元/年 |
| **合计** | | **~500 元/月** |

适合日均 200-2000 单的中小型物流/电商企业。

---

## 建议启动顺序

```
Week 1-2: Phase 6（加固）+ Phase 11（部署）
               ↓
Week 3-4: Phase 7（电子面单）← 这是 MVP 核心
```

做完 Phase 7 即可达到 **最小可用产品（MVP）** 状态，可以在一家真实客户试用。
