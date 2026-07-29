<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>采购单管理</span>
          <el-button type="primary" @click="showCreate = true">新建采购单</el-button>
        </div>
      </template>
      <el-form :model="filter" inline style="margin-bottom:12px">
        <el-form-item label="供应商"><el-input v-model="filter.vendor" placeholder="供应商名称/ID" clearable style="width:180px" @clear="fetchPOs" @keyup.enter="fetchPOs" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filter.status" clearable style="width:120px" @change="fetchPOs">
            <el-option label="草稿" value="draft" /><el-option label="已审批" value="approved" /><el-option label="已收货" value="received" /><el-option label="已取消" value="cancelled" />
          </el-select>
        </el-form-item>
        <el-form-item><el-button type="primary" @click="fetchPOs">查询</el-button></el-form-item>
      </el-form>
      <el-table :data="purchaseOrders" stripe v-loading="loading" style="width:100%">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="po_no" label="采购单号" width="180" />
        <el-table-column prop="vendor_name" label="供应商" width="150" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'approved' ? 'success' : row.status === 'received' ? 'info' : 'warning'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="total_amount" label="金额" width="130">
          <template #default="{ row }">¥{{ Number(row.total_amount||0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="175" />
        <el-table-column label="操作" width="260">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="viewDetail(row)">详情</el-button>
            <el-button size="small" type="success" link :disabled="row.status!=='draft'" @click="approve(row)">审批</el-button>
            <el-button size="small" type="primary" link :disabled="row.status!=='approved'" @click="receive(row)">收货</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="display:flex;justify-content:flex-end;margin-top:12px">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="onPageChange" @size-change="onSizeChange" />
      </div>
    </el-card>

    <el-dialog v-model="showCreate" title="新建采购单" width="600px" destroy-on-close @closed="resetCreateForm">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="供应商ID">
          <el-input v-model="createForm.vendor_id" placeholder="供应商UUID" />
        </el-form-item>
        <el-form-item label="仓库ID">
          <el-input v-model="createForm.warehouse_id" placeholder="仓库UUID" />
        </el-form-item>
        <el-divider>采购项</el-divider>
        <el-form-item v-for="(line, idx) in createForm.lines" :key="idx" :label="`项 ${idx+1}`">
          <div style="display:flex;gap:8px;width:100%">
            <el-input v-model="line.sku" placeholder="SKU" style="width:130px" />
            <el-input-number v-model="line.quantity" :min="1" style="width:120px" />
            <el-input-number v-model="line.unit_price" :min="0" :precision="2" style="width:130px" />
            <el-button type="danger" :icon="Delete" circle size="small" @click="removeLine(idx)" />
          </div>
        </el-form-item>
        <el-form-item>
          <el-button @click="addLine">+ 添加商品</el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showDetail" title="采购单详情" width="700px" destroy-on-close>
      <template v-if="detail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="采购单号">{{ detail.po_no }}</el-descriptions-item>
          <el-descriptions-item label="供应商">{{ detail.vendor_name || detail.vendor_id }}</el-descriptions-item>
          <el-descriptions-item label="仓库ID">{{ detail.warehouse_id }}</el-descriptions-item>
          <el-descriptions-item label="金额">¥{{ Number(detail.total_amount||0).toFixed(2) }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ detail.created_at }}</el-descriptions-item>
        </el-descriptions>
        <el-table v-if="detail.lines?.length" :data="detail.lines" stripe style="margin-top:12px">
          <template #empty><el-empty description="暂无数据" /></template>
          <el-table-column prop="sku" label="SKU" width="150" />
          <el-table-column prop="quantity" label="数量" width="80" />
          <el-table-column prop="unit_price" label="单价" width="120" />
          <el-table-column label="小计" width="120">
            <template #default="{ row }">¥{{ (row.quantity || 0) * (row.unit_price || 0) }}</template>
          </el-table-column>
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { usePagination } from '../../composables/usePagination'
import apiClient from '../../api'

const loading = ref(false)
const creating = ref(false)
const purchaseOrders = ref<any[]>([])
const showCreate = ref(false)
const showDetail = ref(false)
const detail = ref<any>(null)
const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()
const filter = reactive({ vendor: '', status: '' })
const createForm = reactive({
  vendor_id: '', warehouse_id: '',
  lines: [{ sku: '', quantity: 1, unit_price: 0 }],
})

async function fetchPOs() {
  loading.value = true
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize.value) })
    if (filter.vendor) params.set('vendor', filter.vendor)
    if (filter.status) params.set('status', filter.status)
    const res = await apiClient.get(`/warehouses/purchase-orders?${params}`)
    const d = res.data?.data ?? res.data ?? []
    let items
    if (Array.isArray(d)) { items = d; total.value = d.length }
    else { items = d.items ?? []; total.value = d.total ?? d.items?.length ?? 0 }
    purchaseOrders.value = items
  } catch { purchaseOrders.value = [] }
  loading.value = false
}

async function viewDetail(row: any) {
  detail.value = null; showDetail.value = true
  try {
    const res = await apiClient.get(`/warehouses/purchase-orders/${row.id}`)
    detail.value = res.data?.data ?? res.data
  } catch { detail.value = { ...row } }
}

function resetCreateForm() { Object.assign(createForm, { vendor_id: '', warehouse_id: '', lines: [{ sku: '', quantity: 1, unit_price: 0 }] }) }
function addLine() { createForm.lines.push({ sku: '', quantity: 1, unit_price: 0 }) }
function removeLine(idx: number) { createForm.lines.splice(idx, 1) }

async function submitCreate() {
  creating.value = true
  try {
    await apiClient.post('/warehouses/purchase-orders', createForm)
    ElMessage.success('创建成功')
    showCreate.value = false
    fetchPOs()
  } catch { /* ignore */ }
  creating.value = false
}

async function approve(row: any) {
  try {
    await apiClient.post(`/warehouses/purchase-orders/${row.id}/approve`)
    ElMessage.success('已审批')
    fetchPOs()
  } catch { /* ignore */ }
}

async function receive(row: any) {
  try {
    await apiClient.post(`/warehouses/purchase-orders/${row.id}/receive`)
    ElMessage.success('已收货')
    fetchPOs()
  } catch { /* ignore */ }
}

onMounted(fetchPOs)
</script>
