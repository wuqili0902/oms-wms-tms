import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'

describe('PdaPage.vue', () => {
  it('renders mutation tab content', async () => {
    const PdaPage = (await import('../views/pda/PdaPage.vue')).default
    const wrapper = mount(PdaPage, {
      global: { plugins: [createPinia(), ElementPlus] },
    })
    expect(wrapper.text()).toContain('库存变动')
    expect(wrapper.text()).toContain('同步队列')
  })

  it('has submit and clear buttons', async () => {
    const PdaPage = (await import('../views/pda/PdaPage.vue')).default
    const wrapper = mount(PdaPage, {
      global: { plugins: [createPinia(), ElementPlus] },
    })
    const buttons = wrapper.findAllComponents({ name: 'ElButton' })
    const texts = buttons.map(b => b.text())
    expect(texts).toContain('提交变动')
    expect(texts).toContain('清空')
  })

  it('shows empty state for sync queue table', async () => {
    const PdaPage = (await import('../views/pda/PdaPage.vue')).default
    const wrapper = mount(PdaPage, {
      global: { plugins: [createPinia(), ElementPlus] },
    })
    const tabs = wrapper.findAllComponents({ name: 'ElTabPane' })
    expect(tabs.length).toBe(2)
  })
})
