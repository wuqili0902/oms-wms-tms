import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '@/api'
import type { Device, SessionLog } from '@/types/device'

export const useDeviceStore = defineStore('device', () => {
  const devices = ref<Device[]>([])
  const loading = ref(false)
  const selectedDevice = ref<Device | null>(null)
  const sessions = ref<SessionLog[]>([])
  const syncLogs = ref<any[]>([])

  async function fetchDevices(): Promise<void> {
    loading.value = true
    try {
      const res = await apiClient.get('/devices')
      devices.value = res.data?.data ?? res.data ?? []
    } catch (e: any) {
      console.warn('[device] fetchDevices failed:', e?.response?.data ?? e)
    } finally {
      loading.value = false
    }
  }

  async function fetchDeviceById(id: string): Promise<void> {
    try {
      const res = await apiClient.get(`/devices/${id}`)
      selectedDevice.value = res.data?.data ?? res.data
    } catch (e: any) {
      console.warn('[device] fetchDeviceById failed:', e?.response?.data ?? e)
    }
  }

  async function fetchSessions(deviceId: string): Promise<SessionLog[]> {
    try {
      const res = await apiClient.get(`/devices/${deviceId}/sessions`)
      sessions.value = res.data?.data ?? res.data ?? []
      return sessions.value
    } catch (e: any) {
      console.warn('[device] fetchSessions failed:', e?.response?.data ?? e)
      return []
    }
  }

  async function fetchSyncLogs(deviceId: string): Promise<any[]> {
    try {
      const res = await apiClient.get(`/devices/${deviceId}/sync`)
      syncLogs.value = res.data?.data ?? res.data ?? []
      return syncLogs.value
    } catch (e: any) {
      console.warn('[device] fetchSyncLogs failed:', e?.response?.data ?? e)
      return []
    }
  }

  async function createSession(deviceId: string): Promise<void> {
    try {
      await apiClient.post(`/devices/${deviceId}/sessions`)
    } catch (e: any) {
      ElMessage.error(e?.response?.data?.detail ?? '创建会话失败')
    }
  }

  return {
    devices, loading, selectedDevice, sessions, syncLogs,
    fetchDevices, fetchDeviceById, fetchSessions, fetchSyncLogs, createSession,
  }
})
