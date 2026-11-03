# 01 `src/auth` 模块完成度审计

| 项 | 值 |
|----|----|
| 审计日期 | 2026-10-20 |
| 审计依据 | `audit/00-index.md` §2(`src/auth/ \| 6 \| 认证/RBAC:router/service/models/schemas`)、§3(`tests/auth/ \| 5`)、§6 入口口径 |
| 方法 | 静态阅读(全模块逐行)+ 实测跑测(pytest)+ 最小复现脚本(装饰器语义)+ 跨模块 grep 取证 |
| 代码改动 | **无**(本文件为唯一产出,未修改任何 `.py`) |
| 复核命令 | `pytest tests/auth tests/test_auth_guards.py tests/test_auth_router.py tests/test_auth_service.py tests/test_auth_supplementary.py tests/test_core_security.py tests/test_security.py tests/test_dependencies_extra.py -q` → **192 passed / 0 failed / 62.78s** |

---

## 0. 结论速览

主链路(注册 → 登录 → 访问 → 刷新 → 登出 → RBAC 判定)**已实现且测试绿**;
但存在 **4 个必须修的 P1 缺陷** 与 **9 个 P2**,以及一组**能力缺口**(自助服务、业务侧 RBAC 接入)。

| 维度 | 判定 | 关键证据 |
|------|------|---------|
| 目录结构分层 | 已实现 | `src/auth/{__init__,models,schemas,service,router,token_store}.py` |
| 认证主链路 | 已实现 | `src/auth/router.py:48-96`、`src/auth/service.py:26-118` |
| 令牌生命周期 | 部分实现 | `src/core/security.py:40-51` 无 `jti` → access 不可撤销;`src/auth/service.py:99-113` 不校验用户状态 |
| RBAC 引擎 | 已实现 | `src/core/dependencies.py:88-140` |
| RBAC 业务接入 | **未实现(几乎为零)** | `require_permission` 仅出现在 2 个 router:`src/auth/router.py`(12 行)、`src/admin/router.py`(12 行),其余 12 个 router 全为 0 |
| 用户自助能力 | **未实现** | 全模块无 `update_user` / `delete_user` / `change_password` / 找回流程(见 §3 缺口表) |
| 测试 | 已实现(有盲区) | 192 passed;盲区见 §7 |
| 前端集成 | 部分实现 | `frontend/src/api/index.ts:27-68` 刷新单飞实现正确;但 `frontend/src/stores/auth.ts:57` 登出请求缺 body → 后端 422 |
| 移动端集成 | 部分实现 | `mobile/src/api/client.js:15-24` SecureStore 正确;`:147-154` 无 refresh → 60 分钟硬过期 |

---

## 1. 索引口径核对(00-index.md vs 实际)

| 索引声明 | 实际 | 证据 | 判定 |
|----------|------|------|------|
| `src/auth/` 6 文件 | 6 文件 | `__init__.py`(6 行)、`models.py`(76)、`router.py`(270)、`schemas.py`(74)、`service.py`(346)、`token_store.py`(129) | ✅ |
| 内容要点 = "router/service/models/schemas" | 遗漏 `token_store.py` | `src/auth/token_store.py` 是 refresh 撤销/轮转的核心(`:34-61`) | ⚠️ 计数对、清单漏核心文件 |
| 职责 = "认证/RBAC" | RBAC 引擎完备,业务侧未接入 | `require_permission` 使用点:`src/auth/router.py` ×12、`src/admin/router.py` ×12、定义 `src/core/dependencies.py:113` | ⚠️ 口径成立但覆盖窄 |
| `tests/auth/` 5 文件 | 5 文件 | `test_auth.py`、`test_auth_service.py`、`test_models.py`、`test_models_unit.py`、`test_token_store.py` | ✅ |
| (索引未提)认证测试实际分布 | 11 个测试文件、两处目录 | 另:`tests/test_auth_guards.py`、`tests/test_auth_router.py`、`tests/test_auth_service.py`、`tests/test_auth_supplementary.py`、`tests/test_core_security.py`、`tests/test_security.py`、`tests/test_core_csrf.py`、`tests/test_csrf.py`、`tests/test_rate_limiter.py`、`tests/test_dependencies_extra.py` | ⚠️ 索引口径不完整 |
| 测试重复 | 存在重叠 | `tests/auth/test_models.py`(12 用例)与 `tests/auth/test_models_unit.py`(10 用例)同源;`tests/auth/test_auth_service.py`(35)与 `tests/test_auth_service.py`(3)同源 | ⚠️ |
| `e2e/auth.spec.ts` 存在 | 存在 | `e2e/auth.spec.ts:20`(注册→登录→首页)、`:41-43`(未登录重定向) | ✅ 但**未进 CI**(`.github/workflows/ci.yml` 无 playwright 步骤,前端 job 仅 `npm ci` + `npm run build`,`:87-88`) |

---

## 2. 端点清单核对(17 个,逐个证据)

前缀:`/api/v1`(`src/main.py:187`)+ `/auth`(`src/auth/router.py:27`)。

| # | 端点 | 证据行 | 鉴权 | response_model | 限流 | 判定 |
|---|------|--------|------|----------------|------|------|
| 1 | `POST /auth/register` | `router.py:48-59` | 公开 | `UserResponse` | 3/3600s `:49` ✅生效 | 部分(见 P1-4/P2-2) |
| 2 | `POST /auth/login` | `:62-69` | 公开 | `TokenResponse` | 5/60s `:63` ✅生效 | 已实现 |
| 3 | `POST /auth/refresh` | `:72-78` | 公开 | `TokenResponse` | 10/60s `:72` ❌**不生效** | 缺陷(见 P1-3) |
| 4 | `POST /auth/logout` | `:81-84` | 公开(无鉴权、无限流) | `MessageResponse` | 无 | 部分 |
| 5 | `GET /auth/me` | `:87-96` | `get_current_user` | `UserResponse` | 无 | 已实现 |
| 6 | `GET /auth/users` | `:99-106` | `admin.rbac.manage` `:100` | `list[UserResponse]` | 无 | 部分(无分页,见 P2-8) |
| 7 | `POST /auth/roles` | `:109-120` | `admin.rbac.manage` `:110` | `RoleResponse`/201 | 无 | 已实现 |
| 8 | `GET /auth/roles` | `:123-130` | 同上 `:124` | `list[RoleResponse]` | 无 | 已实现 |
| 9 | `GET /auth/permissions` | `:133-140` | 同上 `:134` | `list[PermissionResponse]` | 无 | 已实现 |
| 10 | `PUT /auth/roles/{role_id}` | `:143-155` | 同上 `:144` | `RoleResponse` | 无 | 已实现 |
| 11 | `DELETE /auth/roles/{role_id}` | `:158-169` | 同上 `:159` | 204 | 无 | 已实现(系统角色保护 `service.py:168`) |
| 12 | `POST /auth/permissions` | `:172-183` | 同上 `:173` | `PermissionResponse`/201 | 无 | 已实现 |
| 13 | `POST /auth/users/{uid}/roles` | `:186-201` | 同上 `:189` | `UserRoleResponse` | 无 | 部分(入参裸 `dict` `:192`,见 P2-5) |
| 14 | `DELETE /auth/users/{uid}/roles/{rid}` | `:204-216` | 同上 `:206` | 204 | 无 | 已实现 |
| 15 | `POST /auth/roles/{rid}/permissions` | `:219-234` | 同上 `:222` | `RolePermissionResponse` | 无 | 部分(裸 `dict` `:225`) |
| 16 | `DELETE /auth/roles/{rid}/permissions/{pid}` | `:237-249` | 同上 `:239` | 204 | 无 | 已实现 |
| 17 | `POST /auth/users/{uid}/toggle` | `:252-269` | `admin.user.manage` `:255` | `ToggleActiveResponse` | 无 | 部分(分层违规 + 可自我停用,见 P2-6) |

**结构性缺失端点(无对应路由)**:`GET /auth/users/{uid}`、`PATCH /auth/users/{uid}`、`DELETE /auth/users/{uid}`、`PATCH/DELETE /auth/permissions/{pid}`、`GET /auth/users/{uid}/roles`、`GET /auth/roles/{rid}/permissions`、`POST /auth/change-password`、`POST /auth/forgot-password`。

其中 `GET /auth/users/{uid}` 的 service 已存在却无路由消费:`src/auth/service.py:63-69`(`get_user_by_id`)仅被测试引用(`tests/auth/test_auth_service.py:52,62`)。

---

## 3. Service 层能力矩阵

已实现 19 个函数(`src/auth/service.py`):

| 分组 | 函数:行 |
|------|---------|
| 用户 | `register_user:26`、`authenticate_user:52`、`get_user_by_id:63`、`get_user_by_username:72`、`list_users:79` |
| 令牌 | `create_tokens:87`、`refresh_tokens:99`、`revoke_refresh_token:116` |
| 角色 | `create_role:123`、`list_roles:141`、`update_role:147`、`delete_role:162` |
| 权限 | `list_permissions:176`、`create_permission:182` |
| 绑定 | `assign_role_to_user:204`、`remove_role_from_user:226`、`assign_permission_to_role:244`、`remove_permission_from_role:266` |
| 引导 | `_ensure_admin:294`(私有)、模块标志 `_admin_seeded:283` |

**缺失(未实现)**:

| 能力 | 状态 | 说明 |
|------|------|------|
| 改密码 / 改邮箱 | ❌ 无函数、无端点 | 全模块无 `update_user`/`change_password`;且 JWT 无版本声明(`src/core/security.py:40-51`)→ 即便补上也失效不了旧 token |
| 删除用户(REST) | ❌ | 仅 admin HTML 有:`src/admin/router.py:207-221` |
| 停用/删除后撤销 token | ❌ | `revoke_refresh_token` 全仓仅 1 处调用(`src/auth/router.py:83`);停用(`src/auth/router.py:267`)与删除(`src/admin/router.py:218`)均不调用 |
| 权限 update/delete | ❌ | service 仅 `list:176` / `create:182` |
| 用户角色 / 角色权限 查询 | ❌ | 无 `list_user_roles` / `list_role_permissions`,前端无法回显绑定关系 |
| 账号锁定 / 登录失败计数 | ❌ | `src/auth/models.py:10-21` 无 `failed_login_count` / `locked_until` / `last_login` 字段 |
| 登录审计字段 | ❌ | 模型无 `last_login`;未见登录失败落库 |

---

## 4. 数据模型与迁移一致性

| 模型 | 证据 | 迁移证据 | 判定 |
|------|------|----------|------|
| `User` | `models.py:10-21`(username `:16`、email `:17` 双 unique index、`hashed_password:18`、`is_active:19`) | `alembic/versions/eb47b7e1074b_full_schema.py:201` 建表,`:211-213` 建索引 | ✅ 一致 |
| `Role` | `:24-36`(`code:31` unique、`is_system:33`) | 同上 `:153`、`:163-164` | ✅ |
| `Permission` | `:39-51`(`code:46` unique、`resource:47`、`action:48`) | 同上 `:124`、`:135-136` | ✅ |
| `UserRole` | `:54-63`(复合主键 `:58-63` + `uq_user_role:56`) | 建表 `:353` + FK CASCADE `:356-357`;约束补建 `26f0642a5601:198` | ✅(约束冗余,见下) |
| `RolePermission` | `:66-75`(复合主键 `:70-75` + `uq_role_permission:68`) | 建表 `:318` + FK `:321-322`;约束补建 `26f0642a5601:185` | ✅(同上) |

- **冗余提示**:`uq_user_role` / `uq_role_permission` 与复合主键(`models.py:58-63,70-75`)语义重复;且补建走 `_best_effort`(`26f0642a5601:185,198`)会吞掉失败,回滚侧同样 best_effort(`:217,232`)。功能无碍,属噪音。
- **缺失字段**:`last_login`、`failed_login_count`、`locked_until`、`password_updated_at`、`is_superuser`。

---

## 5. 令牌生命周期

| 环节 | 参数/机制 | 证据 | 判定 |
|------|-----------|------|------|
| 算法 | HS256 | `src/core/security.py:8` | ✅ |
| access 有效期 | 60 min | `:9` + `:40-44` | ✅ |
| refresh 有效期 | 7 天 | `:10` + `:47-51` | ✅ |
| 声明校验 | 强制 `exp/iss/aud`,iss/aud = `app_name` | `:60-67` | ✅ 良好(拒外部签发) |
| 口令散列 | bcrypt + `gensalt()`;经 `asyncio.to_thread` 避免阻塞事件循环 | `:23-27`、`:30-37` | ✅ |
| refresh 轮转 | 先 decode 再原子 pop(Lua `GET`+`DEL` 防 TOCTOU)→ 签发新对 | `src/auth/service.py:99-113`、`src/auth/token_store.py:34-61`(`:46-52` Lua) | ✅ 设计正确 |
| 存储 TTL 对齐 | `REFRESH_TOKEN_TTL = 7d` == `REFRESH_TOKEN_EXPIRE_DAYS` | `token_store.py:18` vs `security.py:10` | ✅ |
| 存储键 | `rt:` + sha256(token)[:16],不落明文 JWT | `token_store.py:99-101` | ✅(16 hex 截断 = 64 bit,碰撞风险可忽略但可留全长) |
| access 撤销 | ❌ 无 `jti`/黑名单 | `security.py:40-44,47-51` 无 `jti`;登出仅撤 refresh(`router.py:81-84`) | ❌ 登出后 access 仍可用至 60 min |
| 刷新时用户状态校验 | ❌ 不查库 | `service.py:99-113` 全程无 `User` 查询;`router.py:74-78` 直通 | ❌ 见 P1-2 |
| Redis 降级 | 失败即永久切内存(`_redis_ok` 无恢复路径) | `token_store.py:30,58,69,81,92` | ⚠️ 进程生命周期内不可逆 |
| 内存回退语义 | 每进程独立 dict、无 TTL、无容量上限 | `token_store.py:29,94` | ⚠️ 多 worker 部署下 A 签发的 refresh 在 B 进程不可用 |

---

## 6. RBAC 执行面

**引擎**(已实现):
- `require_permission` 工厂:`src/core/dependencies.py:113-140`;空权限直接 403(`:124-125`);多权限为 AND 语义(`:131-137`)。
- 权限解析:`_get_user_permissions:88-110`(`selectinload` 两层预载 `:98-101`),用户不存在/无角色 → 空集合(`:102-104`)。
- 引导权限码 4 个:`service.py:286-291`(`admin.rbac.manage`、`admin.user.manage`、`admin.webhook.manage`、`admin.export.manage`)。
- 与代码实际用码一致:全仓 `require_permission("…")` 只出现这 4 个码,**无"要求了却从未播种"的码** → 一致性 ✅。

**覆盖面**(RBAC 引擎基本没接到业务上):

| router | 端点数 | 端点级 guard 行 | 路由级 `dependencies=[Depends(get_current_user)]` | `require_permission` 行数 |
|--------|-------:|----------------:|---:|--------------------------:|
| `src/auth/router.py:27` | 17 | 12 perm + 5 auth | 无(`:27` 无路由级依赖) | 12 |
| `src/admin/router.py` | 38(HTML 页) | 11 | 是(`:31`) | 12 |
| `src/wms/router.py:43` | 41 | 41 | 无 | 0 |
| `src/tms/router.py:39` | 50 | 1 | 是(`:39`) | 0 |
| `src/oms/router.py:20` | 9 | 9 | 无 | 0 |
| `src/routes/stock.py:22` | 11 | 1 | 是(`:22`) | 0 |
| `src/barcode/router.py:25` | 8 | 8 | 无 | 0 |
| `src/logistics/router.py:29` | 6 | 6 | 无 | 0 |
| `src/notification/router.py:26` | 5 | 5 | 无 | 0 |
| `src/webhooks/router.py:16` | 4 | 4 | 无 | 0 |
| `src/analytics/router.py:20` | 4 | 1 | 是(`:20`) | 0 |
| `src/pda/router.py:13` | 3 | 3 | 无 | 0 |
| `src/api/v1/mobile.py:17` | 3 | 3 | 无 | 0 |
| `src/connectors/router.py:20` | 3 | 2 | 无 | 0 |
| 合计 | 192 | — | 4 个 router 有路由级登录门 | **仅 2 个 router 有细粒度授权** |

计数口径:`@router.<method>(` 装饰器计数 + `Depends(get_current_user|require_permission|…)` 行计数(路由级依赖单列),与 `00-index.md` §10 的 "约 188 REST + 2 WebSocket" 口径不同(本计数含 admin 38 个 HTML 页;若剔除,REST 约 168;WebSocket 2 个:`src/notification/router.py:142`、`src/pda/router.py:93`)。

**RBAC 一致性缺口**:同一份用户数据,REST 需权限、HTML 不需:
- `GET /api/v1/auth/users` 需 `admin.rbac.manage`(`src/auth/router.py:99-100`);
- `GET /admin/users` 仅需已登录(`src/admin/router.py:31` 路由级 + `:360-361` 该端点无 permission),返回全量用户邮箱(脱敏仅限 `hashed_password`,`:367-370`)。

**认证判定缺口**:`get_current_user`(`src/core/dependencies.py:15-42`)**只解码 JWT,不查库**;对比 `require_permission` 每次查库(`:131`)。→ 停用/降权对**已签发的 access token** 无效(60 分钟窗口内),对 refresh 也无效(见 P1-2)。另有 `get_optional_current_user:45-62`(匿名返回 `{}`)与 `get_required_current_user:65-85` 两变体并存,`auto_error=False` 与显式 401 逻辑重复。

---

## 7. 测试证据(实测)

| 测试文件 | 用例数 | 覆盖点 |
|----------|-------:|--------|
| `tests/auth/test_auth.py` | 19 | 端点级:注册 `:31-51`、登录 `:53-74`、me `:76-92`、refresh `:94-114`、logout `:116-135`、角色 `:137-174`、错误路径 `:176-256` |
| `tests/auth/test_auth_service.py` | 35 | service 级:用户 `:27-108`、角色 `:110-193`、权限 `:195-226`、绑定 `:228-326`、refresh 异常 `:328-360`、`_ensure_admin` `:362-…` |
| `tests/auth/test_token_store.py` | 18 | 内存语义 `:9-55`、Redis 助手 `:56-105`、降级 `:106-172` |
| `tests/auth/test_models.py` | 12 | ORM 落库/唯一约束/关系 |
| `tests/auth/test_models_unit.py` | 10 | 模型结构(与 `test_models.py` 重叠) |
| `tests/test_auth_guards.py` | 23 | 9 个受保护端点 403(`:109-168`)、401(`:245-246`) |
| `tests/test_auth_router.py` | 8 | 含 toggle 403 路径(`:138-184`) |
| `tests/test_auth_service.py` | 3 | 角色增改删补充(`:12,18,26`) |
| `tests/test_auth_supplementary.py` | 7 | `authenticate_user` / `create_tokens` / `revoke` |

**实测结果**:上述 + `test_core_security.py` / `test_security.py` / `test_dependencies_extra.py` 合跑 **192 passed / 0 failed**(62.78s);子集 `tests/auth` + `test_auth_supplementary.py` + `test_auth_guards.py` **125 passed**(40.93s)。

**测试盲区(未覆盖)**:
1. `/auth/refresh` 限流有效性(P1-3 因此长期无人发现)。
2. "停用/删除用户后旧 refresh 是否失效"(P1-2 无回归)。
3. 硬编码 admin 口令的可配置性/轮换(P1-1)。
4. `token_store` 在真实 Redis 下的并发轮转(仅 mock 级,`tests/auth/test_token_store.py:56-105`)。
5. `_ensure_admin` 并发竞态(P2-9)。
6. X-Forwarded-For 伪造绕过登录限流(P2-1)。
7. 前端 `authStore.test.ts` / `apiClient.test.ts` / `Login.test.ts` 与 `e2e/auth.spec.ts` **不在 CI**(`.github/workflows/ci.yml:87-88` 仅 `npm ci` + `npm run build`;全 workflow 无 playwright/vitest 步骤)。

---

## 8. 客户端集成

| 端 | 机制 | 证据 | 判定 |
|----|------|------|------|
| Web | 登录/刷新/登出 store | `frontend/src/stores/auth.ts:12-21`、`:33-54`、`:56-63` | 部分 |
| Web | 401 自动刷新 + 单飞 + 等待队列(避免并发刷新) | `frontend/src/api/index.ts:11-12,27-68`(排除 `/auth/refresh`、`/auth/login` 自触发 `:27`) | ✅ 实现质量好 |
| Web | 刷新失败清 token 并跳登录 | `:60-64` | ✅ |
| Web | 路由守卫 | `frontend/src/router/index.ts:59-65`(`requiresAuth`) | ✅ |
| Web | 登出请求缺 body | `auth.ts:57` 调 `post('/auth/logout')` 无 `refresh_token`,后端要求 body(`src/auth/router.py:82`) → 422 被 `catch` 吞(`auth.ts:57`) | ❌ **服务端 refresh 永不撤销** |
| Web | token 存 localStorage | `auth.ts:7-8`、`api/index.ts:15,41,51-52` | ⚠️ XSS 可窃取(access+refresh 同地) |
| Web | 错误信息 HTML 转义(防存储型 XSS) | `api/index.ts:70-75` | ✅ |
| 移动端 | SecureStore 存 token | `mobile/src/api/client.js:8,15-24`,请求注入 `:30-32` | ✅ |
| 移动端 | 无 refresh 调用 | `client.js:147-154` 仅 `login`/`register`/`me` | ❌ 60 分钟硬过期,须重登 |
| Admin HTML | 用户增/停用/删 | `src/admin/router.py:166-185`、`:188-204`、`:207-221` | 已实现(但不撤销 token) |
| Admin HTML | 无角色/权限管理页 | `src/admin/templates/admin/` 仅 `users.html`,无 roles/permissions 模板 | ⚠️ 该缺口由 Vue SPA 补齐(见下行),Jinja 面板功能不对称 |
| Vue SPA | RBAC 管理界面(角色表 / 权限表 / 建角色 / 建权限 / 用户-角色绑定 / 角色-权限绑定) | `frontend/src/views/admin/UserList.vue:38`(角色 tab)、`:46`、`:76`、`:108-116`(建角色表单)、`:149-168`(建权限表单)、`:140,191`(绑定勾选)、`:254`(`GET /auth/users`)、`:266`(`GET /auth/roles`)、`:278`(`GET /auth/permissions`)、`:306`(toggle)、`:323`(分配角色) | ✅ 已实现(与 REST 一致;缺角色删除/权限删除的 UI 入口) |

---

## 9. 缺陷清单(按严重度)

### P1(修在生产上线前)

**P1-1 硬编码种子管理员口令**
- 证据:`src/auth/service.py:338` `hashed_password=await async_hash_password("admin123456")`;引导入口为**公开**注册端点(`src/auth/router.py:48-49` 无鉴权 → `service.py:44` 调 `_ensure_admin`)。
- 无任何配置项可覆盖:检查 `src/config.py`、`.env.example`、`deploy/.env.production.example`、`deploy/helm/tms/templates/secret.yaml`、`deploy/helm/tms/values.yaml` 对 `admin|seed` **零命中**。
- 口令已在文档公开:`docs/functional-test-plan.md:45`("超级管理员 admin / admin123456 / 全部权限")、`:90`,并出现在 `docs/fix-auditlog-bodybuffer-hang.md:73` 与多个测试(`tests/test_full_api.py:68,76,78`)。
- 失败场景:未预置管理员的部署,任何能访问 `/api/v1/auth/register` 的人都会触发 seed,然后可用 `admin/admin123456` 拿到全部 `admin.*` 权限(登录端点仅 5 次/60 秒,不构成防线)。

**P1-2 停用/删除用户后旧 refresh 仍能持续换取 access,并可访问绝大多数业务端点**
- 证据链:`src/auth/service.py:99-113`(刷新全程不查 `User`)→ `src/auth/router.py:74-78` 直通;`src/core/dependencies.py:15-42`(鉴权只解 JWT);`src/auth/models.py` 无 token 版本/撤销字段;`revoke_refresh_token` 全仓只在 `src/auth/router.py:83` 被调用。
- 影响面:§6 表显示 **12 个 router 的 190 个端点只有"是否登录"这一道门**,无 permission 校验 → 幽灵 token 仍可读写 OMS/WMS/TMS/PDA/条码/库存;仅 `require_permission` 端点会因 `_get_user_permissions` 返回空集合而 403(`src/core/dependencies.py:102-104`),`/auth/me` 返回 404(`src/auth/router.py:94-95`)。
- 后果:7 天内可持续轮转(每次刷新都写入新 refresh,`service.py:112`),离职/封禁账号无法真正下线。

**P1-3 `/auth/refresh` 的限流装饰器顺序写反,实际未注册**
- 证据:`src/auth/router.py:72-73`(`@rate_limit` 在 `@router.post` **之上**);正确写法见同文件 `:48-49`、`:62-63`。
- 机制:装饰器自下而上应用,`router.post` 先把**未包装**的函数注册进路由表并原样返回,`rate_limit` 之后只重绑模块名(`src/core/rate_limiter.py:145-190` 的 wrapper 未进入路由表)。
- 实测复现:最小脚本(fastapi `APIRouter` 两种顺序各注册一次,读 `route.endpoint` 上的 wrapper 标记)→ 正确顺序 `True`、反序 `False`。脚本位于仓库外临时目录,未纳入代码库。
- 双重证据:即便生效也会 `TypeError` —— wrapper 以 `wrapper(request: Request, *args, **kwargs)` 调用(`rate_limiter.py:147,180`),而 `refresh(request: RefreshRequest)` 无 `Request` 形参(`router.py:74`)。
- 结果:refresh 端点**无任何速率限制**(注释里的 10/60 是假象)。

**P1-4 拿到管理员的唯一路径是硬编码口令;正常注册者拿不到任何角色**
- 证据:`src/auth/service.py:34-41` 建用户时不分配任何角色;`_ensure_admin` 建的 `admin` 是独立账号(`:327-331,334-343`)。
- 失败场景:全新部署里第一个管理员必须知道并使用 `admin123456`(见 `docs/functional-test-plan.md:45`),否则无人能调用 `admin.rbac.manage` 端点去给自己授权 → 运维事实上依赖弱口令进场,且无改密端点可换掉它(§3 缺口)。

### P2

| # | 缺陷 | 证据 | 影响 |
|---|------|------|------|
| P2-1 | 无条件信任 `X-Forwarded-For` 取第一跳作为限流键 | `src/core/rate_limiter.py:152-160`(`:157-160`),无 trusted-proxy 判定 | 伪造头即可绕过登录 5/60(`src/auth/router.py:63`);叠加无账号级锁定(`models.py:10-21`)→ 撞库成本极低 |
| P2-2 | 注册端点做用户枚举 | `service.py:32` → `router.py:54`("Username or email already exists") | 可批量探测已注册邮箱/用户名;登录侧是统一 401(`router.py:67` ✅)但注册侧不是 |
| P2-3 | 全仓只有 auth 有端点限流 | `grep rate_limit(` 全仓命中仅 `src/auth/router.py:49,63,72`;`rate_limiter` 仅在 `src/main.py:99,108` 做连接/关闭,**无全局限流中间件**;预置装饰器 `rate_limiter.py:196-198` 无人使用 | 其余 ~168 个 REST 端点裸奔 |
| P2-4 | 限流 Redis 不可用时 fail-**open** | `rate_limiter.py:74-75`(注释自陈为本地开发便利);测试模式直通 `:71-72`;仅 Redis 命令异常才 fail-closed(`:93-94`) | 生产 Redis 抖动 = 限流消失 |
| P2-5 | RBAC 绑定端点入参为裸 `dict` | `router.py:192,198`(`data["role_id"]`)、`:225,231`(`data["permission_id"]`) | 缺键 → `KeyError` → 500(而非 422);无类型/UUID 校验 |
| P2-6 | toggle 端点分层违规 + 可自我停用 | `router.py:252-269`(端点内 `import uuid` `:262`,直接 `select`/`commit` `:263-268`;service 层无对应函数);无"不能停用自己/最后一个管理员"保护 | 误操作可自锁;破坏 router/service 分层约定 |
| P2-7 | 口令上限 128 vs bcrypt 72 字节静默截断 | `schemas.py:9`(`max_length=128`)vs `security.py:23-27`(裸 `bcrypt.hashpw`) | 超 72 字节的口令实际只校验前 72 字节,声明强度虚高 |
| P2-8 | 列表端点无分页 | `service.py:79-82`(用户)、`:141-144`(角色)、`:176-179`(权限);端点 `router.py:99,123,133` 无分页参数,尽管平台已有 `src/core/pagination.py`(`00-index.md` §2 记录其存在) | 用户量增长后响应膨胀 |
| P2-9 | `_admin_seeded` 进程级全局 + 无并发/跨进程保护 | `service.py:283,294-303,345`;唯一性由 `models.py:16` 索引兜底 | 并发首次注册 → 第二个请求 IntegrityError → 被 `router.py:55-58` 吞成 500,且该请求的注册用户一并回滚(`service.py:46` 同一事务) |

### P3(噪音/技术债)

- 测试重复:`tests/auth/test_models_unit.py` vs `tests/auth/test_models.py`;`tests/test_auth_service.py`(3 用例)嵌在 `tests/auth/test_auth_service.py`(35 用例)之外,同名易混。
- `token_store` 内存回退无 TTL/容量上限(`:29`),`_redis_ok` 单向降级不可恢复(`:30,58,69,81,92`)。
- 冗余唯一约束:`models.py:56,68` 与复合主键重复(见 §4)。
- `PermissionCreate` 无 `Field` 约束(`schemas.py:57-62`)→ 可写入空 `code`;`RoleUpdate` 无长度约束(`:42-44`)。
- JWT `uid` 声明除轮转传递(`service.py:109`)外无消费者。
- `get_current_user` / `get_required_current_user` / `get_optional_current_user` 三变体逻辑重复(`dependencies.py:15-85`),外部调用者选择语义不明。
- `src/auth/router.py:30-45` 在 router 内就地定义 4 个小型 response model(`MessageResponse` 等),与 `schemas.py` 分层不一致。
- `src/tasks/__init__.py:9` 提到 `example.py` 教学桩,实际 `src/tasks/` 无该文件(文档陈旧)。

---

## 10. 完成度缺口(未实现能力清单)

| 能力 | 状态 | 备注 |
|------|------|------|
| 用户自助改密 / 邮箱 / 找回密码 | ❌ | 无 service、无端点、无 token 版本机制可配合 |
| 用户 REST 详情 / 更新 / 删除 | ❌ | 仅 admin HTML 有删除(`admin/router.py:207-221`) |
| 权限 CRUD 完整性(改/删) | ❌ | 只能 create + list(`service.py:176,182`) |
| 角色-权限 / 用户-角色 回显查询 | ❌ | 无 GET 端点;前端无法显示当前绑定 |
| access token 撤销 / 会话列表 | ❌ | 无 `jti`;无会话与 auth 模块的关联(`src/pda` 的 session 属设备会话) |
| 账号锁定 / 失败计数 / 登录审计 | ❌ | 模型无字段(`models.py:10-21`) |
| 业务端点 RBAC 接入 | ❌ | 见 §6(仅 2/16 个 router 使用) |
| Jinja 管理面板的 RBAC 页 | ❌(Vue SPA 已有) | `src/admin/templates/admin/` 无 roles/permissions 模板;Vue 侧已具备:`frontend/src/views/admin/UserList.vue:38-191,254-323` |
| MFA / SSO / OAuth 外部身份 | ❌ | 无相关代码(非缺陷,列为边界) |
| 口令策略(强度/历史/过期) | 部分 | 仅 `min_length=8`(`schemas.py:9`),`SECRET_KEY` 有校验(`config.py:21-37`) |

---

## 11. 建议修复顺序(供 opencode + 9B-Coder 执行,本审计未实施)

1. **P1-1 + P1-4**:`_ensure_admin` 改为读取 `settings.admin_bootstrap_password`(必填、启动校验,类似 `config.py:21-37` 的现有模式)或改为 CLI/迁移播种;并在文档移除明文口令(`docs/functional-test-plan.md:45,90`)。同时给首个注册用户可选 `is_admin` 引导或明确"必须用播种账号建角色"。
2. **P1-2**:`refresh_tokens` 增加 `User` 存在 + `is_active` 校验(`service.py:99-113`);在停用/删除路径调用 `token_store` 撤销(需要按用户索引 refresh token,或在 User 上加 `token_version` 声明并在 `get_current_user` 比对)。配套回归测试。
3. **P1-3**:把 `@rate_limit` 移到 `@router.post` 之下(与 `:48-49` 一致),并加断言测试(refresh 第 11 次请求返回 429)。
4. **P1-4** — 已在 1 内。
5. **P2-5 / P2-6**:补 `RoleAssignRequest` / `PermissionAssignRequest` schema;把 toggle 下沉到 service 并加自我保护(禁止停用自己/最后一个 admin)。
6. **P2-1 / P2-4**:引入 `trusted_proxies` 配置,XFF 仅在可信代理链下采信;限流 Redis 不可用时按配置决定 open/closed。
7. **P2-2 / P2-7 / P2-8 / P2-9**:统一注册冲突文案、限制口令长度 ≤ 72 字节(或改 passlib)、列表接入 `src/core/pagination.py`、`_ensure_admin` 用 DB 级幂等(`ON CONFLICT DO NOTHING`)取代进程标志。
8. **能力补齐**:自助改密 + 用户 CRUD + 权限改删 + 回显 GET(与 §3 缺口表一一对应)。

---

## 12. 审计方法与未验证项

**已实测**
- 认证相关测试:`192 passed / 0 failed`(62.78s),见页首复核命令;子集 125 passed(40.93s)。
- 装饰器顺序语义:仓库外临时目录最小复现脚本(两种顺序各注册一次,检查 `route.endpoint` 是否为 wrapper)→ 反序时路由表内为**未包装**函数。
- 跨模块取证:`require_permission(` 计数(admin 12 / auth 12 / 定义 1)、`rate_limit(` 全仓命中(auth 3 + `src/cache/decorators.py` 内部同名函数)、端点装饰器计数(§6 表)、WebSocket 2 处、`admin123456` 全仓 9 处命中、`revoke_refresh_token` 仅 1 处调用、CI 步骤清单(`ci.yml:17-19,53-71,87-88`)。

**未验证(下次深审需补)**
1. `_best_effort` 约束补建(`alembic/versions/26f0642a5601:185,198`)在**全新 SQLite 库**上的实际效果(AGENTS.md 只记录 PG 侧已验证)。
2. `token_store` 在真实 Redis 下的行为(现有测试均为 mock 级,`tests/auth/test_token_store.py:56-105,126-172`)。
3. 多 worker(uvicorn `--workers > 1`)下内存回退模式的 refresh 可用性(`token_store.py:29,94`)。
4. `require_permission` 每请求两次 `selectinload` 查询的性能影响(`dependencies.py:98-101`)——未做压测。
5. 生产 Helm 是否强制注入足够强度的 `SECRET_KEY`(`config.py:26-37` 有校验,但未实跑 `alembic upgrade head` + 启动校验链)。
