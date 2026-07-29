import { describe, it, expect } from 'vitest'
import apiClient from '../api/index'

describe('Import CSV endpoints', () => {
  it.skip('imports orders via /api/v1/import/orders', async () => {
    const csv = `customer_id,items,priority,notes
550e8400-e29b-41d4-a716-446655440000,[{"sku":"SKU-A","qty":2}],"high",Urgent order
`
    const res = await apiClient.post('/api/v1/import/orders', { file: new File([csv], 'orders.csv') })
    expect(res.status).toBe(200)
    expect(res.data.success).toBeGreaterThan(0)
  })

  it.skip('imports inventory via /api/v1/import/inventory', async () => {
    const csv = `sku_id,warehouse_id,quantity,min_qty
550e8400-e29b-41d4-a716-446655440001,550e8400-e29b-41d4-a716-446655440002,100,20
`
    const res = await apiClient.post('/api/v1/import/inventory', { file: new File([csv], 'inventory.csv') })
    expect(res.status).toBe(200)
    expect(res.data.success).toBeGreaterThan(0)
  })
})
