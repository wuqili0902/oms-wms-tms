import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import type { Page } from '@playwright/test'

const API = 'http://127.0.0.1:8000/api/v1'

async function registerUser(unique: string) {
  const res = await fetch(`${API}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      username: `e2e_${unique}`,
      email: `e2e_${unique}@example.com`,
      password: 'Test1234!',
    }),
  })
  return res
}

async function login(unique: string): Promise<string> {
  const res = await fetch(`${API}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: `e2e_${unique}`, password: 'Test1234!' }),
  })
  expect(res.status).toBe(200)
  const data = await res.json()
  const token = data?.access_token ?? data?.data?.access_token
  expect(typeof token).toBe('string')
  return token
}

async function loginViaUI(page: Page, username: string) {
  await page.goto('/login')
  await expect(page.locator('.login-container')).toBeVisible()
  await page.locator('.el-input__inner').nth(0).fill(username)
  await page.locator('.el-input__inner').nth(1).fill('Test1234!')
  await page.locator('.el-button--primary').click()
  await expect(page).toHaveURL(/\/dashboard/)
  await page.waitForLoadState('networkidle')
}

test.describe('业务主流程', () => {
  test('登录后可访问核心业务页面', async ({ page }) => {
    const unique = randomUUID().slice(0, 8)
    await registerUser(unique)
    await loginViaUI(page, `e2e_${unique}`)

    // 通过侧边栏菜单做 SPA 导航(避免整页 reload 与 vite HMR 竞态)
    const menuItem = page.locator('.el-menu .el-menu-item, .el-menu .el-sub-menu__title')
    const pages: Array<{ menu: string; url: string; parent?: string }> = [
      { menu: '订单管理', url: '/orders' },
      { menu: '仓库列表', url: '/warehouses', parent: '仓库管理' },
      { menu: '运单列表', url: '/transport', parent: '运输管理' },
      { menu: '入库管理', url: '/stock/in', parent: '仓库管理' },
      { menu: '设备管理', url: '/devices' },
    ]

    for (const p of pages) {
      const target = menuItem.getByText(p.menu, { exact: true }).first()
      if (!(await target.isVisible().catch(() => false))) {
        await menuItem.getByText(p.parent!, { exact: true }).first().click()
        await expect(target).toBeVisible()
      }
      await target.click()
      await expect(page).toHaveURL(new RegExp(p.url.replace('/', '\\/') + '\\/?$'))
      await expect(page.locator('.el-card').first()).toBeVisible()
    }
  })

  test('API 创建运单 → 前端运输列表可见', async ({ page }) => {
    const unique = randomUUID().slice(0, 8)
    await registerUser(unique)
    const token = await login(unique)

    const res = await fetch(`${API}/transport-orders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        carrier_code: 'zto',
        service_type: 'standard',
        transport_type: 'carrier_pickup',
        delivery_name: 'E2E 收货人',
        delivery_phone: '13800138000',
        pickup_address: { city: '上海', detail: '测试路 1 号' },
        delivery_address: { city: '杭州', detail: '测试路 2 号' },
        package_count: 1,
        total_weight_kg: 2.5,
      }),
    })
    expect([201, 200]).toContain(res.status)
    const created = await res.json()
    const transportNo = created?.transport_no ?? created?.data?.transport_no
    expect(typeof transportNo).toBe('string')

    // 前端登录后访问运输列表,应能看到该运单号
    await loginViaUI(page, `e2e_${unique}`)
    await page.goto('/transport')
    await expect(page.locator('table').first()).toBeVisible()
    await expect(page.getByText(transportNo).first()).toBeVisible({ timeout: 15000 })
  })

  test('TMS 非法 UUID 路径返回 404 而非 500', async () => {
    const unique = randomUUID().slice(0, 8)
    await registerUser(unique)
    const token = await login(unique)
    const headers = { Authorization: `Bearer ${token}` }

    const res = await fetch(`${API}/transport-orders/not-a-real-uuid`, { headers })
    expect(res.status).toBe(404)
  })

  test('未登录 API 访问受保护资源返回 401', async () => {
    const res = await fetch(`${API}/warehouses`)
    expect([401, 403]).toContain(res.status)
  })
})
