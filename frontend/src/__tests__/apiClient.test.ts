import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import axios from 'axios'
import type { AxiosInstance } from 'axios'

const mocks = vi.hoisted(() => {
  const store: Record<string, string | null> = {}
  return {
    lsGet: vi.fn((k: string) => store[k] ?? null),
    lsSet: vi.fn((k: string, v: string) => { store[k] = v }),
    lsRemove: vi.fn((k: string) => { delete store[k] }),
    error: vi.fn(),
    clear: () => { Object.keys(store).forEach((k) => delete store[k]) },
  }
})

vi.mock('element-plus', () => ({ ElMessage: { error: mocks.error, warning: vi.fn() } }))

describe('api client', () => {
  let apiClient: AxiosInstance

  beforeEach(async () => {
    mocks.clear()
    mocks.error.mockReset()
    vi.stubGlobal('localStorage', {
      getItem: mocks.lsGet,
      setItem: mocks.lsSet,
      removeItem: mocks.lsRemove,
    })
    // re-import fresh module state (isRefreshing / pendingRequests reset)
    vi.resetModules()
    const mod = await import('../api')
    apiClient = mod.default
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('attaches Bearer token from localStorage on requests', async () => {
    mocks.lsSet('access_token', 'tok123')
    const adapter = apiClient.defaults.adapter
    const spy = vi.fn(async (config: any) => {
      expect(config.headers.Authorization).toBe('Bearer tok123')
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
    })
    apiClient.defaults.adapter = spy as any
    await apiClient.get('/orders')
    apiClient.defaults.adapter = adapter
    expect(spy).toHaveBeenCalled()
  })

  it('sends no Authorization when token absent', async () => {
    const adapter = apiClient.defaults.adapter
    const spy = vi.fn(async (config: any) => {
      expect(config.headers.Authorization).toBeUndefined()
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config }
    })
    apiClient.defaults.adapter = spy as any
    await apiClient.get('/orders')
    apiClient.defaults.adapter = adapter
    expect(spy).toHaveBeenCalled()
  })

  it('passes through 2xx responses', async () => {
    const adapter = apiClient.defaults.adapter
    apiClient.defaults.adapter = (async (config: any) => ({ data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config })) as any
    const res = await apiClient.get('/orders')
    expect(res.data).toEqual({ ok: true })
    apiClient.defaults.adapter = adapter
  })

  it('returns error.message for non-detail errors', async () => {
    const adapter = apiClient.defaults.adapter
    apiClient.defaults.adapter = (async () => Promise.reject({ message: 'Network Error' })) as any
    await expect(apiClient.get('/orders')).rejects.toMatchObject({ message: 'Network Error' })
    expect(mocks.error).toHaveBeenCalledWith('Network Error')
    apiClient.defaults.adapter = adapter
  })

  it('surfaces backend detail message on business errors', async () => {
    const adapter = apiClient.defaults.adapter
    apiClient.defaults.adapter = (async () => Promise.reject({
      message: 'Request failed with status code 400',
      config: { url: '/orders' },
      response: { status: 400, data: { detail: '库存不足' } },
    })) as any
    await expect(apiClient.get('/orders')).rejects.toBeTruthy()
    expect(mocks.error).toHaveBeenCalledWith('库存不足')
    apiClient.defaults.adapter = adapter
  })

  it('surfaces the documented error envelope, and hands it to the view', async () => {
    const adapter = apiClient.defaults.adapter
    apiClient.defaults.adapter = (async () => Promise.reject({
      message: 'Request failed with status code 422',
      config: { url: '/return-orders' },
      response: {
        status: 422,
        data: { success: false, error: { code: 'VALIDATION_ERROR', message: "reason must be one of: damaged, wrong_item" } },
      },
    })) as any
    const err = await apiClient.get('/return-orders').catch((e) => e)
    expect(mocks.error).toHaveBeenCalledWith("reason must be one of: damaged, wrong_item")
    expect(err.userMessage).toBe("reason must be one of: damaged, wrong_item")
    apiClient.defaults.adapter = adapter
  })

  it('prefers the envelope over the legacy detail when a response carries both', async () => {
    const adapter = apiClient.defaults.adapter
    apiClient.defaults.adapter = (async () => Promise.reject({
      message: 'Request failed with status code 409',
      config: { url: '/stock/adjust' },
      response: {
        status: 409,
        data: { detail: 'Conflict', error: { code: 'CONFLICT', message: '库存已被并发修改，请重新读取后重试' } },
      },
    })) as any
    await apiClient.post('/stock/adjust', {}).catch(() => undefined)
    expect(mocks.error).toHaveBeenCalledWith('库存已被并发修改，请重新读取后重试')
    apiClient.defaults.adapter = adapter
  })

  it('shows a message containing angle brackets exactly as the server wrote it', async () => {
    // Element Plus renders ElMessage's text, not HTML, so escaping here would put
    // "&lt;" in front of the operator.  The server quotes values as Python reprs.
    const adapter = apiClient.defaults.adapter
    apiClient.defaults.adapter = (async () => Promise.reject({
      message: 'Request failed with status code 422',
      config: { url: '/devices' },
      response: { status: 422, data: { success: false, error: { code: 'VALIDATION_ERROR', message: "device_code must be one of: pda, phone, got 'PDA<1'" } } },
    })) as any
    const err = await apiClient.post('/devices', {}).catch((e) => e)
    expect(mocks.error).toHaveBeenCalledWith("device_code must be one of: pda, phone, got 'PDA<1'")
    expect(err.userMessage).toContain("got 'PDA<1'")
    apiClient.defaults.adapter = adapter
  })

  it('does not redirect for 401 on /auth/login', async () => {
    const adapter = apiClient.defaults.adapter
    apiClient.defaults.adapter = (async () => Promise.reject({
      message: 'Unauthorized',
      config: { url: '/auth/login', headers: {} },
      response: { status: 401, data: { detail: 'bad credentials' } },
    })) as any
    await expect(apiClient.post('/auth/login', {})).rejects.toBeTruthy()
    apiClient.defaults.adapter = adapter
  })

  it('refreshes token on 401 and retries original request', async () => {
    mocks.lsSet('access_token', 'expired_at')
    mocks.lsSet('refresh_token', 'valid_rt')
    const adapter = apiClient.defaults.adapter
    const refreshSpy = vi.spyOn(axios, 'post').mockResolvedValue({
      data: { access_token: 'fresh_at', refresh_token: 'fresh_rt' },
      status: 200, statusText: 'OK', headers: {}, config: {} as any,
    } as any)
    let originalCalls = 0
    apiClient.defaults.adapter = (async (config: any) => {
      if (config.url?.includes('/auth/refresh')) {
        return { data: { access_token: 'fresh_at', refresh_token: 'fresh_rt' }, status: 200, statusText: 'OK', headers: {}, config }
      }
      originalCalls++
      if (config._retry) {
        return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config }
      }
      return Promise.reject({
        message: 'Unauthorized',
        config: { url: config.url, headers: {} },
        response: { status: 401, data: { detail: 'expired' } },
      })
    }) as any

    const res = await apiClient.get('/orders')
    expect(refreshSpy).toHaveBeenCalled()
    expect(originalCalls).toBe(2)
    expect(res.data).toEqual({ ok: true })
    expect(mocks.lsSet).toHaveBeenCalledWith('access_token', 'fresh_at')
    refreshSpy.mockRestore()
    apiClient.defaults.adapter = adapter
  })
})
