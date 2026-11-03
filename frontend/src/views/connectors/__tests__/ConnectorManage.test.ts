/*
Frontend contract for the 连接器管理 screen and its two 配置说明 pages.

The screen shipped unreachable and wired to URLs the API never had:
``views/connectors/index.vue`` had no route in ``src/router/index.ts`` at all, it
listed connectors from ``GET /connectors/status`` and synced them with
``POST /connectors/{id}/sync`` (neither existed), a failed fetch ended in
``console.warn`` so the operator saw "暂无连接器数据", and its 配置 buttons pushed
``/connectors/amazon-config`` while the SPA route is
``/connectors/amazon-config/:connectorId`` — the router matched nothing.  Behind
those buttons sat two forms collecting an **AWS access key** and a **Shopify
Admin API token** and posting them to endpoints that do not exist; SP-API
authenticates with an LWA client id/secret plus a refresh token, and Shopify's
webhook is verified with the app's own ``SECRET_KEY``, so nothing in those forms
was a credential this system can use.

These tests pin the fixed shape: the registry is read from the endpoint that
exists, every button leads to a route the SPA actually has, the config pages are
read-only (no secret inputs, no write requests), and a failed fetch is shown.
*/

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createRouter, createMemoryHistory } from 'vue-router'

const REGISTRY = [
  {
    id: 'amazon',
    name: 'Amazon SP-API',
    type: 'amazon',
    status: 'not_configured',
    configured: false,
    last_sync: null,
    capabilities: {
      order_import: 'implemented',
      tracking_handover_record: 'implemented',
      tracking_upload: 'not_implemented',
      order_status_poll: 'not_implemented',
      inventory_sync: 'not_implemented',
    },
    credentials: [
      { env: 'AMAZON_SP_API_CLIENT_ID', set: false, value: null },
      { env: 'AMAZON_SP_API_CLIENT_SECRET', set: false, value: null },
      { env: 'AMAZON_SP_API_REFRESH_TOKEN', set: false, value: null },
      { env: 'AMAZON_SP_API_REGION', set: null, value: 'us' },
    ],
    note: '凭据写在服务器配置（.env / 环境变量）里，不经网页传输。',
  },
  {
    id: 'shopify',
    name: 'Shopify Webhook',
    type: 'shopify',
    status: 'active',
    configured: true,
    last_sync: null,
    capabilities: {
      order_push: 'implemented',
      fulfillment_push: 'implemented',
      order_pull: 'not_available',
      inventory_sync: 'not_available',
    },
    credentials: [{ env: 'SECRET_KEY', set: true, value: null }],
    note: 'Shopify 是推送式对接：订单由 Webhook 带 HMAC 签名送入。',
  },
]

const registryList = () => ({ data: REGISTRY })
const registryOne = (url: string) => ({ data: REGISTRY.find((c) => c.id === url.split('/')[2]) ?? REGISTRY[0] })
const registryGet = (url: string) => Promise.resolve(url === '/connectors/status' ? registryList() : registryOne(url))

// vi.hoisted: the mock factory below runs when ``../../../api`` is imported,
// which is above these declarations, so the spies have to exist first.
const { getMock, postMock, putMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(() => Promise.resolve({ data: {} })),
  putMock: vi.fn(() => Promise.resolve({ data: {} })),
}))

vi.mock('../../../api', () => ({
  default: { get: getMock, post: postMock, put: putMock },
}))

import apiClient from '../../../api'
import ConnectorManage from '../index.vue'
import AmazonConfig from '../AmazonConfig.vue'
import ShopifyConfig from '../ShopifyConfig.vue'

// The route table as ``src/router/index.ts`` declares it: the config screens sit
// under ``:connectorId``, which is exactly what the 配置 buttons used to omit.
function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/connectors/manage', name: 'ConnectorManage', component: ConnectorManage },
      { path: '/connectors/amazon-config/:connectorId', name: 'AmazonConfig', component: AmazonConfig },
      { path: '/connectors/shopify-config/:connectorId', name: 'ShopifyConfig', component: ShopifyConfig },
    ],
  })
}

const settle = () => new Promise((r) => setTimeout(r, 50))

async function mountManage(router: ReturnType<typeof makeRouter>) {
  if (router.currentRoute.value.path !== '/connectors/manage') {
    await router.push('/connectors/manage')
    await router.isReady()
  }
  const wrapper = mount(ConnectorManage, { global: { plugins: [createPinia(), ElementPlus, router] } })
  await settle()
  return wrapper
}

describe('连接器管理 (views/connectors/index.vue)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMock.mockImplementation(registryGet)
  })

  it('reads the registry from the endpoint that exists', async () => {
    const wrapper = await mountManage(makeRouter())
    expect(apiClient.get).toHaveBeenCalledWith('/connectors/status')
    expect(wrapper.text()).toContain('Amazon SP-API')
    expect(wrapper.text()).toContain('Shopify Webhook')
    // The listing used to be "暂无连接器数据" with the failure in console.warn.
    expect(wrapper.text()).not.toContain('暂无连接器数据')
  })

  it('names each capability as implemented, unimplemented, or not applicable', async () => {
    const wrapper = await mountManage(makeRouter())
    const text = wrapper.text()
    expect(text).toContain('订单导入: 已实现')
    expect(text).toContain('运单回传: 未实现')
    expect(text).toContain('状态轮询: 未实现')
    expect(text).toContain('订单拉取: 不适用')
  })

  it('shows credential variable names, set/unset, and never a secret value', async () => {
    const wrapper = await mountManage(makeRouter())
    const text = wrapper.text()
    expect(text).toContain('AMAZON_SP_API_CLIENT_ID')
    expect(text).toContain('SECRET_KEY')
    expect(text).toContain('未配置')
    expect(text).toContain('已配置')
    // Region is a marketplace selector, shown; credentials publish only their name.
    const amazon = REGISTRY[0]
    for (const field of amazon.credentials.filter((f) => f.env !== 'AMAZON_SP_API_REGION')) {
      expect(text).not.toContain(String(field.value))
    }
  })

  it('has no 同步 button — a 200 there would read as a sync that happened', async () => {
    const wrapper = await mountManage(makeRouter())
    const labels = wrapper.findAll('button').map((b) => b.text().trim())
    expect(labels.some((t) => t.includes('同步'))).toBe(false)
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  it('配置说明 leads to a route the SPA has', async () => {
    const router = makeRouter()
    await router.push('/connectors/manage')
    await router.isReady()
    const wrapper = await mountManage(router)
    const button = wrapper.findAll('button').find((b) => b.text().includes('配置说明'))
    expect(button).toBeTruthy()
    await button!.trigger('click')
    await settle()
    expect(router.currentRoute.value.name).toBe('AmazonConfig')
    expect(router.currentRoute.value.params.connectorId).toBe('amazon')
  })

  it('reports a failed fetch to the operator, not to the console', async () => {
    getMock.mockImplementation(() => Promise.reject(new Error('Request failed with status code 404')))
    const wrapper = await mountManage(makeRouter())
    // The failure has to be on the screen.  The table's own empty text
    // ("暂无连接器数据") is what the operator used to see — the fetch had failed
    // and the reason went to console.warn; the alert is the fix.
    const alerts = wrapper.findAll('.el-alert').map((a) => a.text())
    expect(alerts.join(' ')).toContain('404')
    expect(alerts.length).toBeGreaterThan(0)
  })
})

describe('配置说明 pages are read-only guidance', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getMock.mockImplementation(registryGet)
  })

  const mountConfig = async (component: typeof AmazonConfig, path: string) => {
    const router = makeRouter()
    await router.push(path)
    await router.isReady()
    const wrapper = mount(component, { global: { plugins: [createPinia(), ElementPlus, router] } })
    await settle()
    return wrapper
  }

  it('Amazon page reads status and writes nothing', async () => {
    const wrapper = await mountConfig(AmazonConfig, '/connectors/amazon-config/amazon')
    expect(apiClient.get).toHaveBeenCalledWith('/connectors/amazon')
    expect(apiClient.post).not.toHaveBeenCalled()
    expect(apiClient.put).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('AMAZON_SP_API_CLIENT_ID')
    expect(wrapper.text()).toContain('已配置')
  })

  // The old form asked for AWS Access Key / Secret Access Key / Marketplace IDs
  // and POSTed them to /connectors/amazon/config/{id}.  SP-API uses LWA
  // credentials, and no such endpoint exists — the keys had no consumer.  What is
  // checked here is the absence of a *form*: the guidance text on the fixed page
  // says "不是 AWS Access Key" on purpose.
  it('Amazon page collects no AWS access key', async () => {
    const wrapper = await mountConfig(AmazonConfig, '/connectors/amazon-config/amazon')
    expect(wrapper.findAll('input')).toHaveLength(0)
    expect(wrapper.findAll('textarea')).toHaveLength(0)
    expect(wrapper.findAll('form, .el-form')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('保存配置')
  })

  it('Amazon page says credentials live in the server config', async () => {
    const wrapper = await mountConfig(AmazonConfig, '/connectors/amazon-config/amazon')
    expect(wrapper.text()).toContain('不在网页填写')
  })

  it('Shopify page names the webhook endpoint and writes nothing', async () => {
    const wrapper = await mountConfig(ShopifyConfig, '/connectors/shopify-config/shopify')
    expect(apiClient.get).toHaveBeenCalledWith('/connectors/shopify')
    expect(apiClient.post).not.toHaveBeenCalled()
    expect(apiClient.put).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('/api/v1/connectors/shopify/webhook')
    expect(wrapper.text()).toContain('orders/create')
    expect(wrapper.text()).toContain('SECRET_KEY')
  })

  // The old form took an Admin API Token (shpat_…) and PUT it to
  // /connectors/{id}/config; the system never calls the Shopify Admin API, so the
  // token had no consumer.  Checked as the absence of a form — the guidance text
  // names the token to say it is not needed.
  it('Shopify page collects no Admin API token', async () => {
    const wrapper = await mountConfig(ShopifyConfig, '/connectors/shopify-config/shopify')
    expect(wrapper.findAll('input')).toHaveLength(0)
    expect(wrapper.findAll('textarea')).toHaveLength(0)
    expect(wrapper.findAll('form, .el-form')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('保存配置')
  })
})
