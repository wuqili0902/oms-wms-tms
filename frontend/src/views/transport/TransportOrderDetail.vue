<template>
  <div>
    <el-button text style="margin-bottom:12px" @click="$router.push('/transport')">
      <el-icon><ArrowLeft /></el-icon> 返回运输列表
    </el-button>

    <el-card v-loading="loading">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>运单详情：{{ order?.order_no }}</span>
          <div>
            <el-button size="small" @click="printOrder">打印</el-button>
            <el-tag :type="statusType(order?.status||'')" size="large">{{ statusLabel(order?.status||'') }}</el-tag>
          </div>
        </div>
      </template>

      <el-descriptions :column="2" border>
        <el-descriptions-item label="运单号">{{ order?.order_no }}</el-descriptions-item>
        <el-descriptions-item label="承运商">{{ order?.carrier_code }}</el-descriptions-item>
        <el-descriptions-item label="司机">{{ order?.driver_name || '—' }}</el-descriptions-item>
        <el-descriptions-item label="车牌号">{{ order?.plate_no || '—' }}</el-descriptions-item>
        <el-descriptions-item label="出发地">{{ order?.origin || '—' }}</el-descriptions-item>
        <el-descriptions-item label="目的地">{{ order?.destination || '—' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ order?.created_at }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ order?.updated_at }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card style="margin-top:16px">
      <template #header>
        <span>运输追踪</span>
        <el-button size="small" style="float:right" @click="showAddTracking = true">添加追踪事件</el-button>
      </template>
      <el-timeline>
        <el-timeline-item
          v-for="(evt, idx) in trackingEvents"
          :key="idx"
          :timestamp="evt.created_at"
          :type="evt.event_type === 'delivered' ? 'success' : 'primary'"
        >
          {{ eventLabel(evt.event_type) }}
          <p v-if="evt.location" style="font-size:12px;color:#909399">{{ evt.location }}</p>
          <p v-if="evt.remark" style="font-size:12px;color:#909399">{{ evt.remark }}</p>
        </el-timeline-item>
        <el-timeline-item v-if="trackingEvents.length === 0" timestamp="—">
          暂无追踪记录
        </el-timeline-item>
      </el-timeline>
    </el-card>

    <el-card style="margin-top:16px">
      <template #header>
        <span>签收凭证</span>
        <div style="float:right">
          <el-button v-if="!pod" size="small" type="primary" @click="showAddPod = true">录入签收</el-button>
          <el-button v-if="pod" size="small" @click="showEditPod = true">更新签收</el-button>
        </div>
      </template>
      <template v-if="pod">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="签收人">{{ pod.receiver_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="签收时间">{{ pod.delivery_time || '—' }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ pod.notes || '无' }}</el-descriptions-item>
        </el-descriptions>
        <div v-if="pod.photos?.length" style="display:flex;gap:8px;margin-top:12px">
          <el-image v-for="(url, idx) in pod.photos" :key="idx" :src="url" style="width:120px;height:120px;border-radius:4px;object-fit:cover" />
        </div>
      </template>
      <el-empty v-else description="暂无签收凭证" />
    </el-card>

    <div style="margin-top:12px;text-align:right">
      <el-button size="small" type="danger" @click="$router.push(`/transport/exceptions?order_id=${route.params.id}`)">报告异常</el-button>
    </div>

    <el-dialog v-model="showAddPod" title="录入签收凭证" width="500px" destroy-on-close>
      <el-form :model="podForm" label-width="100px">
        <el-form-item label="签收人"><el-input v-model="podForm.receiver_name" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="podForm.notes" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddPod = false">取消</el-button>
        <el-button type="primary" :loading="podLoading" @click="submitPod">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showEditPod" title="更新签收凭证" width="500px" destroy-on-close>
      <el-form :model="podForm" label-width="100px">
        <el-form-item label="签收人"><el-input v-model="podForm.receiver_name" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="podForm.notes" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditPod = false">取消</el-button>
        <el-button type="primary" :loading="podLoading" @click="submitEditPod">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showAddTracking" title="添加追踪事件" width="500px" destroy-on-close>
      <el-form :model="trackForm" label-width="100px">
        <el-form-item label="事件类型">
          <el-select v-model="trackForm.event_type" style="width:100%">
            <el-option label="已发车" value="dispatched" />
            <el-option label="提货完成" value="pickup_completed" />
            <el-option label="运输中" value="in_transit" />
            <el-option label="到达中转站" value="arrived_hub" />
            <el-option label="分拣中" value="sorting_center" />
            <el-option label="派送中" value="out_for_delivery" />
            <el-option label="已签收" value="delivered" />
            <el-option label="延迟异常" value="exception_delay" />
            <el-option label="破损异常" value="exception_damaged" />
          </el-select>
        </el-form-item>
        <el-form-item label="位置"><el-input v-model="trackForm.location" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddTracking = false">取消</el-button>
        <el-button type="primary" :loading="trackLoading" @click="submitTracking">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

const route = useRoute()
const order = ref<any>(null)
const loading = ref(false)
const trackingEvents = ref<any[]>([])
const pod = ref<any>(null)
const showAddPod = ref(false)
const showEditPod = ref(false)
const showAddTracking = ref(false)
const podLoading = ref(false)

function printOrder() { window.print() }
const trackLoading = ref(false)
const podForm = reactive({ receiver_name: '', notes: '' })
const trackForm = reactive({ event_type: 'in_transit', location: '' })

function statusLabel(s: string) {
  const map: Record<string, string> = { draft: '草稿', dispatched: '已发车', pickup_completed: '已提货', in_transit: '在途', out_for_delivery: '派送中', delivered: '已签收', exception: '异常', cancelled: '已取消' }
  return map[s] || s
}

function statusType(s: string) {
  const map: Record<string, string> = { draft: 'info', dispatched: 'primary', in_transit: 'warning', out_for_delivery: 'warning', delivered: 'success', exception: 'danger', cancelled: 'info' }
  return map[s] || 'info'
}

function eventLabel(t: string) {
  const map: Record<string, string> = { created: '已创建', dispatched: '已发车', pickup_completed: '提货完成', in_transit: '运输中', arrived_hub: '到达中转站', sorting_center: '分拣中', out_for_delivery: '派送中', delivered: '已签收', exception_delay: '延迟异常', exception_damaged: '破损异常', cancelled: '已取消' }
  return map[t] || t
}

async function submitPod() {
  podLoading.value = true
  try {
    await apiClient.post(`/transport-orders/${route.params.id}/pod`, podForm)
    ElMessage.success('签收凭证已录入')
    showAddPod.value = false
    const res = await apiClient.get(`/transport-orders/${route.params.id}/pod`)
    pod.value = res.data?.data ?? res.data
  } catch { /* ignore */ }
  podLoading.value = false
}

async function submitEditPod() {
  podLoading.value = true
  try {
    await apiClient.put(`/transport-orders/${route.params.id}/pod`, podForm)
    ElMessage.success('签收凭证已更新')
    showEditPod.value = false
    const res = await apiClient.get(`/transport-orders/${route.params.id}/pod`)
    pod.value = res.data?.data ?? res.data
  } catch { /* ignore */ }
  podLoading.value = false
}

async function submitTracking() {
  trackLoading.value = true
  try {
    await apiClient.post(`/transport-orders/${route.params.id}/tracking-events`, trackForm)
    ElMessage.success('追踪事件已添加')
    showAddTracking.value = false
    const res = await apiClient.get(`/transport-orders/${route.params.id}/tracking`)
    trackingEvents.value = (res.data?.data ?? res.data?.items ?? res.data) || []
  } catch { /* ignore */ }
  trackLoading.value = false
}

onMounted(async () => {
  const id = route.params.id as string
  if (!id) return
  loading.value = true
  try {
    const res = await apiClient.get(`/transport-orders/${id}`)
    order.value = res.data?.data ?? res.data
  } catch { /* ignore */ }
  loading.value = false

  try {
    const res = await apiClient.get(`/transport-orders/${id}/tracking`)
    trackingEvents.value = (res.data?.data ?? res.data?.items ?? res.data) || []
  } catch { /* ignore */ }

  try {
    const res = await apiClient.get(`/transport-orders/${id}/pod`)
    pod.value = res.data?.data ?? res.data
  } catch { pod.value = null }
})
</script>

<style>
@media print {
  .app-header, .app-aside, .el-button { display: none !important; }
  .app-main { padding: 0 !important; }
  .el-card { box-shadow: none !important; border: 1px solid #ddd !important; }
}
</style>
