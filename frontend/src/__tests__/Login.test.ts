import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import Login from '../views/Login.vue'
import { createPinia } from 'pinia'

describe('Login.vue', () => {
  it('renders title', () => {
    const wrapper = mount(Login, {
      global: { plugins: [createPinia()] },
    })
    expect(wrapper.text()).toContain('物流管理系统')
  })

  it('has login button', () => {
    const wrapper = mount(Login, {
      global: { plugins: [createPinia()] },
    })
    expect(wrapper.text()).toContain('登 录')
  })
})
