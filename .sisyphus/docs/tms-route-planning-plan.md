# TMS 多级中转路线规划功能开发计划

## 项目背景

为 TMS（运输管理系统）新增 **Hub-and-Spoke 多级转运路线规划**能力。  
一个物流订单从武汉运货到柳州，系统需自动计算直达方案 vs 经长沙中转方案，并返回最优路径。

主流方案采用 Dijkstra/A* 最短路径算法 + CarrierRoute 价格对比实现多段运输优化。

---

## 一、已完成部分 (✅)

### 1. 数据模型层 (`src/tms/models.py`)
| 模型 / 枚举 | 说明 |
|-------------|------|
| `TransferHubType` | 枢纽类型：primary / secondary / cargo_station |
| `TransferHub` | 转运枢纽 CRUD |
| `CarrierRoute` | 预定义承运商线路价格表（distance_km, transit_hours, base_price_per_kg） |
| `TransportSegmentStatus` | Segment 生命周期状态枚举 (draft → dispatched → pickup → in_transit → completed) |
| `TransportSegment` | 单段运输任务（多段路线中的每一段） |
| `HubConnection` | Hub 之间有向图边，用于路径规划算法 |
| `RoutePlanType`, `RoutePlanStatus` | RoutePlan 类型与状态枚举 |
| `RoutePlan` | 多段路线蓝图，关联 TransportOrder |

### 2. Schema 定义层 (`src/tms/schemas.py`)
| Schema | 说明 |
|--------|------|
| `TransferHubCreate / TransferHubResponse` | Hub CRUD 请求/响应 |
| `CarrierRouteCreate / CarrierRouteResponse` | 线路价格维护 |
| `TransportSegmentCreate / TransportSegmentResponse` | Segment 管理 |
| `HubConnectionCreate / HubConnectionResponse` | 连接关系管理 |
| `RoutePlanCreate / RoutePlanResponse` | RoutePlan CRUD |

### 3. Service import (`src/tms/service.py`)
已添加对 CarrierRoute, HubConnection, RoutePlan, TransferHub, TransportSegment 及相关枚举的引用。

---

## 二、待完成工作 (🟡)

### Phase A — Service 业务逻辑函数（service.py 尾部追加）

| # | 函数签名 | 难度 |
|---|----------|------|
| 1 | `create_hub(db, data)` / `update_hub(hub_id, data)` | Simple CRUD |
| 2 | `get_hub` / `list_hubs(city?, type?)` | Simple |
| 3 | `add_carrier_route` / `list_carrier_routes(origin_city?, dest_city?)` | Simple |
| 4 | `add_hub_connection(data)` / `list_hub_connections(hub_code?)` | Simple |
| 5 | **`find_best_route_plan(transport_order_id, db)`** ⭐ | Core algorithm — Dijkstra + cost optimization |
| 6 | **`generate_route_plan(order_id, type="auto_gen")`** | Complex — creates RoutePlan + TransportSegments |
| 7 | `create_segment(data)` / `update_segment_status(seg_id, status)` | State Machine |

### Phase B — Route Planning 核心算法（关键）

```python
async def find_best_route_plan(transport_order_id: str, db: AsyncSession) -> dict:
    """Dijkstra 最短路径 + CarrierRoute 价格优化"""

    # Step 1 - 加载订单，解析 origin / dest city
    order = await get_transport_order(db, transport_order_id)

    # Step 2 - 查找起点 Hub & 终点 Hub (按 city name)
    origin_hubs = list_hubs_by_city(order.pickup_address.city)
    dest_hubs = list_hubs_by_city(order.delivery_address.city)

    # Step 3 - 构建 HubConnection 有向图
    graph, edge_weights = build_graph_from_hub_connections()

    # Step 4 - Dijkstra: origin → dest (bidirectional edges)
    for o in origin_hubs:
        for d in dest_hubs:
            dist, time_est, path = dijkstra(o.code, d.code, graph)

    # Step 5 - 结合 CarrierRoute 定价计算成本，选出最优解
    candidates = [...]  # list of (path, cost_km, transit_hours)

    return {
        "origin_city": origin_city,
        "destination_city": dest_city,
        "total_distance_km": best.path_total_distance,
        "estimated_transit_hours": best.transit_time_estimate,
        "segments": [
            {"segment_no": i, "from_hub": p[i], "to_hub": p[i+1]}
            for i in range(len(best.segments))
        ]
    }
```

### Phase C — Router API 端点（router.py 尾部追加）

| Method | Path | Function |
|--------|------|----------|
| POST | `/transfer-hubs` | `create_hub(data, db)` |
| PATCH | `/transfer-hubs/{hub_id}` | `update_hub(hub_id, data, db)` |
| GET | `/transfer-hubs` | `list_hubs(city?, type?, db)` |
| GET | `/transfer-hubs/{hub_id}` | `get_hub(hub_id, db)` |
| POST | `/carrier-routes` | `add_carrier_route(data, db)` |
| GET | `/carrier-routes` | `list_carrier_routes(db)` |
| POST | `/hub-connections` | `add_hub_connection(data, db)` |
| GET | `/hub-connections` | `list_hub_connections(hub_code?, db)` |
| **POST** | **`/transport-orders/{order_id}/route-plans`** | `generate_route_plan(order_id, type="auto_gen", db)` |
| GET | `/route-plans/{plan_id}` | `get_route_plan(plan_id, db)` |
| PATCH | `/segments/{seg_id}/status` | `update_segment_status(seg_id, status, db)` |

### Phase D — 可选补充
1. **种子数据初始化脚本** (seed.py) — 武汉、长沙、柳州等 Hub + 基础连接
2. **单元测试** — pytest 覆盖 route planning 核心算法
3. **API 文档示例** (curl / Postman)

---

## 三、开发优先级排序

| P | 功能 | 依赖关系 |
|---|------|----------|
| P0 | `find_best_route_plan` Dijkstra 最短路径 | 核心算法，其余依赖它 |
| P1 | `generate_route_plan(auto_gen)` — 基于路由方案创建 RoutePlan + Segments | 调用 P0 |
| P2 | TransportSegment CRUD + status update (state machine) | 展示 segment |
| P3 | TransferHub / HubConnection / CarrierRoute CRUD API | 管理数据 |

---

## 四、当前进度概览

```
models.py          ██████████ 100% complete ✅
schemas.py         ██████████ 100% complete ✅  
service imports     ██████████ 100% complete ✅
service functions   ███░░░░░░░ ~25% — core route planning function started
router.py           ░░░░░░░░░░ 0% — no new endpoints yet
```

---

## 五、状态机（TransportSegment）

```
draft ──► dispatched ──► pickup ──► in_transit ──► transit_hub_arrived ◄──┐
                                                        │                 │
                                                      out_for_delivery   sorting_center
                                                        │                 │
                                                          ▼               ▼
                                                        completed ←─────── in_transit
```

- `in_transit` → `out_for_delivery`: 到达目的地城市
- `transit_hub_arrived` → `sorting_center`: 中转枢纽分拣
- `exception` 分支：任意状态可跳入 exception（延迟/损坏/丢失）
