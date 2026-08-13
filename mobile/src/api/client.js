/**
 * API client for OMS/WMS backend.
 * Handles JWT token storage, request signing, and error normalization.
 */
import * as SecureStore from "expo-secure-store";
import AsyncStorage from "@react-native-async-storage/async-storage";

const TOKEN_KEY = "auth_token";
const BASE_URL = __DEV__
  ? "http://10.0.2.2:8000/api/v1"   // Android emulator → host
  : "https://api.oms.example.com/api/v1";

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

// ── HTTP helpers with offline-queue support ────────────────────────────────

async function request(method, path, body = null) {
  const token = await getToken();
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);

  let resp;
  try {
    resp = await fetch(`${BASE_URL}${path}`, opts);
  } catch (err) {
    // Network failure. Queue mutations (POST/PUT/PATCH/DELETE) for later sync.
    const isMutation = method !== "GET";
    if (isMutation) {
      await enqueueMutation(path, method, body);
    }
    throw { ...err, queued: isMutation, offline: true };
  }

  const data = await resp.json().catch(() => null);

  if (!resp.ok) {
    const msg =
      data?.detail || (Array.isArray(data?.detail) ? data.detail[0]?.msg : "Request failed");
    throw { status: resp.status, message: msg, data };
  }
  return data;
}

let _mutCount = 0;

/** Lightweight mutation queue entry. */
async function enqueueMutation(path, method, body) {
  const raw = await AsyncStorage.getItem("pda_mutations");
  const entries = JSON.parse(raw ?? "[]");
  entries.push({
    id: `m_${++_mutCount}_${Date.now()}`,
    path,
    method,
    body,
    created_at: new Date().toISOString(),
    synced_at: null,
  });
  await AsyncStorage.setItem("pda_mutations", JSON.stringify(entries));
}

/** Re-queue all pending mutations and return count. */
export async function syncMutations() {
  const raw = await AsyncStorage.getItem("pda_mutations");
  if (!raw) return 0;
  const entries = JSON.parse(raw);
  let synced = 0;
  for (const m of entries) {
    try {
      await request(m.method, m.path, m.body);
      m.synced_at = new Date().toISOString();
      synced++;
    } catch { /* keep unsynced */ }
  }
  await AsyncStorage.setItem(
    "pda_mutations",
    JSON.stringify(entries.filter(e => !e.synced_at))
  );
  return synced;
}

// ── WebSocket manager (PDA real-time push) ────────────────────────────────

class PdaSocketManager {
  constructor() {
    this._callbacks = new Set();
    this._ws = null;
    this._reconnectTimer = null;
  }

  connect(deviceId, url = "ws://10.0.2.2:8000/pda/ws?client_id=") {
    if (this._ws?.readyState === WebSocket.OPEN) return;
    const ws = new WebSocket(url + encodeURIComponent(deviceId));
    this._ws = ws;

    ws.onmessage = ({ data }) => {
      try {
        const msg = JSON.parse(data);
        this._callbacks.forEach(cb => cb(msg));
      } catch {}
    };
    ws.onerror = () => this.scheduleReconnect(deviceId, url);
    ws.onclose = () => this.scheduleReconnect(deviceId, url);
  }

  send(payload) {
    if (this._ws?.readyState === WebSocket.OPEN) this._ws.send(JSON.stringify(payload));
  }

  scheduleReconnect(deviceId, url) {
    clearTimeout(this._reconnectTimer);
    // Exponential backoff: 1s → 2s → 4s → 8s (max 30s)
    const delay = Math.min(1000 * Math.pow(2, this._retryCount++), 30000);
    this._reconnectTimer = setTimeout(() => {
      this.connect(deviceId, url);
    }, delay);
  }

  onMessage(cb) { this._callbacks.add(cb); return () => this._callbacks.delete(cb); }

  disconnect() { clearTimeout(this._reconnectTimer); if (this._ws) this._ws.close(); }
}

export const pdaSocket = new PdaSocketManager();

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

  updateOrderStatus: (id, status) =>
    request("PATCH", `/orders/${id}/status`, { status }),

  // ── Inventory ────────────────────────────────────────────────────────────
  queryInventory: (params = {}) => {
    const qs = Object.entries(params)
      .filter(([_, v]) => v != null)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join("&");
    return request("GET", `/warehouses/inventory${qs ? "?" + qs : ""}`);
  },

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

  receiveGoods: (poId, data) =>
    request("POST", `/purchase-orders/${poId}/receive`, data),

  // ── Transfer Orders ──────────────────────────────────────────────────────
  createTransferOrder: (data) =>
    request("POST", "/warehouses/transfers", data),

  listTransferOrders: () =>
    request("GET", "/warehouses/transfers"),

  // ── PDA Sync / Offline Queue ────────────────────────────────────────────
  registerDevice: (deviceData) =>
    request("POST", `/pda/mutations`, deviceData),

  heartbeat: () =>
    request("GET", `/pda/sync`),
};
