import apiClient from '../api'

// ═══════════════ Inventory / Stock In ═══════════════
//
// The paths here are the paths ``src/main.py`` mounts.  This file used to call
// ``/inventory``, ``/inventory/adjust`` and ``/inventory/movements``, and the
// WMS router carries the prefix ``/warehouses`` — so every one of them was a
// 404, and 库存管理 opened on an empty table with 库存调整 never reaching the
// server at all.  The payload types are the request models in
// ``src/wms/schemas.py`` / ``src/wms/schemas.py`` (``InventoryAdjust``,
// ``TransferOrderCreate``), not a shape invented for the screen.

/** GET /warehouses/inventory — query inventory rows (``InventoryResponse``) */
export function getInventory(params?: Record<string, string>) {
  return apiClient.get('/warehouses/inventory', { params })
}

/** POST /warehouses/inventory/adjust — move stock on a location's SKU.
 *
 * ``quantity`` is signed: positive lands stock, negative takes it.  A take is
 * pulled from batches by ``picking_strategy`` (FEFO by default), and the batch
 * the goods were scanned on is sent as ``batch_no`` — dropping it used to land
 * the movement on the ``DEFAULT`` batch.
 */
export function adjustStock(payload: {
  warehouse_id: string
  location_id: string
  sku: string
  quantity: number
  reason?: string
  batch_no?: string
  expiry_date?: string
  manufacturing_date?: string
  picking_strategy?: 'fefo' | 'fifo' | 'batch'
}) {
  return apiClient.post('/warehouses/inventory/adjust', payload)
}

/** GET /warehouses/inventory/movements — stock movement history */
export function getMovements(warehouse_id: string) {
  return apiClient.get('/warehouses/inventory/movements', { params: { warehouse_id } })
}

/** GET /warehouses/{wh_id}/locations — the bins an adjustment can name */
export function getLocations(warehouse_id: string) {
  return apiClient.get(`/warehouses/${warehouse_id}/locations`, { params: { page: 1, page_size: 200 } })
}

// ═══════════════ Stock In (Purchase Receipt) ═══════════════

/** POST /stock-in — create a receipt.
 *
 * The documented body: the ``{"data": {...}}`` envelope the stock endpoints read,
 * ``lines`` for the line array, ``ref_no`` for the external document number.
 * This function used to post a flat ``{ po_id, items }`` payload, which reached
 * ``data["warehouse_id"]`` on an empty dict (a 500), and ``po_id`` names no
 * column of ``stock_in`` — it is now refused by name instead of dropped, so the
 * purchase order number goes in ``ref_no``.
 */
export function createStockIn(payload: {
  warehouse_id: string
  type?: 'PURCHASE' | 'RETURN' | 'TRANSFER_IN' | 'ADJUSTMENT'
  ref_no?: string
  supplier_id?: string
  lines: Array<{ sku: string; qty: number; batch_no?: string }>
}) {
  return apiClient.post('/stock-in', { data: payload })
}

/** GET /stock-in — list stock in records */
export function getStockIn(params: { page: number; page_size?: number }) {
  return apiClient.get('/stock-in', { params })
}

// ═══════════════ Transfer Order (库存调拨) ═══════════════

/** POST /warehouses/transfers — create a transfer.
 *
 * Both ends are required and each is a warehouse — an id or a code.  They used
 * to be sent to ``/transfer-orders``, a path the API does not mount, and the
 * service read the source out of ``source_location`` only: a body naming
 * ``source_warehouse_id`` was filed with no source, and that same value was
 * reused as the destination.  ``PATCH /transfer-orders/{id}/status`` is gone
 * from this file for the same reason: the route does not exist.  The API
 * creates and lists transfer orders and nothing else, so a transfer order keeps
 * ``status = DRAFT`` — confirming, shipping and receiving a transfer are not
 * implemented anywhere, and a screen that offered a status change was writing
 * to a 404.
 */
export function createTransferOrder(payload: {
  source_warehouse_id: string
  target_warehouse_id: string
  type?: 'SKU' | 'LOCATION' | 'WAREHOUSE'
  ref_no?: string
  remarks?: string
  lines: Array<{ sku?: string; sku_id?: string; quantity: number }>
}) {
  return apiClient.post('/warehouses/transfers', payload)
}

/** GET /warehouses/transfers — list transfer orders (with their lines) */
export function getTransferOrders(params?: { warehouse_id?: string }) {
  return apiClient.get('/warehouses/transfers', { params })
}
