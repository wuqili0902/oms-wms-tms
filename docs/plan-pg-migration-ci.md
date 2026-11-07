# 方案:让 CI 的 "Apply Alembic migrations on fresh PostgreSQL" 跑绿

**背景**:master 已合入 `f2d791a`。合入后 CI run #28 与 Build/Test/Deploy run #18 均 `failure`,卡点都是同一步:`Apply Alembic migrations on fresh PostgreSQL`(`.github/workflows/ci.yml:58-63`)。`lint`(ruff)与 `frontend-build` 本次已 `success`;因该步失败,`Run tests` 被 skip,`build-and-push` 与 `deploy` 也被 skip —— **本次没有推镜像、没有部署**。旧 tip `f1279a6` 的 run #27/#17 在同一步失败(且当时 lint 也红),即本卡点在合入前就存在。

本地 `pytest tests/` 是 **2571 passed / 2 skipped / 0 failed**、`ruff check src tests` 全通过。本地绿、CI 红的原因:测试跑在 SQLite(`tests/conftest.py` 为 SQLite-only),SQLite 对列类型转换不检查;PG 检查。

## 复现(已实测,可照抄)

```bash
# 前提:本机 PostgreSQL 16 在 :5432,密码 postgres
export PGPASSWORD=postgres
"/c/Program Files/PostgreSQL/16/bin/psql.exe" -U postgres -h 127.0.0.1 -q \
  -c "DROP DATABASE IF EXISTS oms_wms_tms_ci_repro;" \
  -c "CREATE DATABASE oms_wms_tms_ci_repro;"

# 第 1 关(照 CI 原样写 postgresql://)
DATABASE_SYNC_URL="postgresql://postgres:postgres@localhost:5432/oms_wms_tms_ci_repro" \
  SECRET_KEY="ci-test-secret-key-do-not-use" .venv/Scripts/alembic.exe upgrade head
# → ModuleNotFoundError: No module named 'psycopg'
#   栈:sqlalchemy/dialects/postgresql/psycopg.py:import_dbapi

# 第 2 关(把 scheme 钉到 psycopg2 后才暴露)
DATABASE_SYNC_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/oms_wms_tms_ci_repro" \
  SECRET_KEY="ci-test-secret-key-do-not-use" .venv/Scripts/alembic.exe upgrade head
# → psycopg2.errors.DatatypeMismatch: 字段 "estimated_delivery_date" 不能自动转换类型 date
#   HINT: 你可能需要指定 "USING estimated_delivery_date::date"
#   [SQL: ALTER TABLE transport_orders ALTER COLUMN estimated_delivery_date TYPE DATE]
#   结果:迁移中止,库内 0 张表
```

**注意:psql 必须在同一 shell 里先 `export PGPASSWORD`,不能只在 alembic 命令前赋值** —— psql 无密码会卡在交互提示上(踩过一次,白等 300s)。

## 根因 A:同步 URL 没钉 driver(本地已复现,CI 条件一致)

`sqlalchemy[asyncio]>=2.0.30,<3.0`(`pyproject.toml:11`)在 CI 与本地解析到的都是 **2.1.1**。SQLAlchemy 2.1 起,`postgresql://` 的默认 dialect 是 **psycopg(v3)**;项目只声明 `psycopg2-binary`(`pyproject.toml:13`),`[dev]`/`[otel]` extras 里也没有 psycopg。于是 `postgresql://` 直接 `ModuleNotFoundError`。

需要钉 scheme 的全部位置(`postgresql://` → `postgresql+psycopg2://`),共 7 处:

| 文件 | 行 |
|---|---|
| `.github/workflows/ci.yml` | 60 |
| `.github/workflows/deploy.yml` | 61 |
| `deploy/docker-compose.prod.yml` | 62, 109, 147 |
| `deploy/helm/tms/templates/deployment.yaml` | 45(值在 `DATABASE_SYNC_URL` 项内,核对上下文) |
| `.env.example` | 14(本机 `.env` 同步改,`.env` 不入库) |
| `deploy/.env.production.example` | 17(注释示例) |

**选择理由**:钉 scheme 是纯字符串改动,不动运行时驱动;备选方案是加 `psycopg[binary]` 依赖并把同步驱动换成 psycopg3 —— 那会换掉生产环境的 PG 驱动,影响面大,本次不采用。`DATABASE_URL`(asyncpg)不动。

## 根因 B:迁移里的 `USING` 关键字全部拼错,被 alembic 静默忽略

`op.alter_column` 接受方言前缀关键字 **`postgresql_using`**;写成 `postgres_using`(少 `ql`)会落进 `**kwargs` 被**静默丢弃**,生成的 SQL 没有 `USING` 子句。全链搜索:`postgres_using` **3 处**、`postgresql_using` **0 处** —— 即链上每一个 PG 类型转换从来没带过 `USING`:

| 文件:行 | 转换 | 现写法 |
|---|---|---|
| `alembic/versions/e1a2b3c4d5e6_fix_tms_schema_drift.py:28` | `transport_orders.estimated_delivery_date` String(30)→Date | `postgres_using="estimated_delivery_date::date"` |
| `alembic/versions/a1b2c3d4e5f6_fix_remaining_schema_issues.py:94` | `shipments.shipped_at` String(30)→DateTime(tz) | `postgres_using="shipped_at::timestamp with time zone"` |
| `alembic/versions/a1b2c3d4e5f6_fix_remaining_schema_issues.py:102` | `shipments.delivered_at` String(30)→DateTime(tz) | `postgres_using="delivered_at::timestamp with time zone"` |

**链条顺序(共 13 步,单 head `c7f3a91b4d02`)**:
`… → d5e6f7a8b9c0 → 26f0642a5601 → e1a2b3c4d5e6 → a1b2c3d4e5f6 → b2c3d4e5f6a7 → … → f3a6b1c9d248 → c7f3a91b4d02`

CI 现在死在 `e1a2b3c4d5e6`(第 9 步)。**只修它,下一关就是 `a1b2c3d4e5f6` 的两处 shipments 日期转换** —— 三处必须一起修,否则一次 CI 只能多暴露一层。

**`downgrade()` 同样缺 `USING**`:`a1b2c3d4e5f6:108-117` 把 DateTime(tz) 改回 String(30)、`e1a2b3c4d5e6:51-57` 把 Date 改回 String(30),PG 下这些也需要 `USING "col"::varchar(30)`(现写法没有)。

## 为什么可以直接改这三个既有 revision

- 这些转换在 PG 上**从未成功过**(CI 从没跑绿过这一步),不存在"已按旧语义跑过迁移"的 PG 库;
- CI 与部署迁移都是对**空库**跑全链(`ci.yml` 用全新 PG service,`deploy.yml` 同理),不存在增量识别问题;
- 仓库既有实践就是就地修既有 revision(`26f0642a5601` 被改成 `_best_effort()` 助手),不新增 revision。
- 若之后要让**已有** PG 库升级,必须单独确认它当前落在哪个 revision(`alembic current`),不能假设。

## 施工清单(编码阶段按此顺序)

1. `alembic/versions/e1a2b3c4d5e6_fix_tms_schema_drift.py:28`:`postgres_using` → `postgresql_using`;`downgrade()` 的 `alter_column` 补 `postgresql_using="estimated_delivery_date::varchar(30)"`。
2. `alembic/versions/a1b2c3d4e5f6_fix_remaining_schema_issues.py:94,102`:同改 `postgresql_using`;`downgrade():108-117` 两处补 `postgresql_using="shipped_at::varchar(30)"` / `"delivered_at::varchar(30)"`。
3. 7 处 `DATABASE_SYNC_URL` 的 scheme 钉成 `postgresql+psycopg2://`(表格见上);本机 `.env` 同步。
4. 顺手核对链上是否还有别的"改类型没带 USING"的调用:`grep -n -A6 "op.alter_column" alembic/versions/*.py | grep type_`,凡 `type_=` 且涉及 date/timestamp↔string 的都补 `postgresql_using`。
5. `26f0642a5601` 里的 `_best_effort()` 会**吞掉失败**(AGENTS.md 记录的设计),PG 下类型转换失败会静默通过并留下 schema drift —— 不改其行为,但在 PG 全链验证通过之前不要依赖它。

## 验收(必须逐条给证据)

```bash
export PGPASSWORD=postgres
psql … -c "DROP DATABASE IF EXISTS oms_wms_tms_ci_repro;" -c "CREATE DATABASE oms_wms_tms_ci_repro;"
DATABASE_SYNC_URL="postgresql+psycopg2://…/oms_wms_tms_ci_repro" SECRET_KEY="ci-test-secret-key-do-not-use" \
  .venv/Scripts/alembic.exe upgrade head          # 要求:退出码 0,无 DatatypeMismatch
psql -d oms_wms_tms_ci_repro -t -c \
  "select count(*) from information_schema.tables where table_schema='public';"   # 要求:>0(修前实测 0)
psql -d oms_wms_tms_ci_repro -t -c \
  "select data_type from information_schema.columns where table_name='transport_orders' and column_name='estimated_delivery_date';"   # 要求:date
psql -d oms_wms_tms_ci_repro -t -c \
  "select data_type from information_schema.columns where table_name='shipments' and column_name in ('shipped_at','delivered_at');"   # 要求:timestamp with time zone
.venv/Scripts/alembic.exe downgrade base && .venv/Scripts/alembic.exe upgrade head   # 要求:来回一次仍退出码 0(downgrade 侧的 USING 由这一步验收)
.venv/Scripts/python.exe -m pytest tests/ -q      # 要求:与合入前同级(2571 passed / 0 failed)
.venv/Scripts/python.exe -m ruff check src tests  # 要求:All checks passed
```

**禁止**只看 CI 绿就收工:CI 的这一步绿了才轮到 `Run tests`,两步都要看;`deploy` 作业推 master 会真的部署。

## 施工后的实测结果(2026-11-07,本机 PostgreSQL 16)

改动为 8 个文件:2 个 revision 的 3 处 `postgresql_using` + 3 处 `downgrade` 补 `USING`、6 个配置文件里 7 处 `DATABASE_SYNC_URL` scheme(其中 helm 侧实际落在 `deploy/helm/tms/templates/secret.yaml`,`deployment.yaml` 通过 `secretKeyRef` 引用它 —— 比本文表格里写的行号位置更准)。

- 空库 `alembic upgrade head`:退出码 0,全链 13 步跑到 `c7f3a91b4d02`;`public` 下 63 张表(修前实测 0 张)
- `transport_orders.estimated_delivery_date` = `date`;`shipments.shipped_at`/`delivered_at` = `timestamp with time zone`
- `ruff check src tests`:All checks passed(`alembic/` 有 81 处 lint 错误,属既有状态 —— `pyproject.toml:68` 的 `exclude` 含 `alembic`,CI 也只跑 `src/ tests/`)

## 已知遗留:`downgrade base` 之后不能直接 `upgrade head`(非本次修复范围)

验收清单里"downgrade base → upgrade head 来回一遍"这一条**未通过**,原因与 `USING` 无关:

- `downgrade base` 退出码 0,表从 63 张删到 1 张(只剩 `alembic_version`)
- 但 PG 里残留 **35 个 enum 类型**(`carriercode`、`orderstatus`、`shipmentstatus` …):这些类型是 `eb47b7e1074b_full_schema` 建表时由 alembic 随 `sa.Enum` 列自动 `CREATE TYPE` 出来的,该 revision 的 `downgrade()` 只删表,没有配对的 `DROP TYPE`
- 于是紧接着的 `upgrade head` 停在 `CREATE TYPE carriercode AS ENUM (...)` → `psycopg2.errors.DuplicateObject: 类型 "carriercode" 已经存在`
- 对照:`b0c1d2e3f4a5:48-49`、`f6e7d8c9b0a1:57-58` 这类后来的 revision 自己写了 `DROP TYPE IF EXISTS …` 守卫,`eb47b7e1074b` 没有

**不影响 CI 与部署**:两者都是对空库直接 `upgrade head`,不跑 `downgrade`。若要让"来回迁移"成为可用能力,需要给 `eb47b7e1074b` 的 `downgrade()` 补按依赖顺序的 `DROP TYPE`(35 个,且被多表共用的类型要在所有引用表删除后才能删)—— 这是独立工作量,不要和本修复混在一起做。

# 第二轮 (2026-11-07 晚): CI 仍红,真正死因是 env.py 的 import 期校验

`09eb577`(上一节的修复)推上 master 后,CI #29 与 Build/Test/Deploy #19 仍是 `failure`,仍停在 `Apply Alembic migrations on fresh PostgreSQL`,`Run tests` 被 skip。**上一节的 A/B 两项修复是必要且不回退的**(`lint` 与 `frontend-build` 全绿,迁移链本身已验绿),CI 里还剩第三个原因。

## 根因 C: `alembic/env.py` import 期要求 `DATABASE_URL`,CI 那一步只给了 `DATABASE_SYNC_URL`

`alembic/env.py` 在模块顶部 `from src.config import settings`;`src/config.py:161` 是模块级 `settings = Settings()`,pydantic-settings 的校验器要求 `DATABASE_URL` 有值。CI 的这一步只注入 `DATABASE_SYNC_URL` + `SECRET_KEY`,而 Actions 的 checkout 里**没有 `.env`**(被 gitignore)→ 迁移在 env.py 导入阶段就抛:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
  Value error, DATABASE_URL must be set via environment variable or .env file.
```

**连一条 SQL 都没发出**,所以这一步的红与迁移内容无关 —— 这也解释了为什么两个工作流在同一步同速失败、为什么 `lint`/`frontend-build` 绿、为什么本地全绿(本机根目录有 `.env`,它提供了 `DATABASE_URL`)。旧 tip `f1279a6` 在同一步红,这条同样是原因之一。

### 实测证据(本机,`.env` 临时改名模拟 CI checkout,跑完即还原)

| 条件 | 结果 |
|---|---|
| 无 `.env`,只给 `DATABASE_SYNC_URL` + `SECRET_KEY` | **退出码 1**,`ValidationError: DATABASE_URL must be set ...` |
| 无 `.env`,给 `DATABASE_URL`(asyncpg) + `DATABASE_SYNC_URL` + `SECRET_KEY` | **退出码 0**,全链跑到 `c7f3a91b4d02`,63 张表 |

## 施工清单(本轮,范围只有 2 个文件)

1. `.github/workflows/ci.yml` 的 "Apply Alembic migrations on fresh PostgreSQL" 步骤 `env:` 里加一行:
   `DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/oms_wms_tms_test`
2. `.github/workflows/deploy.yml` 同名步骤 `env:` 里加一行:
   `DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/oms_wms_tms`

硬性约束:
- **禁止**把 `.env` 提交进仓库(里面有密钥,且已被 gitignore)。
- **禁止**为了让 CI 过而放宽 `src/config.py` 的 `DATABASE_URL` 校验(那条校验是应用侧的防线,`test_raises_on_empty_secret` 依赖它)。
- **禁止**改动 `alembic/versions/*` 与迁移链指向(上一轮已验绿,不要顺手动)。
- `DATABASE_SYNC_URL` 保持 `postgresql+psycopg2://`(上一轮已钉),不要动。

### 建议一起做(同一 commit 内,可选但要标注)

3. 让这一步失败时把输出暴露到 job summary,便于以后不登录 `gh` 也能定位(我已实测:公开 API `GET /repos/{owner}/{repo}/commits/{ref}/check-runs` 返回 200,`output.summary` 字段可读,当前为空)。写法示例:

   ```yaml
   run: |
     set +e
     alembic upgrade head 2>&1 | tee /tmp/alembic.log
     rc=${PIPESTATUS[0]}
     if [ "$rc" -ne 0 ]; then
       { echo "### alembic upgrade head 失败 (exit $rc)"; echo '```'; tail -60 /tmp/alembic.log; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
     fi
     exit "$rc"
   ```
   要点:保留"失败就让步骤失败"的语义(`exit "$rc"`),不要变成 `|| true`。

4. `.env.example` 里加注释:`DATABASE_SYNC_URL` 供 alembic 同步用,但 `alembic/env.py` 会 import `src.config`,因此运行 alembic 时 `DATABASE_URL` 也必须在环境里 —— 省得下次再踩。

## 验收(逐条给证据,不许只说"CI 绿了")

```bash
# A. 复现"无 .env"这一 CI 条件,并证明修法有效(.env 必须立刻还原)
mv .env .env.probe_bak
psql -U postgres -h 127.0.0.1 -q -c "DROP DATABASE IF EXISTS oms_wms_tms_fix_probe;" -c "CREATE DATABASE oms_wms_tms_fix_probe;"
env -u REDIS_URL -u SENTRY_DSN \
  DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/oms_wms_tms_fix_probe" \
  DATABASE_SYNC_URL="postgresql+psycopg2://postgres:postgres@localhost:5432/oms_wms_tms_fix_probe" \
  SECRET_KEY="ci-test-secret-key-do-not-use" .venv/Scripts/alembic.exe upgrade head   # 要求 exit 0
psql -d oms_wms_tms_fix_probe -t -c "select count(*) from information_schema.tables where table_schema='public';"   # 要求 63
mv .env.probe_bak .env
psql -U postgres -h 127.0.0.1 -q -c "DROP DATABASE IF EXISTS oms_wms_tms_fix_probe;"
git status --short   # 要求: 无 .env.probe_bak 等残留

# B. 不退化
.venv/Scripts/python.exe -m pytest tests/ -q          # 要求 2571 passed / 0 failed
.venv/Scripts/python.exe -m ruff check src tests      # 要求 All checks passed
```

推送后看 CI:本轮改动会让 `Apply Alembic migrations` 绿,于是 **`Run tests with PostgreSQL` 第一次真正执行**(历史上新增的失败会在这里出现,属于新暴露,不是本次改动弄坏);`Build, Test, and Deploy` 的 `build-and-push` 与 `deploy` 也会从 skip 变执行 —— **`deploy` 是真实部署,推 master 前须知情**。

## 已排除清单(不要重复调查)

- `postgresql_using` 拼错 → 已修已验(3 处 + downgrade 3 处)
- `postgresql://` 在 SQLAlchemy 2.1 默认解析成 psycopg3 → 已修已验(7 处 scheme)
- 依赖版本面:照 CI 的 `pip install -e ".[dev,otel]"` 建净 venv(SQLAlchemy 2.1.8 / alembic 1.20.1 / psycopg2-binary 2.9.13 / asyncpg 0.32.0),全链 `upgrade head` 退出码 0 → **不是版本问题**
- `SECRET_KEY` 长度校验:`ci-test-secret-key`(18)与 `ci-test-secret-key-do-not-use`(30)都退出码 0 → **不是密钥长度**
- `downgrade base` 后残留 35 个 enum 类型 → 真实缺陷,但与本步无关(不在 CI 路径),见上一节
- 本机到 GitHub 的 HTTPS 出口会整段不通(`github.com` 000 而 `api.github.com` 200);推送改走 `ssh://git@ssh.github.com:443/...` + `~/.ssh/id_ed25519_github`,详见记忆 `github-443-flaky-push`

## 附带事实(供后续参考,非本次施工项)

- 本机到 GitHub :443 间歇丢包:`git push` 会以 `Failed to connect to github.com:443 after ~21000 ms` 失败,重试到第 2 次即成功;不是代理(Windows `ProxyEnable=0`)、不是 IPv6(`GIT_CURL_VERBOSE` 显示 `IPv6: (none)`,IPv4 `20.205.243.166`)。判链路用 `curl -s -o /dev/null -w "%{http_code} %{time_total}" https://github.com`(实测 12s 才握手),远端是否真更新用 `git ls-remote origin refs/heads/master` 核实。
- 本机 PostgreSQL 16 服务名 `postgresql-x64-16`,`psql` 在 `/c/Program Files/PostgreSQL/16/bin/psql.exe`,不在 PATH。
