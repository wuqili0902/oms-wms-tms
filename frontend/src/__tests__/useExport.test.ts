import { describe, it, expect } from 'vitest'
import { useExport } from '../composables/useExport'

describe('useExport', () => {
  it('returns downloadCSV function', () => {
    const { downloadCSV } = useExport()
    expect(typeof downloadCSV).toBe('function')
  })
})
