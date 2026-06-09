/**
 * API client for OMS/WMS backend.
 * Handles JWT token storage, request signing, and error normalization.
 */
import * as SecureStore from "expo-secure-store";

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

// ── HTTP helpers ───────────────────────────────────────────────────────────

async function request(method, path, body = null) {
  const token = await getToken();
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);

  const resp = await fetch(`${BASE_URL}${path}`, opts);
  const data = await resp.json();

  if (!resp.ok) {
    const msg =
      data.detail || (Array.isArray(data.detail) ? data.detail[0]?.msg : "Request failed");
    throw { status: resp.status, message: msg, data };
  }
  return data;
}

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

  adjustInventory: (data) =>
    request("POST", "/warehouses/inventory/adjust", data),

  // ── Barcode ──────────────────────────────────────────────────────────────
  generateBarcode: (data) =>
    request("POST", "/barcode/generate", data),

  validateBarcode: (gtin) =>
    request("POST", "/barcode/validate", { gtin }),

  recordScan: (data) =>
    request("POST", "/barcode/scan", data),
};
