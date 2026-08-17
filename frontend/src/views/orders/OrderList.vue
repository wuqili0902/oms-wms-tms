<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>订单管理</span>
          <div>
            <el-button @click="downloadCSV('/admin/export/orders', 'orders.csv')">导出 CSV</el-button>
            <el-button type="primary" @click="showCreate = true">新建订单</el-button>
          </div>
        </div>
      </template>

      <el-form :model="filters" inline>
        <el-form-item label="状态">
          <el-select v-model="filters.status" placeholder="全部" clearable style="width:130px" @change="fetchOrders">
            <el-option label="草稿" value="draft" />
            <el-option label="已确认" value="confirmed" />
            <el-option label="处理中" value="processing" />
            <el-option label="拣货中" value="picking" />
            <el-option label="已完成" value="completed" />
            <el-option label="已取消" value="cancelled" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="fetchOrders">刷新</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="orders" stripe v-loading="loading" style="width:100%" @row-dblclick="viewDetail">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="order_no" label="订单号" width="180" />
        <el-table-column prop="customer_id" label="客户ID" width="160" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="80">
          <template #default="{ row }">
            <el-tag :type="priorityType(row.priority)" size="small">{{ row.priority }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total_amount" label="金额" width="130">
          <template #default="{ row }">¥{{ Number(row.total_amount).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="175" />
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="viewDetail(row)">详情</el-button>
            <el-button size="small" type="warning" link :disabled="row.status!=='draft'" @click="handleStatus(row,'confirmed')">确认</el-button>
            <el-button size="small" type="success" link :disabled="row.status==='completed'||row.status==='cancelled'" @click="handleSplit(row)">拆单</el-button>
            <el-button size="small" type="info" link :disabled="row.status==='completed'||row.status==='cancelled'" @click="handleMerge(row)">合并</el-button>
            <el-button size="small" type="danger" link :disabled="row.status==='cancelled'" @click="handleCancel(row)">取消</el-button>
            <el-button size="small" type="danger" link :disabled="row.status!=='draft'" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div style="display:flex;justify-content:flex-end;margin-top:16px">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="fetchOrders"
        />
      </div>
    </el-card>

    <el-dialog v-model="showCreate" title="新建订单" width="700px" destroy-on-close>
      <el-form :model="createForm" label-width="100px" :rules="createRules" ref="createFormRef">
        <el-form-item label="客户ID" prop="customer_id">
          <el-input v-model="createForm.customer_id" placeholder="客户ID" />
        </el-form-item>
        <el-form-item label="优先级" prop="priority">
          <el-select v-model="createForm.priority" style="width:100%">
            <el-option label="低" value="low" />
            <el-option label="中" value="medium" />
            <el-option label="高" value="high" />
            <el-option label="紧急" value="urgent" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="createForm.notes" type="textarea" :rows="3" />
        </el-form-item>
        <el-divider>订单项</el-divider>
        <el-form-item v-for="(item, idx) in createForm.items" :key="idx" :label="`商品 ${idx+1}`">
          <div style="display:flex;gap:8px;flex-wrap:wrap;width:100%">
            <el-input v-model="item.sku" placeholder="SKU" style="width:130px" />
            <el-input v-model="item.gtin" placeholder="GTIN" style="width:140px" />
            <el-input v-model="item.product_name" placeholder="名称" style="width:140px" />
            <el-input-number v-model="item.quantity" :min="1" :max="99999" style="width:130px" />
            <el-input-number v-model="item.unit_price" :min="0" :precision="2" style="width:140px" />
            <el-button type="danger" :icon="Delete" circle size="small" @click="removeItem(idx)" />
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="warning" @click="addItem">+ 添加商品</el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showSplit" title="拆单" width="600px" destroy-on-close>
      <p style="margin-bottom:12px;color:#909399">将订单 <strong>{{ currentOrder?.order_no }}</strong> 拆分为多个子订单</p>
      <el-form :model="splitForm" label-width="80px">
        <el-form-item v-for="(s, idx) in splitForm.splits" :key="idx" :label="`子单 ${idx+1}`">
          <div style="display:flex;gap:8px;width:100%">
            <el-input v-model="s.sku" placeholder="SKU" style="width:150px" />
            <el-input-number v-model="s.quantity" :min="1" style="width:130px" />
            <el-button type="danger" :icon="Delete" circle size="small" @click="splitForm.splits.splice(idx,1)" />
          </div>
        </el-form-item>
        <el-form-item>
          <el-button @click="splitForm.splits.push({sku:'',quantity:1})">+ 添加</el-button>
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="splitForm.reason" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSplit = false">取消</el-button>
        <el-button type="primary" :loading="splitting" @click="submitSplit">确认拆分</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showMerge" title="合并订单" width="500px" destroy-on-close>
      <p style="margin-bottom:12px;color:#909399">将当前订单与其他订单合并</p>
      <el-form :model="mergeForm" label-width="80px">
        <el-form-item label="订单ID">
          <el-input v-model="mergeForm.order_ids_text" type="textarea" :rows="3" placeholder="每行一个订单ID" />
        </el-form-item>
        <el-form-item label="仓库">
          <el-input v-model="mergeForm.warehouse_id" placeholder="仓库ID（可选）" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="mergeForm.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showMerge = false">取消</el-button>
        <el-button type="primary" :loading="merging" @click="submitMerge">确认合并</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import apiClient from '../../api'
import { useExport } from '../../composables/useExport'
import type { Order } from '../../api/types'
import type { FormInstance, FormRules } from 'element-plus'

const { downloadCSV } = useExport()
const router = useRouter()
const route = useRoute()
const loading = ref(false)
const creating = ref(false)
const splitting = ref(false)
const merging = ref(false)
const orders = ref<Order[]>([])
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const showCreate = ref(false)
const showSplit = ref(false)
const showMerge = ref(false)
const currentOrder = ref<Order | null>(null)
const createFormRef = ref<FormInstance>()

const filters = reactive({ status: '' })

const createForm = reactive({
  customer_id: '',
  priority: 'medium',
  notes: '',
  items: [{ sku: '', gtin: '', product_name: '', quantity: 1, unit_price: 0 }],
})

const createRules: FormRules = {
  customer_id: [{ required: true, message: '请输入客户ID', trigger: 'blur' }],
  priority: [{ required: true, message: '请选择优先级', trigger: 'change' }],
}

const splitForm = reactive({ splits: [{ sku: '', quantity: 1 }], reason: '' })
const mergeForm = reactive({ order_ids_text: '', warehouse_id: '', note: '' })

function statusLabel(s: string) {
  const map: Record<string, string> = { draft: '草稿', confirmed: '已确认', processing: '处理中', picking: '拣货中', completed: '已完成', cancelled: '已取消', failed: '失败' }
  return map[s] || s
}

function statusType(s: string) {
  const map: Record<string, string> = { draft: 'info', confirmed: 'primary', processing: 'warning', picking: 'warning', completed: 'success', cancelled: 'danger', failed: 'danger' }
  return map[s] || 'info'
}

function priorityType(s: string) {
  const map: Record<string, string> = { low: 'info', medium: '', high: 'warning', urgent: 'danger' }
  return map[s] || 'info'
}

async function fetchOrders() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    params.set('page', String(page.value))
    params.set('page_size', String(pageSize.value))
    if (filters.status) params.set('status', filters.status)
    const res = await apiClient.get(`/orders?${params}`)
    const data = res.data ?? {}
    orders.value = data.items ?? []
    total.value = data.total ?? 0
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? e.message) }
  loading.value = false
}

function viewDetail(row: Order) {
  router.push(`/orders/${row.id}`)
}

function addItem() {
  createForm.items.push({ sku: '', gtin: '', product_name: '', quantity: 1, unit_price: 0 })
}

function removeItem(idx: number) {
  createForm.items.splice(idx, 1)
}

async function submitCreate() {
  const valid = await createFormRef.value?.validate().catch(() => false)
  if (!valid) return
  creating.value = true
  try {
    await apiClient.post('/orders', createForm)
    ElMessage.success('创建成功')
    showCreate.value = false
    fetchOrders()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? e.message) }
  creating.value = false
}

async function handleStatus(row: Order, status: string) {
  try {
    await apiClient.put(`/orders/${row.id}/status`, { status })
    ElMessage.success(`订单已${statusLabel(status)}`)
    fetchOrders()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? e.message) }
}

async function handleCancel(row: Order) {
  try {
    await ElMessageBox.confirm(`确定取消订单 ${row.order_no}？`, '提示')
    await apiClient.put(`/orders/${row.id}/status`, { status: 'cancelled' })
    ElMessage.success('已取消')
    fetchOrders()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? e.message) }
}

async function handleDelete(row: Order) {
  try {
    await ElMessageBox.confirm(`确定删除订单 ${row.order_no}？此操作不可恢复。`, '提示', { type: 'warning' })
    await apiClient.delete(`/orders/${row.id}`)
    ElMessage.success('已删除')
    fetchOrders()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? e.message) }
}

function handleSplit(row: Order) {
  currentOrder.value = row
  splitForm.splits = [{ sku: '', quantity: 1 }]
  splitForm.reason = ''
  showSplit.value = true
}

async function submitSplit() {
  splitting.value = true
  try {
    await apiClient.post(`/orders/${currentOrder.value!.id}/split`, { splits: splitForm.splits, reason: splitForm.reason })
    ElMessage.success('拆单成功')
    showSplit.value = false
    fetchOrders()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? e.message) }
  splitting.value = false
}

function handleMerge(row: Order) {
  currentOrder.value = row
  mergeForm.order_ids_text = String(row.id)
  mergeForm.warehouse_id = ''
  mergeForm.note = ''
  showMerge.value = true
}

async function submitMerge() {
  merging.value = true
  try {
    const orderIds = mergeForm.order_ids_text.split('\n').map(s => s.trim()).filter(Boolean)
    await apiClient.post('/orders/merge', { order_ids: orderIds, warehouse_id: mergeForm.warehouse_id || undefined, note: mergeForm.note })
    ElMessage.success('合并成功')
    showMerge.value = false
    fetchOrders()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? e.message) }
  merging.value = false
}

onMounted(() => {
  if (route.query.action === 'create') showCreate.value = true
  fetchOrders()
})
</script>
