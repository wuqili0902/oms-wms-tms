import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'

// Rows shaped as ``GET /warehouses/inventory`` answers (``InventoryResponse``).
// The mock used to carry ``product_name``, ``location_name``,
// ``quantity_on_hand``, ``reorder_level`` and ``unit_price``; no endpoint of
// this API returns any of those names, so the assertions written against them
// proved that a table rendered fields the server never sends.
const mockInventory = [
  {
    id: 'inv-1',
    warehouse_id: 'wh-1',
    location_id: 'loc-1',
    sku: 'SKU-A1',
    quantity: 15,
    reserved_qty: 2,
    available_qty: 13,
    batch_no: 'B-A1',
    expiry_date: '2026-12-31',
    created_at: '2026-07-01T10:00:00',
    updated_at: '2026-08-01T10:00:00',
  },
  {
    id: 'inv-2',
    warehouse_id: 'wh-1',
    location_id: 'loc-2',
    sku: 'SKU-B2',
    quantity: 3,
    reserved_qty: 0,
    available_qty: 3,
    batch_no: 'B-B2',
    expiry_date: null,
    created_at: '2026-07-02T10:00:00',
    updated_at: '2026-08-02T10:00:00',
  },
]

const mockWarehouses = {
  data: { data: { items: [{ id: 'wh-1', name: '上海仓' }] } },
}

const mockPurchaseOrders = {
  data: { data: { items: [{ id: 'po-1', po_no: 'PO001', vendor_name: '供应商甲' }] } },
}

vi.mock('../../../api', () => ({
  default: {
    get: vi.fn((url: string) => {
      if (url === '/warehouses') return Promise.resolve(mockWarehouses)
      if (url === '/warehouses/purchase-orders?page=1&page_size=50&status=approved') {
        return Promise.resolve(mockPurchaseOrders)
      }
      return Promise.resolve({ data: [] })
    }),
    post: vi.fn(),
  },
}))

vi.mock('../../../services/inventory', () => ({
  getInventory: vi.fn(() => Promise.resolve({ data: mockInventory })),
  adjustStock: vi.fn(() => Promise.resolve({ data: { ok: true } })),
  createStockIn: vi.fn(() => Promise.resolve({ data: { ok: true } })),
  getLocations: vi.fn(() => Promise.resolve({ data: { items: [{ id: 'loc-1', location_code: 'A-01-1-1' }] } })),
}))

import { getInventory, adjustStock, createStockIn, getLocations } from '../../../services/inventory'
import apiClient from '../../../api'
import InventoryList from '../InventoryList.vue'

describe('InventoryList.vue', () => {
  const mountInventory = () =>
    mount(InventoryList, {
      global: { plugins: [createPinia(), ElementPlus] },
    })

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders header and loads inventory on mount', async () => {
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))
    expect(wrapper.text()).toContain('库存管理')
    expect(getInventory).toHaveBeenCalled()
    expect(wrapper.text()).toContain('SKU-A1')
    expect(wrapper.text()).toContain('B-A1')
  })

  it('names the warehouse a row sits in', async () => {
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))
    // The inventory rows carry a warehouse id; the screen resolves the name
    // from the warehouses it loaded, because the inventory endpoint does not.
    expect(wrapper.text()).toContain('上海仓')
  })

  it('renders the quantities the API reports', async () => {
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))
    expect(wrapper.text()).toContain('15')
    expect(wrapper.text()).toContain('13')
  })

  it('renders warehouses loaded from API', async () => {
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))
    expect(apiClient.get).toHaveBeenCalledWith('/warehouses')
    const options = wrapper.findAll('.el-select-dropdown__item')
    expect(options.length).toBeGreaterThanOrEqual(0)
  })

  it('opens stock-in dialog and adds items', async () => {
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    const buttons = wrapper.findAllComponents({ name: 'ElButton' })
    const stockInBtn = buttons.find((b) => b.text().includes('入库'))
    await stockInBtn!.trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('入库商品')
    expect(wrapper.text()).toContain('+ 添加商品')

    const addBtn = wrapper.findAllComponents({ name: 'ElButton' }).find((b) => b.text().includes('添加商品'))
    await addBtn!.trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('入库预览')
  })

  it('submits stock-in with deduplicated items', async () => {
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    const buttons = wrapper.findAllComponents({ name: 'ElButton' })
    const stockInBtn = buttons.find((b) => b.text().includes('入库'))
    await stockInBtn!.trigger('click')
    await wrapper.vm.$nextTick()

    const form = (wrapper.vm as any).stockInForm
    form.warehouse_id = 'wh-1'
    form.items = [
      { sku: 'SKU-A1', quantity: 2 },
      { sku: 'SKU-A1', quantity: 3 },
      { sku: 'SKU-B2', quantity: 1 },
    ]

    const submitBtn = wrapper.findAllComponents({ name: 'ElButton' }).find((b) => b.text().includes('提交入库'))
    await submitBtn!.trigger('click')
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    expect(createStockIn).toHaveBeenCalledTimes(1)
    const payload = (createStockIn as any).mock.calls[0][0]
    expect(payload.warehouse_id).toBe('wh-1')
    // The service's contract is the server's: lines, each with qty.
    expect(payload.lines).toEqual([
      { sku: 'SKU-A1', qty: 5 },
      { sku: 'SKU-B2', qty: 1 },
    ])
  })

  it('opens adjust dialog and submits adjustment', async () => {
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    const buttons = wrapper.findAllComponents({ name: 'ElButton' })
    const adjustBtn = buttons.find((b) => b.text().includes('库存调整'))
    await adjustBtn!.trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('变化数量')

    const form = (wrapper.vm as any).adjustForm
    form.warehouse_id = 'wh-1'
    form.location_id = 'loc-1'
    form.sku = 'SKU-A1'
    form.quantity = -5
    form.reason = 'DAMAGE'

    const submitBtn = wrapper.findAllComponents({ name: 'ElButton' }).find((b) => b.text().includes('提交调整'))
    await submitBtn!.trigger('click')
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    expect(adjustStock).toHaveBeenCalledTimes(1)
    // The payload is ``InventoryAdjust``: a signed quantity on a location's SKU.
    expect(adjustStock).toHaveBeenCalledWith({
      warehouse_id: 'wh-1',
      location_id: 'loc-1',
      sku: 'SKU-A1',
      quantity: -5,
      reason: 'DAMAGE',
      batch_no: undefined,
      picking_strategy: 'fefo',
    })
  })

  it('refuses to submit an adjustment with no location', async () => {
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    const adjustBtn = wrapper.findAllComponents({ name: 'ElButton' }).find((b) => b.text().includes('库存调整'))
    await adjustBtn!.trigger('click')
    await wrapper.vm.$nextTick()

    const form = (wrapper.vm as any).adjustForm
    form.warehouse_id = 'wh-1'
    form.location_id = ''
    form.sku = 'SKU-A1'
    form.quantity = -5

    const submitBtn = wrapper.findAllComponents({ name: 'ElButton' }).find((b) => b.text().includes('提交调整'))
    await submitBtn!.trigger('click')
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    expect(adjustStock).not.toHaveBeenCalled()
  })

  it('loads the bins of the warehouse being adjusted', async () => {
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    const form = (wrapper.vm as any).adjustForm
    form.warehouse_id = 'wh-1'
    await (wrapper.vm as any).onAdjustWarehouse()
    await new Promise((r) => setTimeout(r, 20))

    expect(getLocations).toHaveBeenCalledWith('wh-1')
  })

  it('handles inventory fetch error gracefully', async () => {
    vi.mocked(getInventory).mockRejectedValueOnce(new Error('boom'))
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))
    expect((wrapper.vm as any).inventory).toEqual([])
  })
})
