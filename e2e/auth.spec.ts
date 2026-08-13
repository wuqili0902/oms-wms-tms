import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'

const BASE = 'http://127.0.0.1:8000/api/v1'

async function registerUser(unique: string) {
  const res = await fetch(`${BASE}/auth/register`, {
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

test.describe('核心流程冒烟', () => {
  test('注册 → 登录 → 首页', async ({ page }) => {
    const unique = randomUUID().slice(0, 8)
    const username = `e2e_${unique}`

    // 1. 注册测试用户 (直接 API,避免重复执行冲突)
    const reg = await registerUser(unique)
    expect([201, 200]).toContain(reg.status)

    // 2. 打开登录页
    await page.goto('/login')
    await expect(page.locator('.login-container')).toBeVisible()

    // 3. 填写并提交登录
    await page.locator('.el-input__inner').nth(0).fill(username)
    await page.locator('.el-input__inner').nth(1).fill('Test1234!')
    await page.locator('.el-button--primary').click()

    // 4. 跳转 dashboard (登录成功)
    await expect(page).toHaveURL(/\/dashboard/)
  })

  test('未登录访问受保护页面被重定向到登录页', async ({ page }) => {
    await page.goto('/orders')
    await expect(page).toHaveURL(/\/login/)
  })
})
