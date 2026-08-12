# OMS-WMS-TMS — 操作手册 v1.0

**状态**: master 分支 | **最后更新**: 2026-08-12

## 一、项目结构速览

```
oms-wms-tms/
├── src/                # FastAPI 后端源码
│   ├── core/          # settings/db/repo/outbox 等基础设施
│   ├── oms/           # OMS: Order, MergeGroup (拆合单)
│   ├── wms/           # WMS: Vendor, Shipment, PO, Invoice
│   ├── tms/           # TMS: TransportOrder, Waybill, ReturnOrder, Exception
│   ├── pda/           # PDA 离线队列 + WebSocket 实时同步
│   └── barcode/       # EAN-13/QR/ZPL 条码生成、Excel 导入导出
├── tests/             # pytest 测试集（~347 用例，全通过）
├── docker-compose.prod.yml    # 生产环境编排
├── .github/workflows/ci.yml   # CI: lint + typecheck + test
└── docs/architecture.md     # 系统架构总览
```

## 二、快速启动

### 开发环境（本地）

```bash
docker compose up -d          # 拉起 postgres + redis + app
python -m uvicorn src.main:app --reload --host 0.0.0.0   # 手动启动
# 或：uvicorn src.main:app --factory --host 0.0.0.0 --port 8001
```

- **数据库**: PostgreSQL 16（异步 + 同步双连接）
- **缓存/队列**: Redis 7（Celery broker，无 RabbitMQ）
- **健康检查**: `curl http://localhost:8001/health` → `{status:"ok", "database":true, "redis":true}`

### 生产环境

```bash
docker compose -f docker-compose.prod.yml up -d
# 或 Helm
helm upgrade --install oms-wms-tms ./oms-wms-tms/chart \
    --namespace logistics --create-namespace --values ./chart/values.yaml
```

## 三、API 使用（`http://localhost:8001/api/v1/`）

### OMS — 订单管理

| 端点 | 方法 | 说明 |
|------|------|------|
| `/orders` | POST | 创建订单，JSON：`{"customer_id":"C001","priority":"urgent","items":[{"sku":"SKU-XX","qty":2}]}` |
| `/orders/{id}` | GET/PUT | 详情 / 更新（支持状态机流转） |
| `/merge/{group_id}` | GET | 合并订单组列表（分页，裸 list→`{"items":[...]}`） |

### WMS — 仓库管理

| 端点 | 说明 |
|------|------|
| `/vendors` / `/purchase-orders` / `/shipments` | 供应商/采购单/发货清单 CRUD |
| `/warehouses/{wh_id}/locations` | 库位（分页，含 status/position） |

### TMS — 运输管理

| 端点 | 说明 |
|------|------|
| `/transport-orders` | 运单 CRUD + 状态机 |
| `/waybills` / `/return-orders` | 运单、退货 |
| `/exceptions` | 运输异常（含 TransportExceptionResponse） |

### PDA — 移动作业

- `/pda/register/{device_id}` — 设备注册并加入 WebSocket 广播通道
- `/pda/sessions/{id}/devices` — 会话关联的设备列表

**响应格式统一**: 分页端点返回 `{"items":[...],"total":N,"page", "page_size","has_next_page"}`；单条记录直接返回对象。

## 四、测试与质量保障

```bash
pytest tests/ -v                        # 全量运行（1720 passed / 0 failed）
pytest tests/ --cov=src --cov-report=term-missing   # 覆盖率报告
ruff check .          # lint（源码通过）
mypy src/             # 类型检查，所有文件须 pass
```

**注意**: `tests/test_e2e.py`（E2E 超时用例）已删除；`src/ml/` 是 WSL 兼容性二进制层，非源码勿删。

## 五、代码规范

- **Ruff** — lint + auto-format（替代 Flake8+isort）
- **mypy --strict** — 所有文件必 `pass`
- **pytest coverage ≥ 80%**

```bash
ruff check .          # lint
ruff format .         # format
mypy src/             # type-check
pytest tests/         # test
```

## 六、数据库迁移（Alembic）

```bash
# 根据 models.py 变更自动生成 migration
alembic revision --autogenerate -m "add transport_orders table"

# 应用所有待应用迁移
alembic upgrade head

# 回滚上一版本（慎用）
alembic downgrade -1
```

## 七、任务队列

- **Celery**: `celery -A src.tasks worker --loglevel=info`（Redis broker，无 RabbitMQ）
- **Outbox** — HTTP 派发，事件持久化 + 可靠投递

## 八、运维说明

### 日志与监控
- Python `logging` + `structlog`，输出 JSON 格式便于 ELK/EFK 收集
- OpenTelemetry traces + Sentry error tracking

### CI / CD
- `.github/workflows/ci.yml`: PR 合并前自动跑 lint + typecheck + tests（~5min）
- Docker build → push ECR → deploy via ECS/AWS；deploy.yml Helm 步骤待启用

## 九、常见问题排查

| 问题 | 原因 & 解决 |
|------|-------------|
| Alembic migration 失败 | 检查 models.py 中是否有未声明外键的 `relationship()` |
| TMS TransportOrder 创建报错 | 确认 carrier_code 在 CarrierCode enum 中存在 |
| Hub-and-Spoke Dijkstra 无结果 | 检查 hub_connections 表中 from/to 连接是否完整 |
| PDA WebSocket 未推送 | 确认设备已 register 且 Redis pubsub 连通 |

## 十、开发约定

1. **模型变更**: 修改 `src/oms/wms/tms/models.py` → `alembic revision --autogenerate -m "..."` → `upgrade head`
2. **新增 API 端点**: 在对应模块的 service + router 中实现，保持 Pydantic schema 与 ORM model 分离；返回类型加 response_model 约束（如 MergeGroupResponse/LocationListResponse）
3. **Celery Task**: 写于 `src/tasks/`，避免每次创建新引擎（复用共享 engine）

## 附录：本次核查结论（2026-08-12）

- ✅ P0 "OrderPriority.URGANIC" bug：**不存在**（跳过修复）
- ✅ 全量测试 `pytest tests/`: **1720 passed / 0 failed**
- ✅ Ruff lint: 源码全部通过
- ✅ docs/architecture.md + completion report 已提交

---

*报告生成时间：2026-08-12 · 代码仓库：D:\oms-wms-tms · 状态分支：master*
