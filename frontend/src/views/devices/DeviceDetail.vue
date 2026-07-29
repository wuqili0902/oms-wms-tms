<script setup lang="ts">
import { ref, onMounted } from 'vue'
import apiClient from '../../api'

const props = defineProps<{ params: { dev_id: string } }>()

const device = ref<any>({})
const sessions = ref<any[]>([])
const syncLogs = ref<any[]>([])
const loading = ref(false)
const tabs = ref(['sessions', 'sync'] as const)
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
      <el-tab-pane label="会话" name="sessions"></el-tab-pane>
      <el-tab-pane label="同步日志" name="sync"></el-tab-pane>
    </el-tabs>

    <!-- Sessions 面板 -->
    <el-row :gutter="12" v-loading="loading">
      <el-col :span="8">
        <el-button type="primary" @click="createSession">创建会话</el-button>
      </el-col>
      <el-col :flex="1"></el-col>
    </el-row>

    <!-- 同步日志面板 -->
    <div class="sync-panel">
      <h4>最近同步记录</h4>
      <el-table v-loading="loading" :data="syncLogs || []" stripe empty-text="暂无数据">
        <el-table-column prop="ts" label="时间" width="160"/>
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }"><StatusTag :type="row.status"/></template>
        </el-table-column>
        <el-table-column prop="duration_ms" label="耗时 (ms)" />
      </el-table>
    </div>
  </el-card>
</template>

<style scoped lang="scss">
.device-detail .sync-panel { margin-top:16px; }
.status-success { color:#67c23a;font-weight:500;}
.status-failed{ color:#f56c6c;font-weight:500;}
</style>

<script setup lang="ts">
import { ElMessage, type UploadProps } from 'element-plus'
import { StatusTag } from '@/components/StatusTag.vue'
import apiClient from '../../api'

function getStatusColor(status?: string) {
  return (status ?? '').toLowerCase() === 'online' ? 'success' : ''
}

async function fetchDevice(): Promise<void> {
  try {
    device.value = await apiClient.get(`/devices/${props.params.dev_id}`)
  } catch { /* ignore */ }
}

async function createSession(): Promise<void> {
  try {
    const res = await apiClient.post(`/devices/${props.params.dev_id}/sessions`)
    ElMessage.success('会话已创建')
  } catch { /* ignore */ }
}

function fetchSessions(): void {}

async function fetchSyncLogs(): Promise<void> {
  try {
    syncLogs.value = await apiClient.get(`/devices/${props.params.dev_id}/sync`) as any[]
  } catch { /* ignore */ }
}

onMounted(() => { fetchDevice(); fetchSyncLogs() })
</script>