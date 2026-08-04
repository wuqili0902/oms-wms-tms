<template>
  <div class="connector-index">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>连接器管理</span>
          <el-button type="primary" size="small" @click="$router.push('/connectors/amazon-config')">配置 Amazon</el-button>
        </div>
      </template>

      <el-table :data="connectors" stripe v-loading="loading">
        <template #empty><el-empty description="暂无连接器数据" /></template>
        <el-table-column prop="name" label="名称" width="180" />
        <el-table-column prop="type" label="类型" width="120">
          <template #default="{ row }">{{ formatType(row.type) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_sync" label="最后同步" width="175">
          <template #default="{ row }">{{ formatTime(row.last_sync) }}</template>
        </el-table-column>
        <el-table-column label="操作" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="$router.push(`/connectors/${row.type}-config`)" :disabled="!isConfigurable(row)">配置</el-button>
            <el-button type="success" size="small" @click="syncConnector(row.id)" :loading="syncing[row.id]">同步</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

interface ConnectorStatusResponse {
  id: string
  name: string
  type: string
  status: string
  last_sync?: string | null
}

const loading = ref(false)
const syncing = reactive({}) as Record<string, boolean>
const connectors = ref<ConnectorStatusResponse[]>([])

function formatType(type: string): string {
  return type.charAt(0).toUpperCase() + type.slice(1)
}

function formatTime(iso?: string | null): string {
  if (!iso) return '从未'
  const d = new Date(iso)
  return `${d.getMonth()+1}/${d.getDate()} ${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`
}

function isConfigurable(row: ConnectorStatusResponse): boolean {
  return row.type === 'amazon' || row.type === 'shopify'
}

async function fetchConnectors() {
  loading.value = true
  try {
    const res = await apiClient.get('/connectors/status')
    connectors.value = (res.data as any)?.data ?? res.data ?? []
  } catch (e: any) {
    console.warn('[connectors] fetchConnectors failed:', e?.response?.data ?? e)
    connectors.value = []
  } finally {
    loading.value = false
  }
}

async function syncConnector(id: string) {
  syncing[id] = true
  try {
    await apiClient.post(`/connectors/${id}/sync`)
    ElMessage.success('同步成功')
  } catch (e: any) {
    console.warn('[connectors] sync failed:', e?.response?.data ?? e)
    ElMessage.error(e?.response?.data?.detail ?? '同步失败')
  } finally {
    syncing[id] = false
  }
}

onMounted(fetchConnectors)
</script>

<style scoped>
.connector-index { padding:16px; }
</style>
