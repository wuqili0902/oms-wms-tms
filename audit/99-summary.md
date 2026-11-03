# 99 整体完成度评估(汇总)

| 项 | 值 |
|----|----|
| 生成日期 | 2026-10-20 |
| 输入 | `audit/` 下全部 `.md`:`00-index.md`(8678 B,结构索引,自述"**未读取任何源码内容**")、`01-auth.md`(本次补写,逐行深审) |
| 补充取证 | 跨模块 grep 计数、桩/TODO 扫描、CI 步骤读取、实测跑测(见 §5) |
| 代码改动 | **无** |

> **先说边界(重要)**
> 1. 上一轮任务要求产出 `audit/01-auth.md`,但当时**并未落盘**(`audit/` 只剩 `00-index.md`)。本轮已按已验证证据补写完成,故本汇总的"深审"部分才成立。
> 2. 因此本文件是:**1 个模块逐行深审(auth)+ 20 个模块证据级初判**。初判判据见 §1,它不等于逐行审计 —— 表中"深度"列显式标注每行的证据强度。
> 3. `00-index.md` 是结构清单(文件数/目录/语言分布),它**不提供功能完成度信息**;所有完成度判断均来自源码取证或实测,不来自该索引。

---

## 1. 三档判据(本文件的客观标准)

| 档位 | 判据(全部满足才算"已实现") |
|------|------------------------------|
| **已实现** | 模块文件齐备 + 已在 `src/main.py:186-201` 挂载 + 存在对应测试文件 + 未发现桩实现/伪造返回/`TODO` 标记 + 未发现"对外呈现成功但实际未执行"的路径 |
| **部分实现** | 主链路可用,但存在以下任一:① 降级/未配置时静默返回伪成功;② 能力矩阵有明确缺口;③ 鉴权/RBAC/限流覆盖不完整;④ 状态不持久 |
| **未实现** | 代码本体是桩/伪造返回(`TODO` 明示"Replace with real …"),或该能力无代码(无 service 函数、无端点、无字段) |

深度标注:**深审** = 逐行读源码 + 实测;**浅证** = 文件齐备性 + 端点/守卫计数 + 桩扫描 + 测试文件存在性,**未逐行验证业务正确性**。

---

## 2. 已实现

| 模块 | 深度 | 证据文件 | 关键证据(file:line) |
|------|------|----------|----------------------|
| `src/auth`(认证主链路) | **深审** | `audit/01-auth.md` §0-§2、`src/auth/{router,service,schemas,models,token_store}.py` | 17 端点 `src/auth/router.py:48-269`;注册→登录→me→refresh→logout `router.py:48-96`;refresh 原子轮转 `src/auth/token_store.py:34-61`;实测 192 passed(§5) |
| `src/oms` | 浅证 | `src/oms/{router,service,schemas,models,merge}.py`;`tests/test_oms_router.py`、`tests/test_oms_extended.py`、`tests/test_oms_merge.py`、`tests/test_oms/test_oms.py`、`tests/test_oms/test_oms_service.py` | 9/9 端点带鉴权守卫(`src/oms/router.py:20` 起,守卫计数 9);split/merge 有独立测试 |
| `src/wms` | 浅证 | `src/wms/{router,service,schemas,models,analysis}.py`、`src/wms/services/picking_service.py`;`tests/test_wms/`(7 文件)、`tests/test_picking_service.py` | 41/41 端点守卫(`src/wms/router.py:43` + 守卫行 41) |
| `src/barcode` | 浅证 | `src/barcode/{router,service,models,schemas,excel_barcode}.py`;`tests/test_barcode_router.py`、`tests/test_barcode_service.py`、`tests/test_barcode/test_barcode.py` | 8/8 端点守卫;校验位算法近期已修(commit `3d7db79`) |
| `src/notification` | 浅证 | `src/notification/{router,service,models,schemas,email,ws}.py`;`tests/test_notification_{router,service,email,ws}.py`、`tests/test_notifications.py` | 真 SMTP 发送 `src/notification/email.py:6,44-51`(`aiosmtplib`);WebSocket 端点 `src/notification/router.py:142`;5/5 端点守卫 |
| `src/webhooks` | 浅证 | `src/webhooks/{router,service,models}.py`;`tests/test_webhooks{,_router,_service}.py` | 4/4 端点守卫 `src/webhooks/router.py:16` |
| `src/pda` | 浅证 | `src/pda/{router,service,models,ws}.py`;`tests/test_pda_service.py`、`tests/test_pda_extra.py`、`tests/test_pda_ws.py` | 3/3 端点守卫 + WS `src/pda/router.py:93` |
| `src/analytics` | 浅证 | `src/analytics/{router,service}.py`;`tests/test_analytics{,_router,_service}.py` | 路由级登录门 `src/analytics/router.py:20`;零值静默问题已修(commit `f1279a6`) |
| `src/stock` + `src/routes` | 浅证 | `src/stock/router.py`(再导出壳)、`src/routes/stock.py`;`tests/test_stock.py` | 11 端点统一登录门 `src/routes/stock.py:22` |
| `src/cache` | 浅证 | `src/cache/{redis_client,decorators}.py`;`tests/test_cache.py`、`tests/test_redis_client.py`、`tests/test_decorators.py` | RedisClient + 内存 fallback;`decorators.py:58` 独立限流工具 |
| `src/core`(平台层 20 文件) | 浅证 | `src/core/{database,middleware,csrf,outbox,offline,pagination,response,exceptions,security,tracing,export,import_utils,models,dependencies}.py`、`src/core/_import/`;`tests/test_core_*`、`tests/test_pagination*.py`、`tests/test_export*.py`、`tests/test_import_utils.py`、`tests/test_tracing.py`、`tests/test_outbox.py` | Shopify HMAC 校验范式 `src/connectors/shopify_webhook.py:17-20`(复用 `hmac.compare_digest`);`src/core/_import/routes.py` 2 端点已挂载(`src/main.py:196`) |
| `src/models` | 浅证 | `src/models/{base,wms,wms_enum,shared_models,erp_connector}.py`;`tests/test_models/test_orm_models.py`、`tests/test_core_models.py`、`tests/test_core/test_core_models.py` | 迁移链与模型一致(auth 部分已逐行核对:`audit/01-auth.md` §4) |
| `src/api`(health + mobile 门面) | 浅证 | `src/api/v1/{health,mobile}.py`;`tests/test_health.py`、`tests/test_health_extra.py`、`tests/test_mobile.py` | 探针端点 `src/main.py` 根 `/health` + `src/api/v1/health.py`(2);mobile 3 端点全守卫 `src/api/v1/mobile.py:17` |
| `src/tasks` + Celery | 浅证 | `src/celery_app.py`、`src/celeryconf.py`、`src/tasks/{base,inventory,maintenance,orders,outbox,sync}.py`;`tests/test_tasks.py`、`tests/test_tasks_inventory.py`、`tests/test_tasks_maintenance.py`、`tests/test_celery_app.py` | 6 个任务模块 + beat 计划;⚠️ 文档陈旧:`src/tasks/__init__.py:9` 引用不存在的 `example.py` |
| `alembic` | 浅证 | `alembic.ini`、`alembic/env.py`、`alembic/versions/`(11) | CI 对**全新 PG 服务**跑 `alembic upgrade head`(`.github/workflows/ci.yml:58-63`);auth 表/索引逐行核对一致(`audit/01-auth.md` §4) |
| `deploy/`(Helm + prod compose) | 浅证 | `deploy/helm/tms/`(Chart/values/templates 9)、`deploy/docker-compose.prod.yml`、`deploy/scripts/backup-db.sh` | CI run 6 全绿记录见 `AGENTS.md`(deploy 阶段);auth 相关缺口见 §4 待办 |
| `frontend/`(结构与集成骨架) | 浅证 | `frontend/src/{main.ts,App.vue,router/index.ts,api/index.ts,stores/auth.ts}`、`frontend/src/views/`(44) | 路由守卫 `frontend/src/router/index.ts:59-65`;401 自动刷新 + 并发单飞队列 `frontend/src/api/index.ts:11-12,27-68`;错误文本转义防 XSS `:70-75`;**11 个 vitest 用例文件**(见 §5)|
| `mobile/`(骨架与存储) | 浅证 | `mobile/App.js`、`mobile/app.json`、`mobile/src/screens/`(11)、`mobile/src/api/{client,cache}.js` | token 存 SecureStore `mobile/src/api/client.js:8,15-24`;离线入队限 mutation(`AGENTS.md` 记录) |

---

## 3. 部分实现

| 模块/能力 | 深度 | 缺什么 | 证据文件与行 |
|-----------|------|--------|--------------|
| `src/auth` 令牌生命周期 | **深审** | 无 `jti` → access token 不可撤销;刷新时不校验用户存在/`is_active` | `src/core/security.py:40-44,47-51`;`src/auth/service.py:99-113`;`src/core/dependencies.py:15-42` |
| `src/auth` RBAC 覆盖面 | **深审** | 引擎完备但仅 2/16 个 router 使用 `require_permission`;停用/降权对已签发 token 无效 | `src/auth/router.py` ×12、`src/admin/router.py` ×12、其余 12 个 router = 0(`audit/01-auth.md` §6 表) |
| `src/auth` 限流 | **深审** | 全仓仅 3 处 `@rate_limit`,其中 1 处**因装饰器顺序失效**;限流 Redis 挂则 fail-open | `src/auth/router.py:49,63,72`;`src/core/rate_limiter.py:74-75`;无全局限流中间件(`src/main.py:99,108` 仅连接/关闭) |
| `src/admin` | 浅证 | 38 端点中 27 个为 HTML 响应;`GET /admin/users` 只要登录不要权限(与 REST 不一致);停用/删除用户不撤销其 refresh token | `src/admin/router.py:31,360-361` vs `src/auth/router.py:99-100`;`src/admin/router.py:188-204,207-221` |
| `src/tms` | 浅证 | 50 端点仅"是否登录"一道门(0 RBAC);未配置 SAP/EDI 时 `sync_transport_order` 返回 `uuid4` **伪装成 ERP 回执**;需求预测无持久化 | `src/tms/router.py:39`;`src/tms/connectors/erp.py:72,96`;`src/models/erp_connector.py:168,271`;`src/tms/ml/forecast.py:21,54`(进程内 `defaultdict` 单例) |
| `src/tms` 推送 | 浅证 | Firebase 未配置即静默跳过并计为失败 | `src/tms/push_service.py:46,114,148` |
| `src/logistics` | 浅证 | 模块本体 CRUD 真实,但**承运商真实对接未实现**(见 §4),且 `generate_tracking_number` 在两个文件里重复实现 | `src/logistics/carriers.py:74-97` 与 `src/logistics/kdniao.py:55-78`(近似重复) |
| `src/connectors` | 浅证 | Shopify 入站真实(含 HMAC 校验),Amazon 出站全为桩(见 §4);Amazon 两个入站端点入参为裸 `dict`(与 auth P2-5 同类)。注:该 router 唯一无 JWT 的端点是 Shopify webhook,**按设计**由 `X-Shopify-Hmac-Sha256` 验证,非鉴权漏洞 | `src/connectors/shopify_webhook.py:17-20,103`;`src/connectors/amazon_sp_api.py:118,138,158,176,195`;裸 dict `src/connectors/router.py:70,83`;webhook 端点 `src/connectors/router.py:39-45` |
| `src/barcode` 二维码输出 | 浅证 | 打印侧为 printer-dependent 占位 | `src/barcode/excel_barcode.py:180` |
| `frontend` 与后端的登出契约 | **深审** | 前端登出不带 body → 后端 422 被吞 → 服务端 refresh 永不撤销;token 存 localStorage | `frontend/src/stores/auth.ts:57` vs `src/auth/router.py:82`;`auth.ts:7-8` |
| `mobile` 会话维持 | 浅证 | 无 refresh 调用 → access 60 分钟硬过期须重登 | `mobile/src/api/client.js:147-154`(仅 login/register/me);有效期 `src/core/security.py:9` |
| CI 覆盖 | 浅证 | 后端 pytest 进 CI,**前端 vitest 与 Playwright 不进 CI** | `.github/workflows/ci.yml:17-19,58-63,70`(lint/迁移/测试)、`:87-88`(前端仅 `npm ci` + `npm run build`) |

---

## 4. 未实现

| 能力 | 深度 | 证据(file:line) | 影响 |
|------|------|-------------------|------|
| **Amazon SP-API 全部出站动作**(状态轮询、状态回同步、运单号上传、FBA 标记、库存同步) | 浅证 | `src/connectors/amazon_sp_api.py:118-126`(`# TODO: Replace with real SP-API call` + 固定返回 `"status": "Unshipped"`)、`:138-145`、`:158-165`(返回 `"status": "uploaded"`)、`:176-183`(`"fba_shipped"`)、`:195-202`(`"synced"`) | 5 个函数**恒返回伪造成功**;上游无法区分"已上传运单号"与"从未上传" |
| **承运商真实追踪**(快递鸟/顺丰/中通等) | 浅证 | `src/logistics/kdniao.py:97` 段落标题即自陈 `# ── API stubs (mock data for demo/testing)`;`:129-150` `query_tracking` 用 `sum(ord(c)) % 100` 的哈希桶决定"已揽收/运输中/派送中/已签收";面单号本地拼装 `src/logistics/carriers.py:74-97`、`src/logistics/kdniao.py:55-78` | 追踪状态为编造;真实履约链路不可用 |
| **用户自助能力**(改密/改邮箱/找回密码) | **深审** | `src/auth/service.py` 全文无 `update_user`/`change_password`;`src/auth/schemas.py` 无对应 schema;`src/auth/models.py:10-21` 无 `password_updated_at` | 管理员无法让用户换密;泄露口令无轮换手段 |
| **用户 REST CRUD**(详情/更新/删除)与 **权限改删** | **深审** | 无路由(`src/auth/router.py` 17 端点清单,`audit/01-auth.md` §2);`get_user_by_id`(`service.py:63`)存在但无端点消费;权限仅 `list:176`/`create:182` | 用户/权限数据不可维护(删除只有 Jinja 面板一条路 `src/admin/router.py:207-221`) |
| **RBAC 业务侧接入** | **深审** | `require_permission(` 全仓仅 `src/auth/router.py`(12)+ `src/admin/router.py`(12);OMS/WMS/TMS/PDA/条码/库存/通知/运单等 190 端点为 0 | 所有业务端点只区分"登录/未登录",无最小权限 |
| **账号锁定 / 失败计数 / 登录审计** | **深审** | `src/auth/models.py:10-21` 无 `failed_login_count`/`locked_until`/`last_login` | 撞库无账号侧成本(叠加 `src/core/rate_limiter.py:157-160` 信任 XFF 可绕 IP 限流) |
| **生产可用的管理员口令引导** | **深审** | 硬编码 `admin123456` `src/auth/service.py:338`;`src/config.py`/`.env.example`/`deploy/.env.production.example`/`deploy/helm/tms/templates/secret.yaml`/`values.yaml` 对 `admin|seed` **零命中**;口令已写进文档 `docs/functional-test-plan.md:45,90` | 唯一进入管理员的路径是公开已知弱口令 |
| **移动端 token 刷新** | 浅证 | `mobile/src/api/client.js:147-154` 无 `/auth/refresh` | PDA 每 60 分钟强制重登 |
| **移动端测试** | 浅证 | `find mobile -name "*test*" -o -name "*spec*"` → **0 命中**(排除 node_modules) | 11 屏无任何自动化保障 |
| **E2E 进 CI** | 浅证 | `e2e/auth.spec.ts:20,41`、`e2e/business.spec.ts`、`e2e/playwright.config.ts` 存在;`.github/workflows/{ci,deploy}.yml` 无 playwright 步骤 | 关键旅程(注册→登录→首页)仅本地可跑 |
| **限流全局接入** | **深证(计数)** | 预置装饰器 `src/core/rate_limiter.py:196-198` 定义后无人使用;`src/main.py:99,108` 只做连接/关闭 | 约 168 个 REST 端点无任何速率限制 |
| 全局 MFA / SSO / 外部身份 | 浅证 | 全仓无相关代码 | 能力边界,非缺陷 |

---

## 5. 测试与 CI 实测数据

| 事实 | 证据 |
|------|------|
| 后端测试文件规模 | `tests/` 顶层 85 个 `.py` + 9 个子目录(`tests/auth` 5、`tests/test_tms` 7、`tests/test_wms` 7、`tests/test_core` 3、`tests/test_e2e` 3、`tests/test_admin` 2、`tests/test_models` 2、`tests/test_oms` 2、`tests/test_barcode` 1)+ `conftest.py` — 与 `00-index.md` §3 的 117 一致 |
| 本次实测(认证子集) | `192 passed / 0 failed / 62.78s`(`tests/auth` 5 文件 + `test_auth_guards` + `test_auth_router` + `test_auth_service` + `test_auth_supplementary` + `test_core_security` + `test_security` + `test_dependencies_extra`);另子集 `125 passed / 40.93s` |
| 全量套件 | 本次后台运行尚未产出结果(启动于 `pytest tests/ -q`),**数字待回填**;仓库最近记录为 `AGENTS.md`:**1704 passed / 0 failed / 10 skipped**(2026-08-02),以及 2026-08-13 的 CI 全线绿 |
| CI 步骤(lint) | `ruff check src/ tests/` + `mypy src/`(`ci.yml:17-19`);`AGENTS.md` 记录 ruff 现 "All checks passed!" |
| CI 步骤(迁移) | 全新 PG 上 `alembic upgrade head`(`ci.yml:58-63`) |
| CI 步骤(测试) | `pytest tests/ --cov=src`(`ci.yml:70`;`deploy.yml:68`) |
| CI 步骤(前端) | **仅** `npm ci` + `npm run build`(`ci.yml:87-88`)→ 无 `npm test`/vitest、无 Playwright |
| 前端测试实际数量 | **11** 个 vitest 文件:`frontend/src/__tests__/`(9)+ `frontend/src/views/transport/__tests__/`(2:`TransportOrderList.test.ts`、`WaybillPrint.test.ts`)→ **与 `00-index.md` §3 的"9 个"不符** |
| 移动端测试 | 0 个文件 |
| E2E 资产 | `e2e/auth.spec.ts`(注册→登录→首页 `:20`;未登录重定向 `:41-43`)、`e2e/business.spec.ts`、`e2e/init_db.py`、`e2e/playwright.config.ts`(含生成物 `test-results/`) |
| 桩/TODO 扫描(全后端) | `grep -rE "TODO|FIXME|XXX|HACK|NotImplementedError" src/ --include=*.py` → **仅 5 处命中,全部在 `src/connectors/amazon_sp_api.py`**(`:118,138,158,176,195`) |
| 前端占位扫描 | `grep -rE "TODO|FIXME|敬请期待|开发中|coming soon" frontend/src` → 0 命中(仅 `placeholder=` 表单属性) |
| 移动端占位扫描 | 0 命中 |

---

## 6. `00-index.md` 口径复核(索引自身的偏差,不影响代码)

| 索引声明 | 实测 | 证据 |
|----------|------|------|
| 净 484 文件、21 个 `src/` 子模块 | 与目录枚举一致 | `00-index.md` §1-§2;并已在 §10 自行纠正 `AGENTS.md` 的"19818 文件" |
| `src/auth/` 要点 = "router/service/models/schemas" | 漏 `token_store.py`(refresh 撤销核心) | `src/auth/token_store.py:34-61` |
| "约 188 REST + 2 WebSocket 端点" | 装饰器计数法得 **206 个 router 路由** = 约 168 REST JSON + 38 admin Web UI/导出(`src/admin/router.py`,其中 27 显式 HTMLResponse),另 `src/main.py` 内联根 `/health`+`/metrics`、WebSocket 2 处 | `src/main.py:186-201`;`audit/01-auth.md` §6;WS:`src/notification/router.py:142`、`src/pda/router.py:93` |
| `tests/auth/` 5 文件 | ✅ 5;但认证测试实际散布 **11 个文件** | §5 实测清单 |
| 前端 `__tests__/` 9 个 vitest | **11** | §5 |
| `mobile/src/screens/` 11 屏 | ✅(未逐屏读) | `AGENTS.md` mobile 补齐记录 |

---

## 7. 待办优先级(可直接交 opencode + 9B-Coder)

按"风险 × 改动量"排序;每条附证据入口:

1. **管理员口令可配置化 + 移除文档明文** — `src/auth/service.py:338`、`docs/functional-test-plan.md:45,90`(P1-1/P1-4)
2. **刷新/鉴权校验用户状态;停用与删除即撤销 token** — `src/auth/service.py:99-113`、`src/core/dependencies.py:15-42`、`src/admin/router.py:188-204,207-221`(P1-2)
3. **修 `/auth/refresh` 限流装饰器顺序 + 加 429 断言测试** — `src/auth/router.py:72-73`(P1-3)
4. **承运商追踪去 mock**(至少改为"未配置 → 显式失败",禁止编造状态) — `src/logistics/kdniao.py:97,129-150`
5. **Amazon SP-API 桩改为显式未实现**(抛 `NotImplementedError` 或返回带 `implemented: false` 的结果),禁止伪造 `uploaded/fba_shipped/synced` — `src/connectors/amazon_sp_api.py:118-202`
6. **ERP 未配置时不得返回伪回执 ID** — `src/tms/connectors/erp.py:72,96`、`src/models/erp_connector.py:168,271`
7. **限流:可信代理配置 + fail-open 改为可配置 + 全局挂载** — `src/core/rate_limiter.py:74-75,157-160,196-198`
8. **前端登出补 body(带 refresh_token)/后端 logout 兼容** — `frontend/src/stores/auth.ts:57` vs `src/auth/router.py:82`
9. **RBAC 业务侧接入**(先 OMS/WMS/库存/运单四类写操作) — `audit/01-auth.md` §6 覆盖面表
10. **移动端 refresh 与 401 重试** — `mobile/src/api/client.js:147-154`
11. **vitest + Playwright 进 CI** — `.github/workflows/ci.yml:87-88`
12. 其余 auth P2 清单(裸 dict 入参、toggle 分层、分页、bcrypt 72 字节、注册枚举、`_admin_seeded` 竞态) — `audit/01-auth.md` §9 P2 表

---

## 8. 建议的后续深审顺序

| 顺位 | 模块 | 理由 |
|------|------|------|
| 1 | `src/connectors` | 唯一含 `TODO` 桩的后端模块,且对外部系统(Amazon)产生虚假成功状态 |
| 2 | `src/logistics` | 追踪/面单为 mock,直接影响履约可信度;另有重复实现 |
| 3 | `src/tms` | 端点最多(50)、0 RBAC、ERP/预测/推送三处降级路径需逐行确认 |
| 4 | `src/wms` + `src/routes/stock` | 库存一致性主战场(最近 commit `f1279a6` 已修"零值误判") |
| 5 | `src/admin` ↔ `src/auth` 交叉面 | 两套 UI 的权限不对称(HTML 无权限要求 vs REST 有) |
| 6 | `src/core`(限流/中间件/outbox/offline) | 影响所有模块的横切能力 |
| 7 | `frontend` + `mobile` | 契约类缺陷(登出、刷新)只有端到端才能暴露 |

---

## 9. 数字面板

| 指标 | 值 | 来源 |
|------|----|------|
| 净源码文件 | 484(257 py / 49 vue / 33 ts / …) | `00-index.md` §0 |
| `src/` 子模块 | 21 | `00-index.md` §2 |
| 路由装饰器合计 | **206**(16 个已挂载 router,`src/main.py:186-201`)+ `src/main.py` 内联根 `/health`、`/metrics`;WebSocket 另 2 处 | `audit/01-auth.md` §6 计数表 |
| 其中 admin Web UI/导出端点 | 38(`src/admin/router.py`),内含 27 个显式 `response_class=HTMLResponse`、3 个 `StreamingResponse`(CSV) | `src/admin/router.py:31` 及装饰器计数 |
| 因此 REST JSON 端点 | 约 **168** | 206 − 38 |
| 使用 `require_permission` 的 router | **2 / 16** | 同上 |
| 使用 `@rate_limit` 的 router | **1 / 16**(3 处,1 处失效) | `src/auth/router.py:49,63,72` |
| 后端测试文件 | 117 | `tests/` 枚举 |
| 前端测试文件 | 11 | `frontend/src/**/__tests__/` |
| 移动端测试文件 | 0 | `find` 扫描 |
| 后端桩/TODO 命中 | 5(全在 `src/connectors/amazon_sp_api.py`) | grep 扫描 |
| 已深审模块 | 1(`src/auth`) | `audit/01-auth.md` |
| 认证子集实测 | 192 passed / 0 failed | 本次实测 |
| 全量套件 | 待回填(仓库记录 1704 passed,2026-08-02) | 后台运行中 / `AGENTS.md` |

**整体判断**:平台骨架(路由/分层/迁移/CI/测试规模)已实现且可用;**对外集成层(承运商追踪、Amazon SP-API、ERP 未配置路径)与访问控制纵深(RBAC 业务接入、令牌撤销、口令引导)是未完成的两大块**。前者决定"能不能真发货",后者决定"能不能上生产"。
