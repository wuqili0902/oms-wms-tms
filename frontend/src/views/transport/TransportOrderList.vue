<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>运输管理</span>
          <div>
            <el-button @click="downloadCSV('/admin/export/transport-orders', 'transport_orders.csv')">导出 CSV</el-button>
            <el-button type="primary" @click="showCreate = true">新建运单</el-button>
            <el-button @click="showFreightDialog = true">运费估算</el-button>
          </div>
        </div>
      </template>

      <el-form :model="filters" inline>
        <el-form-item label="状态">
          <el-select v-model="filters.status" placeholder="全部" clearable style="width:140px" @change="fetchOrders">
            <el-option label="草稿" value="draft" />
            <el-option label="已发车" value="dispatched" />
            <el-option label="在途" value="in_transit" />
            <el-option label="派送中" value="out_for_delivery" />
            <el-option label="已签收" value="delivered" />
            <el-option label="异常" value="exception" />
            <el-option label="已取消" value="cancelled" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="fetchOrders">刷新</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="orders" stripe v-loading="loading" style="width:100%">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="order_no" label="运单号" width="180" />
        <el-table-column prop="driver_name" label="司机" width="100" />
        <el-table-column prop="plate_no" label="车牌号" width="120" />
        <el-table-column prop="origin" label="出发地" width="130" />
        <el-table-column prop="destination" label="目的地" width="130" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="175" />
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="viewDetail(row)">详情</el-button>
            <el-button size="small" type="success" link @click="viewTracking(row)">追踪</el-button>
            <el-button size="small" type="info" link @click="viewRoute(row)">路由</el-button>
            <el-dropdown trigger="click" @command="(s:string)=>updateStatus(row,s)">
              <el-button size="small" type="warning" link>
                状态<el-icon><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="dispatched">发车</el-dropdown-item>
                  <el-dropdown-item command="in_transit">在途</el-dropdown-item>
                  <el-dropdown-item command="out_for_delivery">派送中</el-dropdown-item>
                  <el-dropdown-item command="delivered">签收</el-dropdown-item>
                  <el-dropdown-item command="cancelled">取消</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>

      <div style="display:flex;justify-content:flex-end;margin-top:16px">
        <el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="fetchOrders" />
      </div>
    </el-card>

    <el-dialog v-model="showCreate" title="新建运单" width="600px" destroy-on-close>
      <el-form :model="createForm" label-width="120px">
        <el-form-item label="承运商">
          <el-select v-model="createForm.carrier_code" style="width:100%">
            <el-option label="顺丰" value="sf_express" />
            <el-option label="中通" value="zto" />
            <el-option label="韵达" value="yunda" />
            <el-option label="京东物流" value="jd_logistics" />
            <el-option label="EMS" value="ems" />
          </el-select>
        </el-form-item>
        <el-form-item label="发货仓库ID" prop="pickup_warehouse_id">
          <el-input v-model="createForm.pickup_warehouse_id" placeholder="仓库UUID" />
        </el-form-item>
        <el-form-item label="收货人">
          <el-input v-model="createForm.delivery_name" placeholder="收货人姓名" />
        </el-form-item>
        <el-form-item label="出发城市">
          <el-input v-model="createForm.pickup_city" placeholder="如: 上海" />
        </el-form-item>
        <el-form-item label="目的城市">
          <el-input v-model="createForm.delivery_city" placeholder="如: 北京" />
        </el-form-item>
        <el-form-item label="司机">
          <el-input v-model="createForm.driver_name" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="createForm.notes" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showTrackingDialog" title="运输追踪" width="700px" destroy-on-close>
      <template v-if="trackingOrder">
        <p style="margin-bottom:12px;font-weight:600">运单号：{{ trackingOrder.order_no }}</p>
        <el-timeline>
          <el-timeline-item
            v-for="(evt, idx) in trackingEvents"
            :key="idx"
            :timestamp="evt.created_at"
            :type="evt.event_type === 'delivered' ? 'success' : 'primary'"
          >
            {{ eventLabel(evt.event_type) }}
            <p v-if="evt.location" style="font-size:12px;color:#909399">{{ evt.location }}</p>
          </el-timeline-item>
          <el-timeline-item v-if="trackingEvents.length === 0" timestamp="—">
            暂无追踪记录
          </el-timeline-item>
        </el-timeline>
      </template>
    </el-dialog>

    <el-dialog v-model="showRouteDialog" title="路由计划" width="650px" destroy-on-close>
      <template v-if="routePlan">
        <el-steps :active="routePlan.segments?.length || 0" align-center>
          <el-step v-for="(seg, idx) in routePlan.segments" :key="idx" :title="seg.from_location" :description="seg.to_location" />
        </el-steps>
        <el-table :data="routePlan.segments||[]" stripe style="margin-top:16px">
          <template #empty><el-empty description="暂无数据" /></template>
          <el-table-column prop="from_location" label="起点" width="150" />
          <el-table-column prop="to_location" label="终点" width="150" />
          <el-table-column prop="carrier" label="承运商" width="120" />
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-dialog>

    <el-dialog v-model="showFreightDialog" title="运费估算" width="500px" destroy-on-close>
      <el-form :model="freightForm" label-width="100px">
        <el-form-item label="承运商">
          <el-select v-model="freightForm.carrier" style="width:100%">
            <el-option label="顺丰" value="sf" />
            <el-option label="中通" value="zto" />
            <el-option label="韵达" value="yunda" />
            <el-option label="京东物流" value="jd" />
            <el-option label="EMS" value="ems" />
          </el-select>
        </el-form-item>
        <el-form-item label="出发地">
          <el-input v-model="freightForm.origin" placeholder="城市名" />
        </el-form-item>
        <el-form-item label="目的地">
          <el-input v-model="freightForm.destination" placeholder="城市名" />
        </el-form-item>
        <el-form-item label="重量(kg)">
          <el-input-number v-model="freightForm.weight_kg" :min="0.1" :precision="1" style="width:100%" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="freightLoading" @click="estimateFreight">估算</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="freightResult" type="success" show-icon style="margin-top:12px">
        <template #title>
          预估运费：¥{{ freightResult.estimated_cost_yuan }} | 预计 {{ freightResult.estimated_days }} 天
        </template>
      </el-alert>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import apiClient from '../../api'
import { useExport } from '../../composables/useExport'

const { downloadCSV } = useExport()
const router = useRouter()
const loading = ref(false)
const creating = ref(false)
const orders = ref<any[]>([])
const page = ref(1)
const total = ref(0)
const showCreate = ref(false)
const showTrackingDialog = ref(false)
const showRouteDialog = ref(false)
const trackingOrder = ref<any>(null)
const trackingEvents = ref<any[]>([])
const routePlan = ref<any>(null)
const showFreightDialog = ref(false)
const freightLoading = ref(false)
const freightResult = ref<any>(null)
const freightForm = reactive({ carrier: 'sf', origin: '', destination: '', weight_kg: 1.0 })

const filters = reactive({ status: '' })
const createForm = reactive({
  carrier_code: 'sf_express',
  pickup_warehouse_id: '',
  delivery_name: '',
  pickup_city: '',
  delivery_city: '',
  driver_name: '',
  notes: '',
})

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

async function fetchOrders() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    params.set('page', String(page.value))
    params.set('page_size', '20')
    if (filters.status) params.set('status', filters.status)
    const res = await apiClient.get(`/transport-orders?${params}`)
    const body = res.data?.data ?? res.data ?? {}
    orders.value = body.items ?? []
    total.value = body.total ?? 0
  } catch { orders.value = []; total.value = 0 }
  loading.value = false
}

function viewDetail(row: any) {
  router.push(`/transport/${row.id}`)
}

async function viewTracking(row: any) {
  trackingOrder.value = row
  showTrackingDialog.value = true
  try {
    const res = await apiClient.get(`/transport-orders/${row.id}/tracking`)
    const body = res.data?.data ?? res.data ?? []
    trackingEvents.value = Array.isArray(body) ? body : []
  } catch { trackingEvents.value = [] }
}

async function viewRoute(row: any) {
  routePlan.value = null
  try {
    const createRes = await apiClient.post(`/transport-orders/${row.id}/route-plans`)
    const planId = createRes.data?.data?.id ?? createRes.data?.id
    if (planId) {
      const res = await apiClient.get(`/route-plans/${planId}`)
      routePlan.value = res.data?.data ?? res.data
      showRouteDialog.value = true
    }
  } catch { /* ignore */ }
}

async function updateStatus(row: any, status: string) {
  if (status === 'cancelled') {
    try { await ElMessageBox.confirm('确定取消此运单？', '确认', { type: 'warning' }) } catch { return }
  }
  try {
    await apiClient.put(`/transport-orders/${row.id}/status?status=${status}`)
    ElMessage.success(`已更新为 ${statusLabel(status)}`)
    fetchOrders()
  } catch { /* ignore */ }
}

async function estimateFreight() {
  freightLoading.value = true
  freightResult.value = null
  try {
    const res = await apiClient.post('/freight-estimate', freightForm)
    freightResult.value = res.data?.data ?? res.data
  } catch { /* ignore */ }
  freightLoading.value = false
}

async function submitCreate() {
  creating.value = true
  try {
    const payload: any = { carrier_code: createForm.carrier_code }
    if (createForm.pickup_warehouse_id) payload.pickup_warehouse_id = createForm.pickup_warehouse_id
    if (createForm.delivery_name) payload.delivery_name = createForm.delivery_name
    if (createForm.pickup_city) payload.pickup_address = { city: createForm.pickup_city }
    if (createForm.delivery_city) payload.delivery_address = { city: createForm.delivery_city }
    if (createForm.driver_name) payload.driver_name = createForm.driver_name
    if (createForm.notes) payload.notes = createForm.notes
    await apiClient.post('/transport-orders', payload)
    ElMessage.success('创建成功')
    showCreate.value = false
    fetchOrders()
  } catch { /* ignore */ }
  creating.value = false
}

onMounted(fetchOrders)
</script>
