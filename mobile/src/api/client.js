/**
 * API client for OMS/WMS backend.
 * Handles JWT token storage, request signing, and error normalization.
 */
import * as SecureStore from "expo-secure-store";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { AppState } from "react-native";

import { createOfflineQueue } from "./offline";
import { createPdaSocket } from "./socket";

const TOKEN_KEY = "auth_token";

// The API is not one prefix.  src/main.py mounts the REST routers under
// /api/v1 but mounts the PDA router (and its WebSocket) at the root, so a
// phone that assumes "/api/v1/…" everywhere calls /api/v1/pda/mutations — a
// 404.  For a liveness probe that is not cosmetic: the probe guards every
// replay, so a 404 probe means the queue never drains and the banner just
// reports work that will never leave the device.
const API_ROOT = __DEV__
  ? "http://10.0.2.2:8000"          // Android emulator → host
  : "https://api.oms.example.com";
const API_BASE = `${API_ROOT}/api/v1`;
const PDA_BASE = `${API_ROOT}/pda`;
// The socket shares the PDA mount, but a socket URL is not an HTTP URL with
// its scheme still intact: over HTTPS the phone must dial wss://, and a ws://
// dial fails the handshake before it ever proves the device is online — which
// is exactly the signal the offline queue waits for.
// https:// … becomes wss:// … by the same substitution.
const WS_BASE = `${API_ROOT.replace(/^http/, "ws")}/pda/ws`;

const DEVICE_KEY = "pda_device_id";

/**
 * Stable id for this install.
 *
 * Both the socket and the server-side mutation queue key on it, so it has to
 * outlive restarts: an id minted per launch scatters one PDA's work across as
 * many devices as it has rebooted, and nothing downstream can tell that the
 * scans came from the same handheld.
 */
export async function getDeviceId() {
  const stored = await AsyncStorage.getItem(DEVICE_KEY);
  if (stored) return stored;
  const created = `pda-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  try {
    await AsyncStorage.setItem(DEVICE_KEY, created);
  } catch {
    // Storage failed: this call still needs an id to identify the socket with,
    // it just will not be recognised on the next launch.
  }
  return created;
}

/** HTTP statuses worth replaying later: the server, not the payload, failed. */
const isRetryableStatus = (status) =>
  status == null || status >= 500 || status === 408 || status === 429;

/** Listeners notified whenever the offline queue changes (banner, badges). */
const _queueListeners = new Set();
const _queueStats = { total: 0, pending: 0, retryable: 0, failed: 0, oldest: null, nextAttemptAt: 0 };

// ── Token management ───────────────────────────────────────────────────────

export async function getToken() {
  return SecureStore.getItemAsync(TOKEN_KEY);
}

export async function setToken(token) {
  return SecureStore.setItemAsync(TOKEN_KEY, token);
}

export async function clearToken() {
  return SecureStore.deleteItemAsync(TOKEN_KEY);
}

// ── Offline mutation queue ─────────────────────────────────────────────────

const offlineQueue = createOfflineQueue({
  storage: AsyncStorage,
  onQueueChanged: (stats) => {
    Object.assign(_queueStats, stats);
    _queueListeners.forEach((cb) => {
      try { cb({ ..._queueStats }); } catch { /* a listener must not break the queue */ }
    });
  },
  // Replays bypass request(): request() queues what it fails to send, so a
  // failed replay would enqueue a second copy of the mutation being replayed.
  send: (entry) =>
    rawRequest(entry.method, entry.path, entry.body, {
      idempotencyKey: entry.idempotency_key,
    }),
});

// ── HTTP helpers ───────────────────────────────────────────────────────────

/**
 * One attempt at a request. Throws `{ status, message, data }` when the server
 * answered with an error status, and `{ offline: true }` when we never reached
 * it — callers need both, because "the server said no" is permanent and "we
 * couldn't connect" is not.
 */
async function rawRequest(method, path, body = null, { idempotencyKey = null, base = API_BASE } = {}) {
  const token = await getToken();
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  // The same key on every attempt is what lets the server recognise a replay:
  // src/core/idempotency.py answers the second delivery with the first response
  // instead of running the mutation again.  The FIFO barrier stays — the guard
  // deduplicates a key, it does not order two different ones, and it is absent
  // whenever Redis is down.
  if (idempotencyKey) headers["X-Idempotency-Key"] = idempotencyKey;

  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);

  let resp;
  try {
    resp = await fetch(`${base}${path}`, opts);
  } catch (err) {
    throw { message: err?.message || "Network request failed", offline: true };
  }

  const data = await resp.json().catch(() => null);

  if (!resp.ok) {
    // Two error shapes reach the phone: FastAPI's own {"detail": ...} (validation)
    // and this API's {"success": false, "error": {"code", "message"}} envelope.
    // Reading only `detail` showed every backend rejection as "Request failed".
    const detail = data?.error?.message ?? data?.detail ?? data?.message;
    const message =
      typeof detail === "string" ? detail
      : Array.isArray(detail) ? (detail[0]?.msg ?? detail[0]?.detail ?? "Request failed")
      : "Request failed";
    throw { status: resp.status, code: data?.error?.code, message, data };
  }
  return data;
}

/**
 * Send a request, queueing the mutations that a later replay can make good.
 *
 * A queued mutation still throws — the screen has to tell the operator the
 * count they just typed has not reached the server yet — but the error carries
 * `queued: true` so a screen can say "stored offline" instead of "failed".
 */
async function request(method, path, body = null, { base = API_BASE, queueable = true } = {}) {
  try {
    return await rawRequest(method, path, body, { base });
  } catch (err) {
    // `queueable: false` for the calls aimed at another mount (the root-level
    // /pda endpoints): the replay path stores API_BASE-relative paths, so a
    // queued /pda call would be replayed against the wrong prefix and land as
    // a permanently rejected mutation.
    const worthReplaying =
      queueable && method !== "GET" && (err.offline || isRetryableStatus(err.status));
    if (!worthReplaying) throw err;

    try {
      await offlineQueue.enqueue({ path, method, body });
    } catch (queueErr) {
      // MAX_PENDING reached. Handing back silence here would lose the operator's
      // scan without telling them, so this one surfaces as a plain failure.
      throw {
        ...err,
        queued: false,
        message: `离线待同步队列已满，请先同步后再操作（${queueErr?.message ?? "queue full"}）`,
      };
    }

    throw {
      ...err,
      queued: true,
      offline: true,
      message: err.offline
        ? "离线已保存：将在网络恢复后自动同步"
        : "服务器暂时不可用：已加入待同步队列",
    };
  }
}

/**
 * A call aimed at the root-mounted PDA router.
 *
 * Two things differ from a normal request.  The base is /pda rather than
 * /api/v1, and nothing here is queued: the queue replays paths relative to
 * API_BASE, so a queued /pda call would come back under the wrong prefix and
 * be filed as a permanently rejected mutation — the queue deleting a scan the
 * server never even saw.
 */
function pdaRequest(method, path, body = null) {
  return request(method, path, body, { base: PDA_BASE, queueable: false });
}

/**
 * Replay the queue, but only after a probe proves we are online and logged in.
 *
 * Both halves matter. Flushing into a dead link spends the attempts each entry
 * is allowed before it is dropped, and an expired token answers 401 — a 4xx the
 * queue counts as permanent, which would discard queued scans that were never
 * actually rejected.
 */
async function flushOfflineQueue() {
  await api.heartbeat();
  return await offlineQueue.flush();
}

/** Replay queued mutations. Kept under the pre-P1-17 name for call sites. */
export async function syncMutations() {
  try {
    const result = await flushOfflineQueue();
    return result.synced;
  } catch {
    return 0;
  }
}

export function getOfflineStats() {
  return { ..._queueStats };
}

/** Subscribe to queue changes (banner counts). Returns an unsubscribe function. */
export function subscribeOffline(cb) {
  _queueListeners.add(cb);
  try { cb({ ..._queueStats }); } catch { /* ignore listener errors */ }
  return () => _queueListeners.delete(cb);
}

/** "立即同步": ignore backoff timers and try everything now. */
export async function retryOfflineNow() {
  await offlineQueue.retryNow();
  return await flushOfflineQueue();
}

/** Re-arm mutations the queue had given up on (4xx / attempt ceiling). */
export async function retryOfflineFailed() {
  await offlineQueue.retryFailed();
  return await flushOfflineQueue();
}

export function listOfflineMutations({ includeFailed = true } = {}) {
  return offlineQueue.list({ includeFailed });
}

export async function discardOfflineMutation(id) {
  return await offlineQueue.discard(id);
}

/**
 * Drop everything the queue gave up on.
 *
 * Deliberately destructive: these are mutations that were rejected (4xx) or
 * retried until the attempt ceiling, so dropping them means the physical scan
 * never reached the system.  The banner only offers it once that is stated.
 */
export async function discardFailedOffline() {
  const all = await offlineQueue.list({ includeFailed: true });
  const failed = all.filter((entry) => entry.status === "failed");
  for (const entry of failed) await offlineQueue.discard(entry.id);
  return failed.length;
}

export async function clearOfflineQueue() {
  await offlineQueue.clear();
}

/**
 * Keep the queue drained without a connectivity library.
 *
 * Triggers: the app returning to the foreground, the PDA socket reconnecting
 * (which is itself proof of reachability), and a slow heartbeat tick that only
 * does work when something is actually queued.
 */
async function pumpOfflineQueue() {
  try {
    if ((await offlineQueue.count()) === 0) return null;
    return await flushOfflineQueue();
  } catch {
    return null; // still offline, or logged out — the entries keep their backoff
  }
}

export function startOfflineAutoSync({ probeIntervalMs = 20000 } = {}) {
  let stopped = false;

  const timer = setInterval(() => {
    if (!stopped) pumpOfflineQueue();
  }, probeIntervalMs);

  const subscription = AppState.addEventListener("change", (state) => {
    if (!stopped && state === "active") pumpOfflineQueue();
  });

  return () => {
    stopped = true;
    clearInterval(timer);
    subscription?.remove?.();
  };
}

// ── WebSocket manager (PDA real-time push) ────────────────────────────────
//
// The channel itself lives in api/socket.js.  What is interesting about it —
// the reconnect ladder, the token gate, the ping deadline — is plain
// JavaScript, and keeping it free of React Native imports is what lets
// scripts/test_pda_socket.mjs drive all of it without a simulator.  All the
// socket needs from this module is a token and a reason to drain the queue.

export const pdaSocket = createPdaSocket({
  getToken,
  // A live socket is proof the network is back, which is the cheapest possible
  // trigger for replaying whatever the PDA queued up.
  onOnline: () => pumpOfflineQueue(),
  url: WS_BASE,
});

/** The link state a screen can show: online | connecting | offline. */
export function getConnectionState() {
  return pdaSocket.getState();
}

export function subscribeConnection(cb) {
  return pdaSocket.subscribeState(cb);
}

// ── API methods ────────────────────────────────────────────────────────────

export const api = {
  // ── Auth ─────────────────────────────────────────────────────────────────
  login: (username, password) =>
    request("POST", "/auth/login", { username, password }),

  register: (username, email, password) =>
    request("POST", "/auth/register", { username, email, password }),

  me: () => request("GET", "/auth/me"),

  // ── Orders ───────────────────────────────────────────────────────────────
  listOrders: (page = 1, pageSize = 20) =>
    request("GET", `/orders?page=${page}&page_size=${pageSize}`),

  getOrder: (id) => request("GET", `/orders/${id}`),

  createOrder: (data) => request("POST", "/orders", data),

  // PUT, not PATCH: src/oms/router.py serves PUT /orders/{id}/status, and a
  // PATCH here answered 405 — a 4xx the offline queue files as permanently
  // rejected, so an order status set offline was dropped rather than retried.
  updateOrderStatus: (id, status) =>
    request("PUT", `/orders/${encodeURIComponent(id)}/status`, { status }),

  // ── Warehouses ───────────────────────────────────────────────────────────
  /** Warehouses the operator can work in — the PDA screens all need one. */
  listWarehouses: (page = 1, pageSize = 50) =>
    request("GET", `/warehouses?page=${page}&page_size=${pageSize}`),

  // ── Inventory ────────────────────────────────────────────────────────────
  /** Locations of a warehouse — used to turn a shelf label into a location id. */
  listLocations: (warehouseId) =>
    request("GET", `/warehouses/${encodeURIComponent(warehouseId)}/locations`),

  queryInventory: (params = {}) => {
    const qs = Object.entries(params)
      .filter(([_, v]) => v != null)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join("&");
    return request("GET", `/warehouses/inventory${qs ? "?" + qs : ""}`);
  },

  /**
   * Quantity adjustment — positive in, negative out.
   *
   * `batch_no` / `expiry_date` are what keep a FEFO warehouse honest: the
   * backend keys inventory by batch, so an adjustment that loses the batch the
   * operator scanned lands stock on the "DEFAULT" batch and the real batch
   * never expires on time.
   */
  adjustInventory: (data) =>
    request("POST", "/warehouses/inventory/adjust", data),

  adjustStockCount: (data) =>
    request("POST", "/warehouses/inventory/count/submit", data),

  // ── Picking ──────────────────────────────────────────────────────────────
  listPickingWaves: () =>
    request("GET", "/warehouses/picking-waves"),

  startPickingWave: (waveId) =>
    request("POST", `/warehouses/picking-waves/${waveId}/start`),

  completePickingWave: (waveId) =>
    request("POST", `/warehouses/picking-waves/${waveId}/complete`),

  // ── Barcode ──────────────────────────────────────────────────────────────
  generateBarcode: (data) =>
    request("POST", "/barcode/generate", data),

  validateBarcode: (gtin) =>
    request("POST", "/barcode/validate", { gtin }),

  recordScan: (data) =>
    request("POST", "/barcode/scan", data),

  // ── Packing / Shipments ──────────────────────────────────────────────────
  createPackingRecord: (data) =>
    request("POST", "/warehouses/packing", data),

  listShipments: (params = {}) => {
    const qs = Object.entries(params)
      .filter(([_, v]) => v != null)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
    return request("GET", `/warehouses/shipments${qs ? "?" + qs : ""}`);
  },

  shipPackage: (shipmentId) =>
    request("POST", `/warehouses/shipments/${shipmentId}/ship`),

  // ── Purchase Orders ──────────────────────────────────────────────────────
  listPurchaseOrders: (status = "pending") =>
    request("GET", `/warehouses/purchase-orders?status=${status}`),

  // The purchase-order routes live under /warehouses (src/wms/router.py); a
  // bare /purchase-orders path 404s, which the offline queue would record as a
  // permanently rejected receipt.
  receiveGoods: (poId, data) =>
    request("POST", `/warehouses/purchase-orders/${poId}/receive`, data),

  // ── Transfer Orders ──────────────────────────────────────────────────────
  createTransferOrder: (data) =>
    request("POST", "/warehouses/transfers", data),

  listTransferOrders: () =>
    request("GET", "/warehouses/transfers"),

  // ── PDA Sync / Offline Queue ────────────────────────────────────────────
  /**
   * Ask the server to drain *its* pending-mutation queue (POST /pda/sync).
   *
   * This is not the phone's queue — that one replays through
   * retryOfflineNow().  The old name for this method was `registerDevice`, and
   * there is no device-registration endpoint to register with: POST
   * /pda/mutations hands the server a mutation to apply on its own schedule.
   */
  syncServerMutations: () => pdaRequest("POST", "/sync"),

  /** Hand the server a mutation to apply later, on the server's clock. */
  enqueueMutation: (mutation) => pdaRequest("POST", "/mutations", mutation),

  /** Mutations the server is still holding for this fleet. */
  listServerMutations: (limit = 50) => pdaRequest("GET", `/mutations?limit=${limit}`),

  /**
   * Liveness probe, and the reason the /pda mount matters.
   *
   * flushOfflineQueue() probes before it replays anything.  A probe aimed at
   * /api/v1/pda/mutations 404s, the flush never runs, and the banner goes on
   * reporting queued scans that will never leave the device — which reads to
   * an operator as "the app lost my numbers".
   */
  heartbeat: () => pdaRequest("GET", "/mutations?limit=1"),
};
