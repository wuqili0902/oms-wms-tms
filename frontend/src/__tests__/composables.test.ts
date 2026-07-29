import { describe, it, expect, vi } from 'vitest'
import { ref, nextTick } from 'vue'
import { useDebounce } from '../composables/useDebounce'
import { useNetworkStatus } from '../composables/useNetworkStatus'

describe('useDebounce', () => {
  it('returns initial value immediately', () => {
    const source = ref('hello')
    const debounced = useDebounce(source, 100)
    expect(debounced.value).toBe('hello')
  })

  it('delays value updates', async () => {
    vi.useFakeTimers()
    const source = ref('a')
    const debounced = useDebounce(source, 200)

    source.value = 'b'
    await nextTick()
    expect(debounced.value).toBe('a')

    vi.advanceTimersByTime(199)
    expect(debounced.value).toBe('a')

    vi.advanceTimersByTime(1)
    expect(debounced.value).toBe('b')
  })

  it('cancels previous timer on rapid changes', async () => {
    vi.useFakeTimers()
    const source = ref('a')
    const debounced = useDebounce(source, 200)

    source.value = 'b'
    await nextTick()
    vi.advanceTimersByTime(100)
    source.value = 'c'
    await nextTick()
    vi.advanceTimersByTime(100)
    expect(debounced.value).toBe('a')

    vi.advanceTimersByTime(100)
    expect(debounced.value).toBe('c')
  })

  it('uses default 300ms delay', async () => {
    vi.useFakeTimers()
    const source = ref('x')
    const debounced = useDebounce(source)

    source.value = 'y'
    await nextTick()
    vi.advanceTimersByTime(300)
    expect(debounced.value).toBe('y')
  })
})

describe('useNetworkStatus', () => {
  it('returns current online status', () => {
    const { online } = useNetworkStatus()
    expect(typeof online.value).toBe('boolean')
  })

  it('reacts to online/offline events', () => {
    const { online } = useNetworkStatus()
    expect(online.value).toBe(true)
    window.dispatchEvent(new Event('offline'))
    expect(online.value).toBe(false)
    window.dispatchEvent(new Event('online'))
    expect(online.value).toBe(true)
  })
})
