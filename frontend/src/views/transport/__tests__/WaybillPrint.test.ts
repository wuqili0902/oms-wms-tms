import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createRouter, createMemoryHistory } from 'vue-router'

const mockWaybill = {
  tracking_number: 'ZT240101TEST001',
  order_id: 'ORD001',
  carrier_code: 'zto',
  carrier_name: '中通快递',
  recipient_name: '张三',
  recipient_phone: '13800138000',
  recipient_address: '上海市浦东新区',
  status: 'created',
  print_count: 0,
  items: [{ sku: 'SKU001', qty: 2 }],
}

vi.mock('../../../api', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: mockWaybill }),
    post: vi.fn().mockResolvedValue({ data: { print_callback_url: 'http://print.url' } }),
  },
}))

describe('WaybillPrint.vue', () => {
  let router: any

  beforeEach(() => {
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/transport/print/:tracking', name: 'WaybillPrint', component: () => import('../WaybillPrint.vue') },
      ],
    })
  })

  it('renders tracking number in header', async () => {
    const WaybillPrint = (await import('../WaybillPrint.vue')).default
    const wrapper = mount(WaybillPrint, {
      global: { plugins: [createPinia(), ElementPlus, router] },
      props: { params: { tracking: 'ZT240101TEST001' } },
    })
    await wrapper.vm.$nextTick()
    await new Promise(r => setTimeout(r, 100))
    expect(wrapper.text()).toContain('ZT240101TEST001')
  })

  it('has print button', async () => {
    const WaybillPrint = (await import('../WaybillPrint.vue')).default
    const wrapper = mount(WaybillPrint, {
      global: { plugins: [createPinia(), ElementPlus, router] },
      props: { params: { tracking: 'ZT240101TEST001' } },
    })
    await wrapper.vm.$nextTick()
    await new Promise(r => setTimeout(r, 100))
    const buttons = wrapper.findAllComponents({ name: 'ElButton' })
    const texts = buttons.map(b => b.text())
    expect(texts).toContain('打印电子面单')
  })

  it('has back button', async () => {
    const WaybillPrint = (await import('../WaybillPrint.vue')).default
    const wrapper = mount(WaybillPrint, {
      global: { plugins: [createPinia(), ElementPlus, router] },
      props: { params: { tracking: 'ZT240101TEST001' } },
    })
    await wrapper.vm.$nextTick()
    await new Promise(r => setTimeout(r, 100))
    const buttons = wrapper.findAllComponents({ name: 'ElButton' })
    const texts = buttons.map(b => b.text())
    expect(texts).toContain('返回')
  })

  it('shows label preview with waybill info', async () => {
    const WaybillPrint = (await import('../WaybillPrint.vue')).default
    const wrapper = mount(WaybillPrint, {
      global: { plugins: [createPinia(), ElementPlus, router] },
      props: { params: { tracking: 'ZT240101TEST001' } },
    })
    await wrapper.vm.$nextTick()
    await new Promise(r => setTimeout(r, 100))
    expect(wrapper.text()).toContain('中通快递')
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('13800138000')
  })
})
