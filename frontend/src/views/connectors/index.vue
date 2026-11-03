<template>
  <div class="connector-index">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>连接器管理</span>
          <el-button size="small" :loading="loading" @click="fetchConnectors">刷新</el-button>
        </div>
      </template>

      <el-table :data="connectors" stripe v-loading="loading">
        <template #empty><el-empty description="暂无连接器数据" /></template>
        <el-table-column prop="name" label="名称" width="150" />
        <el-table-column prop="type" label="类型" width="100" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'warning'" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <!-- The actions, named one by one.  A card that said "Amazon SP-API 集成"
             advertised four outbound calls that this build does not perform. -->
        <el-table-column label="可用能力">
          <template #default="{ row }">
            <el-tag v-for="(state, action) in row.capabilities" :key="action"
                    :type="capabilityTag(state)" size="small" style="margin:2px 4px 2px 0">
              {{ capabilityLabel(action) }}: {{ capabilityStateLabel(state) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="凭据" width="230">
          <template #default="{ row }">
            <div v-for="c in row.credentials" :key="c.env" style="font-size:12px;line-height:1.6">
              <el-tag :type="c.set ? 'success' : 'info'" size="small" style="margin-right:4px">
                {{ c.set ? '已配置' : '未配置' }}
              </el-tag>
              {{ c.env }}<span v-if="c.value"> = {{ c.value }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small"
                       @click="$router.push(`/connectors/${row.type}-config/${row.id}`)">配置说明</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-alert v-if="notice" type="warning" :title="notice" show-icon closable style="margin-top:12px" />
      <p v-for="row in connectors" :key="row.id" style="font-size:12px;color:#909399;margin-top:8px">
        {{ row.name }}：{{ row.note }}
      </p>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'
import { errText } from '../../api/errors'

interface CredentialField { env: string; set?: boolean | null; value?: string | null }

interface ConnectorStatusResponse {
  id: string
  name: string
  type: string
  status: string
  configured: boolean
  last_sync?: string | null
  capabilities: Record<string, string>
  credentials: CredentialField[]
  note: string
}

const loading = ref(false)
const connectors = ref<ConnectorStatusResponse[]>([])
const notice = ref('')

const statusLabel = (s: string) =>
  ({ active: '可用', not_configured: '未配置', disabled: '已停用' } as Record<string, string>)[s] ?? s

const capabilityTag = (state: string) =>
  ({ implemented: 'success', not_implemented: 'warning', not_available: 'info' } as Record<string, 'success' | 'warning' | 'info'>)[state] ?? 'info'

const capabilityStateLabel = (state: string) =>
  ({ implemented: '已实现', not_implemented: '未实现', not_available: '不适用' } as Record<string, string>)[state] ?? state

const CAPABILITY_LABELS: Record<string, string> = {
  order_import: '订单导入',
  order_push: '订单推送',
  fulfillment_push: '发货推送',
  tracking_handover_record: '交接记录',
  tracking_upload: '运单回传',
  order_status_poll: '状态轮询',
  order_pull: '订单拉取',
  inventory_sync: '库存同步',
}
const capabilityLabel = (action: string) => CAPABILITY_LABELS[action] ?? action

async function fetchConnectors() {
  loading.value = true
  try {
    const res = await apiClient.get('/connectors/status')
    connectors.value = (res.data as any)?.data ?? res.data ?? []
    notice.value = ''
  } catch (e: any) {
    // The fetch used to end in console.warn alone: the operator saw an empty
    // table with the words 暂无连接器数据 and no hint that the page had asked
    // for a URL the API never had.
    connectors.value = []
    notice.value = errText(e, '连接器列表获取失败')
    ElMessage.error(notice.value)
  } finally {
    loading.value = false
  }
}

onMounted(fetchConnectors)
</script>

<style scoped>
.connector-index { padding:16px; }
</style>
