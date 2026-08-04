<template>
  <div>
    <el-card>
      <!-- 实时通知徽章（WebSocket） -->
      <el-badge :value="liveBadge" type="dot" class="live-badge"></el-badge>

      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>通知中心</span>
          <div>
            <el-button size="small" @click="showPreferences = true">偏好设置</el-button>
            <el-button size="small" @click="markAllRead">全部标为已读</el-button>
          </div>
        </div>
      </template>
      <el-table :data="notifications" stripe v-loading="loading" @row-click="markRead">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column width="40">
          <template #default="{ row }">
            <el-badge :hidden="row.is_read" is-dot style="margin-left:8px" />
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="200">
          <template #default="{ row }">
            <span :style="{ fontWeight: row.is_read ? 'normal' : 'bold' }">{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="body" label="内容" min-width="300" />
        <el-table-column prop="created_at" label="时间" width="175" />
      </el-table>
      <div style="display:flex;justify-content:flex-end;margin-top:12px">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="onPageChange" @size-change="onSizeChange" />
      </div>
    </el-card>

    <el-dialog v-model="showPreferences" title="通知偏好设置" width="500px" destroy-on-close @closed="resetPrefForm">
      <el-form :model="prefForm" label-width="160px">
        <el-form-item label="订单状态通知">
          <el-switch v-model="prefForm.order_updates" />
        </el-form-item>
        <el-form-item label="库存预警通知">
          <el-switch v-model="prefForm.inventory_alerts" />
        </el-form-item>
        <el-form-item label="运输异常通知">
          <el-switch v-model="prefForm.transport_exceptions" />
        </el-form-item>
        <el-form-item label="系统通知">
          <el-switch v-model="prefForm.system_notifications" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showPreferences = false">取消</el-button>
        <el-button type="primary" :loading="prefLoading" @click="submitPreferences">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { usePagination } from '../../composables/usePagination'
import apiClient from '../../api'

const loading = ref(false)
const notifications = ref<any[]>([])
const showPreferences = ref(false)
const prefLoading = ref(false)
const liveBadge = ref(0)
let ws: any = null
const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()

function reconnect(): void {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${protocol}//${location.host}/api/v1/notifications/ws?token=` + btoa(JSON.stringify({ uid: localStorage.getItem('uid') }))
  ws?.close?.(1006)
  try {
    ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'
    ws.onopen = () => {}
    ws.onerror = () => {}
    ws.onmessage = (e: any) => {
      const msg = JSON.parse(e.data ?? '{}')
      if (!msg.is_read) notifications.value.unshift(msg as any)
      liveBadge.value++
      setTimeout(() => (liveBadge.value -= 1), 3000)
    }
    } catch (e: any) { console.warn('[notifications] reconnect failed:', e?.response?.data ?? e) }
}

function closeWs(): void { ws?.close?.(1006) }
const prefForm = reactive({
  order_updates: true, inventory_alerts: true,
  transport_exceptions: true, system_notifications: true,
})

async function fetchNotifications() {
  loading.value = true
  try {
    const res = await apiClient.get(`/notifications?page=${page.value}&page_size=${pageSize.value}`)
    const d = res.data?.data ?? res.data ?? []
    let items
    if (Array.isArray(d)) { items = d; total.value = d.length }
    else { items = d.items ?? []; total.value = d.total ?? d.items?.length ?? 0 }
    notifications.value = items
  } catch (e: any) { console.warn('[notifications] fetchNotifications failed:', e?.response?.data ?? e); notifications.value = [] }
  loading.value = false
}

async function markRead(row: any) {
  if (row.is_read) return
  try {
    await apiClient.post(`/notifications/${row.id}/read`)
    row.is_read = true
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '标记已读失败') }
}

async function markAllRead() {
  try {
    await apiClient.post('/notifications/read-all')
    ElMessage.success('已全部标为已读')
    notifications.value.forEach(n => (n.is_read = true))
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '标记全部已读失败') }
}

async function fetchPreferences() {
  try {
    const res = await apiClient.get('/notifications/preferences')
    const p = res.data?.data ?? res.data
    if (p) Object.assign(prefForm, p)
  } catch (e: any) { console.warn('[notifications] fetchPreferences failed:', e?.response?.data ?? e) }
}

function resetPrefForm() { Object.assign(prefForm, { order_updates: true, inventory_alerts: true, transport_exceptions: true, system_notifications: true }) }

async function submitPreferences() {
  prefLoading.value = true
  try {
    await apiClient.put('/notifications/preferences', prefForm)
    ElMessage.success('偏好设置已保存')
    showPreferences.value = false
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '保存失败') }
  prefLoading.value = false
}

onMounted(() => { fetchNotifications(); fetchPreferences(); reconnect() })

onUnmounted(closeWs)
</script>
