import { describe, it, expect } from 'vitest'
import { lazyLoadWithRetry } from '../utils/lazyLoad'

describe('lazyLoadWithRetry', () => {
  it('resolves on first attempt', async () => {
    const loader = () => Promise.resolve('ok')
    const result = await lazyLoadWithRetry(loader, 2, 10)()
    expect(result).toBe('ok')
  })

  it('resolves after retries', async () => {
    let attempts = 0
    const loader = () => {
      attempts++
      return attempts >= 3 ? Promise.resolve('ok') : Promise.reject(new Error('fail'))
    }
    const result = await lazyLoadWithRetry(loader, 3, 10)()
    expect(result).toBe('ok')
    expect(attempts).toBe(3)
  })

  it('rejects after exhausting retries', async () => {
    const loader = () => Promise.reject(new Error('persistent'))
    await expect(lazyLoadWithRetry(loader, 1, 10)()).rejects.toThrow('persistent')
  })
})

describe('NotFound.vue', () => {
  it('is a valid Vue component', async () => {
    const NotFound = (await import('../views/NotFound.vue')).default
    expect(NotFound).toBeDefined()
    expect(NotFound.render || NotFound.template).toBeTruthy()
  })
})
