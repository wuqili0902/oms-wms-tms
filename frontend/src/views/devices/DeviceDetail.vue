<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import StatusTag from '@/components/StatusTag.vue'
import apiClient from '../../api'

const props = defineProps<{ params: { dev_id: string } }>()

const device = ref<any>({})
const sessions = ref<any[]>([])
const syncLogs = ref<any[]>([])
const loading = ref(false)
const tabs = ref(['sessions', 'sync'] as const)

function formatTime(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${d.getMonth()+1}/${d.getDate()} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`
}

function getStatusColor(status?: string): string {
  return (status ?? '').toLowerCase() === 'online' ? 'success' : ''
}

async function fetchDevice(): Promise<void> {
  try {
    device.value = await apiClient.get(`/devices/${props.params.dev_id}`)
  } catch (e: any) { console.error('[DeviceDetail] fetchDevice failed:', e?.response?.data ?? e); ElMessage.error('获取设备信息失败') }
}

async function createSession(): Promise<void> {
  try {
    await apiClient.post(`/devices/${props.params.dev_id}/sessions`)
    ElMessage.success('会话已创建')
    fetchSessions()
  } catch (e: any) { console.error('[DeviceDetail] createSession failed:', e?.response?.data ?? e); ElMessage.error('创建会话失败') }
}

async function fetchSessions(): Promise<void> {
  try {
    sessions.value = await apiClient.get(`/devices/${props.params.dev_id}/sessions`) as any[]
  } catch (e: any) { console.warn('[DeviceDetail] fetchSessions failed:', e?.response?.data ?? e); sessions.value = [] }
}

async function fetchSyncLogs(): Promise<void> {
  try {
    syncLogs.value = await apiClient.get(`/devices/${props.params.dev_id}/sync`) as any[]
  } catch (e: any) { ElMessage.error('获取同步日志失败: ' + (e?.response?.data?.detail ?? e.message)); syncLogs.value = [] }
}

onMounted(() => { fetchDevice(); fetchSessions(); fetchSyncLogs() })
</script>

<template>
  <el-card class="device-detail">
    <template #header>
      <span>设备详情 — {{ params.dev_id }}</span>
    </template>

    <!-- 基本信息 -->
    <el-descriptions :column="1" border v-if="Object.keys(device).length">
      <el-descriptions-item label="ID">{{ device.id ?? '—' }}</el-descriptions-item>
      <el-descriptions-item label="名称">{{ device.name ?? '—' }}</el-descriptions-item>
      <el-descriptions-item label="类型"><StatusTag :type="device.type ?? ''" /></el-descriptions-item>
      <el-descriptions-item label="状态">
        <el-tag :type="getStatusColor(device.last_seen)">{{ device.status ?? '离线' }}</el-tag>
      </el-descriptions-item>
    </el-descriptions>

    <!-- 会话管理 -->
    <el-tabs v-model="tabs" type="border-card">
      <el-tab-pane name="sessions">
        <template #label><span style="display:flex;align-items:center"><i class="el-icon-monitor"></i> 会话</span></template>
        <div v-loading="loading">
          <el-row :gutter="12" style="margin-bottom:16px">
            <el-col :span="8">
              <el-button type="primary" @click="createSession">创建会话</el-button>
            </el-col>
            <el-col :flex="1"></el-col>
          </el-row>

          <!-- Sessions 列表 -->
          <el-table v-loading="loading" :data="sessions || []" stripe empty-text="暂无数据">
            <el-table-column prop="id" label="ID" width="200"/>
            <el-table-column prop="ip_address" label="IP 地址" width="160"/>
            <el-table-column prop="login_at" label="登录时间" width="175">
              <template #default="{ row }">{{ formatTime(row.login_at) }}</template>
            </el-table-column>
            <el-table-column prop="logout_at" label="登出时间" width="175">
              <template #default="{ row }">{{ row.logout_at ? formatTime(row.logout_at) : '—' }}</template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }"><StatusTag :type="row.status"/></template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane name="sync">
        <template #label><span style="display:flex;align-items:center"><i class="el-icon-document"></i> 同步日志</span></template>
        <div v-loading="loading">
          <h4>最近同步记录</h4>
          <el-table :data="syncLogs || []" stripe empty-text="暂无数据">
            <el-table-column prop="ts" label="时间" width="160"/>
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }"><StatusTag :type="row.status"/></template>
            </el-table-column>
            <el-table-column prop="duration_ms" label="耗时 (ms)" />
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>
  </el-card>
</template>

<style scoped lang="scss">
.device-detail .sync-panel { margin-top:16px; }
.status-success { color:#67c23a;font-weight:500;}
.status-failed{ color:#f56c6c;font-weight:500;}
</style>

