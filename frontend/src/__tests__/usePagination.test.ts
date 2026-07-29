import { describe, it, expect } from 'vitest'
import { usePagination } from '../composables/usePagination'

describe('usePagination', () => {
  it('returns default values', () => {
    const { page, pageSize, total } = usePagination()
    expect(page.value).toBe(1)
    expect(pageSize.value).toBe(20)
    expect(total.value).toBe(0)
  })

  it('onPageChange updates page', () => {
    const { page, onPageChange } = usePagination()
    onPageChange(3)
    expect(page.value).toBe(3)
  })

  it('onSizeChange updates pageSize and resets page', () => {
    const pageNum = 5
    const { page, pageSize, onPageChange, onSizeChange } = usePagination()
    onPageChange(pageNum)
    expect(page.value).toBe(pageNum)
    onSizeChange(50)
    expect(pageSize.value).toBe(50)
    expect(page.value).toBe(1)
  })

  it('accepts custom default page size', () => {
    const { pageSize } = usePagination(50)
    expect(pageSize.value).toBe(50)
  })
})
