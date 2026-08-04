import apiClient from '../api'

// ═══════════════ Inventory / Stock In ═══════════════

/** GET /inventory — query inventory items */
export function getInventory(params?: Record<string, string>) {
  return apiClient.get('/inventory', { params })
}

/** POST /inventory/adjust — stock adjustment (add or subtract) */
export function adjustStock(payload: {
  item_id: string
  quantity_change: number
  reason?: string
  reference_no?: string
}) {
  return apiClient.post('/inventory/adjust', payload)
}

/** GET /inventory/movements — stock movement history */
export function getMovements(warehouse_id: string) {
  return apiClient.get('/inventory/movements', { params: { warehouse_id } })
}

// ═══════════════ Stock In (Purchase Receipt) ═══════════════

/** POST /stock-in — receive stock against a purchase order */
export function createStockIn(payload: {
  po_id?: string
  items: Array<{ sku: string; quantity: number }>
  warehouse_id: string
}) {
  return apiClient.post('/stock-in', payload)
}

/** GET /stock-in — list stock in records */
export function getStockIn(params: { page: number; page_size?: number }) {
  return apiClient.get('/stock-in', { params })
}

// ═══════════════ Transfer Order (internal warehouse transfer) ═══════════════

/** POST /transfer-orders — create a transfer */
export function createTransferOrder(payload: {
  source_warehouse_id: string
  target_warehouse_id: string
  items: Array<{ sku: string; quantity: number }>
}) {
  return apiClient.post('/transfer-orders', payload)
}

/** GET /transfer-orders — list transfer orders */
export function getTransferOrders(params: { page?: number; page_size?: number }) {
  return apiClient.get('/transfer-orders', { params })
}

/** PATCH /transfer-orders/{id}/status — update status (PENDING, IN_TRANSIT, DELIVERED, etc.) */
export function updateTransferOrderStatus(id: string, status: string) {
  return apiClient.patch(`/transfer-orders/${id}/status`, { status })
}
