import axios from 'axios'
import type { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

const apiClient: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

let isRefreshing = false
let pendingRequests: Array<(token: string) => void> = []

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    if (error.response?.status === 401 && !originalRequest._retry && !originalRequest.url?.includes('/auth/refresh') && !originalRequest.url?.includes('/auth/login')) {
      if (isRefreshing) {
        return new Promise((resolve) => {
          pendingRequests.push((token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(apiClient(originalRequest))
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const refreshToken = localStorage.getItem('refresh_token')
        if (!refreshToken) throw new Error('No refresh token')

        const res = await axios.post(`${import.meta.env.VITE_API_BASE_URL || '/api/v1'}/auth/refresh`, { refresh_token: refreshToken })
        const data = res.data?.data ?? res.data
        const newToken = data?.access_token ?? res.data?.access_token
        const newRefresh = data?.refresh_token ?? res.data?.refresh_token

        if (!newToken) throw new Error('Refresh failed')

        localStorage.setItem('access_token', newToken)
        if (newRefresh) localStorage.setItem('refresh_token', newRefresh)

        pendingRequests.forEach((cb) => cb(newToken))
        pendingRequests = []

        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return apiClient(originalRequest)
      } catch {
        pendingRequests = []
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        window.location.href = '/login'
        return Promise.reject(error)
      } finally {
        isRefreshing = false
      }
    }

    const msg = error.response?.data && typeof error.response.data === 'object' && 'detail' in (error.response.data as object)
      ? (error.response.data as any).detail
      : error.message
    ElMessage.error(msg)
    return Promise.reject(error)
  },
)

export default apiClient
