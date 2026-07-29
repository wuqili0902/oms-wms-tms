import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import apiClient from '../api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('access_token'))
  const refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))
  const username = ref<string>('')
  const isAuthenticated = computed(() => !!token.value)

  async function login(usernameInput: string, password: string) {
    const res = await apiClient.post('/auth/login', { username: usernameInput, password: password })
    const data = res.data?.data ?? res.data
    token.value = data?.access_token ?? res.data?.access_token
    refreshToken.value = data?.refresh_token ?? res.data?.refresh_token ?? null
    username.value = usernameInput
    localStorage.setItem('access_token', token.value ?? '')
    if (refreshToken.value) localStorage.setItem('refresh_token', refreshToken.value)
    await fetchMe()
  }

  async function fetchMe() {
    try {
      const res = await apiClient.get('/auth/me')
      const me = res.data?.data ?? res.data
      if (me?.username) username.value = me.username
    } catch { /* ignore */ }
  }

  async function refreshAccessToken(): Promise<boolean> {
    if (!refreshToken.value) return false
    try {
      const res = await apiClient.post('/auth/refresh', { refresh_token: refreshToken.value })
      const data = res.data?.data ?? res.data
      const newToken = data?.access_token ?? res.data?.access_token
      const newRefresh = data?.refresh_token ?? res.data?.refresh_token
      if (!newToken) return false
      token.value = newToken
      localStorage.setItem('access_token', newToken)
      if (newRefresh) {
        refreshToken.value = newRefresh
        localStorage.setItem('refresh_token', newRefresh)
      }
      return true
    } catch {
      logout()
      return false
    }
  }

  async function logout() {
    try { await apiClient.post('/auth/logout') } catch { /* ignore */ }
    token.value = null
    refreshToken.value = null
    username.value = ''
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  return { token, refreshToken, username, isAuthenticated, login, fetchMe, refreshAccessToken, logout }
})
