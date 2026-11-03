# 00 结构索引(模块划分清单)

- 生成方式:Glob + Grep + `find` 计数,**未读取任何源码内容**
- 生成日期:2026-10-20
- 统计口径:排除 `node_modules/`、`__pycache__/`、`dist/`、`coverage/`、`test-results/`、`.expo/`、`build/`、`.venv/`、`.git/`
- 净文件规模:**433**(目录)+ **51**(根目录)= **484**;语言分布:py 257 / vue 49 / ts 33 / md 26 / json 19 / html 19 / js 16 / yaml 11 / txt 11 / bat 9 / sh 5 / yml 4 / db 4

---

## 1. 顶层目录

| 目录 | 净文件数 | 主要类型 | 职责 |
|------|---------|---------|------|
| `src/` | 141 | py 116 + html 18 | 后端全部业务模块(FastAPI) |
| `tests/` | 117 | py 116 | 后端测试(含 pytest 子目录) |
| `frontend/` | 95 | vue 49 + ts 33 | Vue3 + TS 前端 SPA |
| `mobile/` | 20 | js 16 | React Native / Expo PDA 客户端 |
| `alembic/` | 14 | py 13 | 数据库迁移链(11 个 revision) |
| `deploy/` | 15 | yaml 10 + sh 1 | Helm Chart + 生产 compose + 备份脚本 |
| `docker/` | 5 | sh 3 + Dockerfile | 镜像与容器入口 |
| `e2e/` | 6 | ts 3 | Playwright 端到端测试 |
| `docs/` | 9 | md | 架构/功能/部署/运维/测试文档 |
| `dev/` | 8 | py 4 + txt 3 | 根目录调试脚本收纳区 |
| `.github/` | 3 | yml 2 + md | CI/CD 工作流 + PR 模板 |
| `logs/` | 12 | 生成物 | 运行日志(非源码) |
| `build/` | 14 | 生成物 | 构建产物(非源码) |

根目录文件:51 个(配置 8、脚本 15、文档 8、调试脚本/临时数据 20)。

---

## 2. `src/` 模块划分

| 子目录 | 文件数 | 内容要点 |
|--------|-------|---------|
| `src/oms/` | 6 | 订单:router/service/schemas/models/merge |
| `src/wms/` | 7 | 仓储:router/service/schemas/models/analysis + `services/picking_service.py` |
| `src/tms/` | 11 | 运输:router/service/schemas/models/push_service/seed + `connectors/erp.py` + `ml/forecast.py` |
| `src/pda/` | 5 | PDA:router/service/models/ws |
| `src/barcode/` | 6 | 条码:router/service/models/schemas/excel_barcode |
| `src/logistics/` | 7 | 运单与承运商:router/service/models/schemas/kdniao/carriers |
| `src/notification/` | 7 | 通知:router/service/models/schemas/email/ws |
| `src/connectors/` | 5 | Shopify/Amazon 入站:router/service/shopify_webhook/amazon_sp_api |
| `src/webhooks/` | 4 | 出站 Webhook:router/service/models |
| `src/analytics/` | 3 | 仪表盘与趋势:router/service |
| `src/admin/` | 20 | HTML 后台:router.py + `templates/admin/` 18 个 html |
| `src/auth/` | 6 | 认证/RBAC:router/service/models/schemas |
| `src/stock/` | 1 | 出入库 API 再导出壳(re-export `src/routes/stock.py`) |
| `src/routes/` | 1 | `stock.py`:出入库/库存流水/调整实现 |
| `src/core/` | 20 | 平台层:database/middleware/rate_limiter/csrf/outbox/offline/pagination/response/exceptions/security/tracing/export/import_utils/models/dependencies + `_import/`(import_orders, import_inventory, routes) |
| `src/cache/` | 3 | RedisClient + 缓存装饰器 |
| `src/models/` | 6 | 跨域模型:base/wms/wms_enum/shared_models/erp_connector |
| `src/api/` | 4 | `v1/health.py`、`v1/mobile.py` |
| `src/tasks/` | 7 | Celery 任务:base/inventory/maintenance/orders/outbox/sync |
| `src/` 根文件 | 7 | `main.py`、`config.py`、`celery_app.py`、`celeryconf.py`、`__init__.py`、coverage 产物 |
| `src/oms_wms_tms.egg-info/` | 5 | 打包元数据(生成物) |

---

## 3. `tests/` 测试目录

| 位置 | 文件数 |
|------|-------|
| `tests/`(顶层 .py) | 85 |
| `tests/test_tms/` | 7 |
| `tests/test_wms/` | 7 |
| `tests/auth/` | 5 |
| `tests/test_core/` | 3 |
| `tests/test_e2e/` | 3 |
| `tests/test_admin/` | 2 |
| `tests/test_models/` | 2 |
| `tests/test_oms/` | 2 |
| `tests/test_barcode/` | 1 |
| 合计 | 117(含 `conftest.py`) |

其他测试入口:`frontend/src/__tests__/`(9 个 vitest 用例)、`e2e/*.spec.ts`(Playwright)。

---

## 4. `frontend/` 结构

| 目录 | 文件数 |
|------|-------|
| `frontend/src/views/` | 44(15 个业务分组:orders/warehouses/stock/transport/tms/barcode/devices/connectors/notifications/pda/webhooks/admin/analytics + Dashboard/Login/NotFound) |
| `frontend/src/__tests__/` | 9 |
| `frontend/src/components/` | 6 |
| `frontend/src/composables/` | 4 |
| `frontend/src/stores/` | 3 |
| `frontend/src/api/` `types/` `utils/` `assets/` | 各 2 |
| `frontend/src/router/` `layouts/` `services/` | 各 1 |
| `frontend/src/` 根 | 3(`main.ts`、`App.vue`、`style.css`) |
| `frontend/public/` | 2 |
| `frontend/` 根 | 11(`package.json`、`package-lock.json`、`vite.config.ts`、`vitest.config.ts`、`tsconfig.json`/`app`/`node`、`index.html`、`.env.example`、`README.md`、`安装依赖`) |

---

## 5. `mobile/` 结构

- 入口:`App.js`、`app.json`、`babel.config.js`、`package.json`
- `src/screens/` 11 屏:Login / OrderList / OrderDetail / Scanner / ReceiveGoods / StockIn / Inventory / StockCount / Picking / PackingRecord / TransferOrder
- `src/api/`:`client.js`、`cache.js`;`src/navigation/AppNavigator.js`

---

## 6. 入口文件

| 用途 | 入口 |
|------|------|
| 后端 API | `src/main.py`(FastAPI app + 中间件 + 路由挂载)、启动命令 `uvicorn src.main:app` |
| Celery | `src/celery_app.py`(app)+ `src/celeryconf.py`(beat_schedule 11 项)+ `src/tasks/*` |
| 数据库迁移 | `alembic.ini` + `alembic/env.py` → `alembic/versions/`(11 个) |
| 前端 SPA | `frontend/index.html` → `frontend/src/main.ts` → `src/router/`;构建 `vite.config.ts`,测试 `vitest.config.ts` |
| 移动端 | `mobile/App.js` + `mobile/app.json`(Expo) |
| E2E | `e2e/playwright.config.ts` + `e2e/auth.spec.ts`、`e2e/business.spec.ts`、`e2e/init_db.py` |
| 容器 | `docker/Dockerfile`、`docker/scripts/entrypoint.sh`、`entrypoint-celery-worker.sh`、`entrypoint-celery-beat.sh`、`docker/nginx/default.conf` |
| 打包配置 | `pyproject.toml`(含 pytest/ruff 配置)、`.pre-commit-config.yaml` |

---

## 7. 构建 / 运行 / 部署脚本

| 类别 | 文件 |
|------|------|
| 构建 | `build.py`、`build.bat`、`frontend/package.json`(scripts)、`docker/Dockerfile` |
| 本地启动 | `dev-start.bat`、`native-start.bat`、`deployall.bat`、`.start-backend.cmd`、`.start-celery.cmd`、`.start-frontend.cmd` |
| 容器编排 | `docker-compose.yml`(开发)、`deploy/docker-compose.prod.yml`(生产) |
| 部署 | `deploy.ps1`、`deploy.sh`、`deploy/scripts/backup-db.sh` |
| CI | `.github/workflows/ci.yml`、`.github/workflows/deploy.yml`、`.github/PULL_REQUEST_TEMPLATE.md` |
| Helm | `deploy/helm/tms/`:Chart.yaml、values.yaml、templates/(deployment/service/ingress/hpa/secret/configmap/migration-job/backup-cronjob/`_helpers.tpl`) |
| 环境模板 | `.env.example`、`deploy/.env.production.example`、`frontend/.env.example` |
| 非构建脚本(工具启动) | `claude-lmstudio2.bat`、`claude-lmstudio22.bat`、`claude-lmstudio33.bat`、`claude-strata.bat`、`claude-deepseek-flash.bat` |

---

## 8. `docs/` 文档清单

`architecture.md`、`feature-summary.md`、`admin-manual.md`、`operations-manual.md`、`deployment-guide.md`、`functional-test-plan.md`、`manual-test-plan.md`、`plan-bugfix.md`、`fix-auditlog-bodybuffer-hang.md`

根目录另有:`README.md`、`AGENTS.md`、`MANUAL.md`、`OPERATIONS.md`、`COMPLETION_REPORT.md`、`单据流转图.md`、`补充开发修复计划.md`、`newtodo.md`、`wuqilitodo.md`

---

## 9. 生成物 / 临时物(建议 gitignore 或移入 `dev/`)

| 位置 | 文件数 | 说明 |
|------|-------|------|
| `frontend/node_modules/` | 28439 | 依赖 |
| `mobile/node_modules/` | 25522 | 依赖 |
| `e2e/node_modules/` | 191 | 依赖 |
| `frontend/dist/` | 71 | 前端构建产物 |
| `frontend/coverage/` | 28 | 前端覆盖率报告 |
| `build/` | 14 | 打包产物 |
| `logs/` | 12 | 运行日志 |
| `src/oms_wms_tms.egg-info/` | 5 | 打包元数据 |
| 根目录调试残留 | — | `_check_db.py`、`_check_db2.py`、`_debug_e2e.py`、`debug_register.py`、`fix_test_wms.py`、`smoke_test.py`、`server.log`、`server_err.log`、`C:server.log`、`NUL`、`login.json`、`dash.json`、`fix-redis-kwarg.txt`、`dev/pyright_out.txt`、`dev/ruff_remaining.txt`、`dev/temp_cov.txt` |
| 根目录 SQLite 库 | 4 | `data.db`、`wms_tms.db`、`wms_pda.db`、`e2e_test.db` |
| 命名问题 | — | `frontend/安装依赖`(无扩展名)、根目录 `NUL`、`C:server.log` |

---

## 10. 口径不一致提示

- `AGENTS.md` 声称「约 19818 文件、40+ 模块」:按本索引实测,排除依赖与生成物后为 **484 文件、21 个 `src/` 子模块**;19818 应是含依赖目录的旧统计。
- `docs/feature-summary.md` 的「~102 端点 / 207 测试」与代码现状不符(实测约 188 REST + 2 WebSocket 端点,117 个测试文件)。
