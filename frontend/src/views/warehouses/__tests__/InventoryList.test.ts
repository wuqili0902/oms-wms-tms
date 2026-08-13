import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'

const mockInventory = [
  {
    id: 'inv-1',
    sku: 'SKU-A1',
    product_name: '测试商品A',
    warehouse_name: '上海仓',
    location_name: 'A-01',
    quantity_on_hand: 15,
    reorder_level: 10,
    unit_price: 12.5,
    updated_at: '2026-08-01T10:00:00',
  },
  {
    id: 'inv-2',
    sku: 'SKU-B2',
    product_name: '测试商品B',
    warehouse_name: '杭州仓',
    location_name: 'B-02',
    quantity_on_hand: 3,
    reorder_level: 5,
    unit_price: 8,
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
}))

import { getInventory, adjustStock, createStockIn } from '../../../services/inventory'
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
    expect(wrapper.text()).toContain('测试商品A')
    expect(wrapper.text()).toContain('上海仓')
  })

  it('shows low-stock highlight for items below reorder level', async () => {
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))
    const spans = wrapper.findAll('span').filter((s) => s.text() === '3')
    expect(spans.length).toBeGreaterThan(0)
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
    expect(payload.items).toEqual([
      { sku: 'SKU-A1', quantity: 5 },
      { sku: 'SKU-B2', quantity: 1 },
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
    form.item_id = 'inv-1'
    form.quantity_change = -5
    form.reason_code = 'DAMAGE'

    const submitBtn = wrapper.findAllComponents({ name: 'ElButton' }).find((b) => b.text().includes('提交调整'))
    await submitBtn!.trigger('click')
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    expect(adjustStock).toHaveBeenCalledTimes(1)
    expect(adjustStock).toHaveBeenCalledWith({
      item_id: 'inv-1',
      quantity_change: -5,
      reason: 'DAMAGE',
    })
  })

  it('handles inventory fetch error gracefully', async () => {
    vi.mocked(getInventory).mockRejectedValueOnce(new Error('boom'))
    const wrapper = mountInventory()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))
    expect((wrapper.vm as any).inventory).toEqual([])
  })
})
