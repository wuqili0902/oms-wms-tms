import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createRouter, createMemoryHistory } from 'vue-router'

const mockOrders = {
  data: {
    data: {
      items: [
        {
          id: 'ord-1',
          transport_no: 'TPL-20260813-ABCD',
          driver_name: '王司机',
          plate_no: '沪A12345',
          status: 'in_transit',
          created_at: '2026-08-13T10:00:00',
        },
      ],
      total: 1,
    },
  },
}

vi.mock('../../../api', () => ({
  default: {
    get: vi.fn((url: string) => {
      if (url.startsWith('/transport-orders')) return Promise.resolve(mockOrders)
      if (url.includes('/tracking')) return Promise.resolve({ data: [] })
      if (url.startsWith('/route-plans/')) return Promise.resolve({ data: { id: 'plan-1', status: 'pending' } })
      return Promise.resolve({ data: [] })
    }),
    post: vi.fn((url: string) => {
      if (url.includes('/route-plans')) return Promise.resolve({ data: { data: { id: 'plan-1' } } })
      if (url === '/freight-estimate') return Promise.resolve({ data: { data: { total_fee: 25.5 } } })
      return Promise.resolve({ data: { id: 'new-1' } })
    }),
    put: vi.fn(() => Promise.resolve({ data: { ok: true } })),
  },
}))

import apiClient from '../../../api'
import TransportOrderList from '../TransportOrderList.vue'

describe('TransportOrderList.vue', () => {
  let router: any

  beforeEach(() => {
    vi.clearAllMocks()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/transport/:id', name: 'TransportOrderDetail', component: { template: '<div />' } }],
    })
  })

  const mountList = () =>
    mount(TransportOrderList, {
      global: { plugins: [createPinia(), ElementPlus, router] },
    })

  it('renders header and loads transport orders on mount', async () => {
    const wrapper = mountList()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))
    expect(wrapper.text()).toContain('运输管理')
    expect(apiClient.get).toHaveBeenCalledWith(expect.stringContaining('/transport-orders'))
    expect(wrapper.text()).toContain('TPL-20260813-ABCD')
    expect(wrapper.text()).toContain('王司机')
    expect(wrapper.text()).toContain('在途')
  })

  it('maps status to Chinese label and tag type', async () => {
    const wrapper = mountList()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))
    expect(wrapper.text()).toContain('在途')
    const vm = wrapper.vm as any
    expect(vm.statusLabel('delivered')).toBe('已签收')
    expect(vm.statusType('exception')).toBe('danger')
  })

  it('builds create payload from form fields', async () => {
    const wrapper = mountList()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    const vm = wrapper.vm as any
    vm.createForm.pickup_warehouse_id = 'wh-1'
    vm.createForm.delivery_name = '张三'
    vm.createForm.pickup_city = '上海'
    vm.createForm.delivery_city = '北京'
    vm.createForm.driver_name = '李司机'
    vm.createForm.notes = '易碎品'

    await vm.submitCreate()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    expect(apiClient.post).toHaveBeenCalledWith('/transport-orders', {
      carrier_code: 'sf_express',
      pickup_warehouse_id: 'wh-1',
      delivery_name: '张三',
      pickup_address: { city: '上海' },
      delivery_address: { city: '北京' },
      driver_name: '李司机',
      notes: '易碎品',
    })
  })

  it('opens tracking dialog and shows transport number', async () => {
    const wrapper = mountList()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    const vm = wrapper.vm as any
    await vm.viewTracking({ id: 'ord-1', transport_no: 'TPL-20260813-ABCD' })
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    expect(vm.showTrackingDialog).toBe(true)
    expect(vm.trackingOrder.transport_no).toBe('TPL-20260813-ABCD')
  })

  it('estimates freight and stores result', async () => {
    const wrapper = mountList()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    const vm = wrapper.vm as any
    await vm.estimateFreight()
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 50))

    expect(apiClient.post).toHaveBeenCalledWith('/freight-estimate', vm.freightForm)
    expect(vm.freightResult.total_fee).toBe(25.5)
  })
})