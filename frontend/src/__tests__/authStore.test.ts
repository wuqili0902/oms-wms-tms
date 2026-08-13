import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const mocks = vi.hoisted(() => {
  const store: Record<string, string | null> = {}
  return {
    post: vi.fn(),
    get: vi.fn(),
    lsGet: vi.fn((k: string) => store[k] ?? null),
    lsSet: vi.fn((k: string, v: string) => { store[k] = v }),
    lsRemove: vi.fn((k: string) => { delete store[k] }),
    clear: () => { Object.keys(store).forEach((k) => delete store[k]) },
  }
})

vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn(), warning: vi.fn(), success: vi.fn() } }))
vi.mock('../api', () => ({
  default: {
    post: mocks.post,
    get: mocks.get,
  },
}))

describe('auth store', () => {
  beforeEach(() => {
    mocks.clear()
    mocks.post.mockReset()
    mocks.get.mockReset()
    vi.stubGlobal('localStorage', {
      getItem: mocks.lsGet,
      setItem: mocks.lsSet,
      removeItem: mocks.lsRemove,
    })
    setActivePinia(createPinia())
  })

  it('login stores token/refresh and fetches me', async () => {
    mocks.post.mockResolvedValueOnce({ data: { access_token: 'at', refresh_token: 'rt' } })
    mocks.get.mockResolvedValueOnce({ data: { username: 'admin' } })

    const { useAuthStore } = await import('../stores/auth')
    const store = useAuthStore()
    await store.login('admin', 'secret')

    expect(mocks.post).toHaveBeenCalledWith('/auth/login', { username: 'admin', password: 'secret' })
    expect(mocks.get).toHaveBeenCalledWith('/auth/me')
    expect(store.isAuthenticated).toBe(true)
    expect(store.username).toBe('admin')
    expect(mocks.lsSet).toHaveBeenCalledWith('access_token', 'at')
  })

  it('login handles wrapped {data: ...} payload', async () => {
    mocks.post.mockResolvedValueOnce({ data: { data: { access_token: 'wrapped', refresh_token: 'rt2' } } })
    mocks.get.mockResolvedValueOnce({ data: { username: 'bob' } })

    const { useAuthStore } = await import('../stores/auth')
    const store = useAuthStore()
    await store.login('bob', 'pw')

    expect(store.token).toBe('wrapped')
    expect(store.refreshToken).toBe('rt2')
  })

  it('fetchMe swallows errors', async () => {
    mocks.get.mockRejectedValueOnce(new Error('network'))
    const { useAuthStore } = await import('../stores/auth')
    const store = useAuthStore()
    await store.fetchMe()
    expect(store.username).toBe('')
  })

  it('refreshAccessToken returns false when no refresh token', async () => {
    const { useAuthStore } = await import('../stores/auth')
    const store = useAuthStore()
    expect(await store.refreshAccessToken()).toBe(false)
  })

  it('refreshAccessToken succeeds and persists new tokens', async () => {
    mocks.lsSet('refresh_token', 'old_rt')
    mocks.post.mockResolvedValueOnce({ data: { access_token: 'new_at', refresh_token: 'new_rt' } })
    const { useAuthStore } = await import('../stores/auth')
    const store = useAuthStore()
    store.refreshToken = 'old_rt'

    const ok = await store.refreshAccessToken()
    expect(ok).toBe(true)
    expect(store.token).toBe('new_at')
    expect(store.refreshToken).toBe('new_rt')
  })

  it('refreshAccessToken logs out on failure', async () => {
    mocks.lsSet('refresh_token', 'rt')
    mocks.post.mockRejectedValueOnce(new Error('expired'))
    const { useAuthStore } = await import('../stores/auth')
    const store = useAuthStore()
    store.refreshToken = 'rt'

    const ok = await store.refreshAccessToken()
    expect(ok).toBe(false)
    expect(store.isAuthenticated).toBe(false)
    expect(store.refreshToken).toBe(null)
  })

  it('logout clears token and storage', async () => {
    mocks.post.mockResolvedValueOnce({ data: {} })
    const { useAuthStore } = await import('../stores/auth')
    const store = useAuthStore()
    store.token = 'at'
    await store.logout()
    expect(store.isAuthenticated).toBe(false)
    expect(mocks.lsRemove).toHaveBeenCalledWith('access_token')
  })
})
