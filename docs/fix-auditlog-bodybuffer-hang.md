# Fix: AuditLogMiddleware 导致 loopback 上 POST 登录卡死（timeout）

## 状态
- **分析方**：Claude Code + 35B-A3B（本方案 = 规划/分析产出）
- **实施方**：opencode + 9B-Coder-MTP（开工前请先读本文档）
- **日期**：2026-09-30

## 症状
浏览器 `http://localhost:5173/` 登录（代理到后端 `POST /api/v1/auth/login`）在
loopback (`127.0.0.1`) 上 **ReadTimeout**；GET `/health` 正常；空 body 的 POST 快速返回 400，
带非空 body 的 POST 永久卡住。

## 根因（已实证）
文件：`src/core/middleware.py`，类 `_BodyBuffer` 的方法 `read_all()`（约 131–141 行）。

```python
async def read_all(self) -> bytes:
    if not self._chunks and not self._done:
        while True:
            message = await self._receive()
            body = message.get("body", b"")
            if not body:          # ← 只判断空 body，忽略了 ASGI `more_body` 标志
                break
            self._chunks.append(body)
        self._done = True
    return b"".join(self._chunks)
```

对单次分块的普通 POST（如登录，body≈45B）：第一次 `receive()` 拿到 body 且
`more_body=False`，因代码只看 `if not body` 而不看 `more_body`，循环**再调一次**
`self._receive()`。而 uvicorn/proactor 在 `more_body=False` 之后不会再发消息，
该调用因此**永久阻塞**。于是 `AuditLogMiddleware.__call__` 卡在
`_extract_request_body(wrapped)` → `wrapped.read_all()`，永远到不了
`self.app`，响应从不发出 → 客户端 ReadTimeout。

为何符合所有观察：
- POST 登录（非空 body）→ `read_all()` 多读一次 → 卡死 ✓
- GET `/health` → 不在 `[POST,PUT,DELETE,PATCH]`，跳过审计、不调 `read_all` → 正常 ✓
- 空 body POST → 首条消息 body 为空 → 立即 break → 不卡 → 快速 400 ✓

**隔离复现**（同机实证）：把当前 `_BodyBuffer.read_all()` 原样搬进最小 ASGI 服务，
loopback 上 GET=200、POST=/login=ReadTimeout；把 `read_all` 改成尊重 `more_body` 后，
GET/POST 均 200。复现/验证脚本：`repro-buggy.py`（卡）、`repro-fixed.py`（好）。

## 修复（最小、明确）
修改 `src/core/middleware.py` 中 `_BodyBuffer.read_all()`，在循环里尊重 `more_body`，
在收到 `more_body=False` 的那条消息后停止（与 Starlette 自身 `Request.body()` 一致）：

```python
async def read_all(self) -> bytes:
    """Consume all body chunks and return them as a single blob."""
    if not self._chunks and not self._done:
        while True:
            message = await self._receive()
            body = message.get("body", b"")
            more_body = message.get("more_body", False)   # ← 新增：尊重 ASGI 流结束标志
            self._chunks.append(body)
            if not more_body:                              # ← 由 `if not body` 改为 `if not more_body`
                break
        self._done = True
    return b"".join(self._chunks)
```

要点：
- 只改这一处判断（`if not body:` → `if not more_body:`，并读出 `more_body`）。
- `__call__` 的 replay 逻辑（143–159 行）先调 `read_all()`，修复后自然正确；无需改动。
- 不要动 `AuditLogMiddleware.__call__`、`_extract_request_body`、`_redact` 等其他方法——
  根因仅在 `read_all` 的多读一次。

## 验证（opencode 改完需自测）
1. `ruff check src/core/middleware.py` 通过。
2. 起后端（`:8000`），在 loopback 上实测：
   - `curl -X POST http://127.0.0.1:8000/api/v1/auth/login -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin123456"}'` → **应返回 200 + JWT**（此前 ReadTimeout）。
   - GET `http://127.0.0.1:8000/health` → 200。
3. 确认审计仍生效：POST 后后端日志出现 `Audit: POST ... body=...`（说明 `read_all` 仍能读到完整 body）。
4. 全量回归：`pytest -q`（重点 `tests/test_core_offline.py` / 中间件相关用例；如项目有 audit 测试一并跑）。

## 不改动
- 不动其他中间件（RequestID/RequestLogging/TraceContext/CORS/csrf/SecurityHeaders/ServerHeader）。
- 不改路由、认证逻辑、数据库结构。

## 参考
- 复现脚本：`repro-buggy.py`（当前 `_BodyBuffer`，loopback 卡 POST）
- 验证脚本：`repro-fixed.py`（尊重 `more_body`，POST/GET 均好）
- 诊断启动器：`run-mw.py`（按名加载中间件子集做二分定位）
