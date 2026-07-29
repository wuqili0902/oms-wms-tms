<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>退货管理</span>
          <div>
            <el-button @click="downloadCSV('/admin/export/returns', 'returns.csv')">导出 CSV</el-button>
            <el-button type="primary" @click="showCreate = true">新建退货单</el-button>
          </div>
        </div>
      </template>
      <el-form :model="filter" inline style="margin-bottom:12px">
        <el-form-item label="退货单号"><el-input v-model="filter.return_no" placeholder="退货单号" clearable style="width:180px" @clear="fetchReturns" @keyup.enter="fetchReturns" /></el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filter.status" clearable style="width:120px" @change="fetchReturns">
            <el-option label="待处理" value="pending" /><el-option label="已完成" value="completed" /><el-option label="已取消" value="cancelled" />
          </el-select>
        </el-form-item>
        <el-form-item><el-button type="primary" @click="fetchReturns">查询</el-button></el-form-item>
      </el-form>
      <el-table :data="returns" stripe v-loading="loading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="return_no" label="退货单号" width="180" />
        <el-table-column prop="order_no" label="原订单号" width="180" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'completed' ? 'success' : 'warning'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="200" />
        <el-table-column prop="created_at" label="创建时间" width="175" />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="viewDetail(row)">详情</el-button>
            <el-button size="small" type="primary" link :disabled="row.status==='completed'" @click="updateStatus(row, 'completed')">完成</el-button>
            <el-button size="small" type="danger" link :disabled="row.status==='cancelled'" @click="updateStatus(row, 'cancelled')">取消</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="display:flex;justify-content:flex-end;margin-top:12px">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="onPageChange" @size-change="onSizeChange" />
      </div>
    </el-card>

    <el-dialog v-model="showDetail" title="退货单详情" width="650px" destroy-on-close>
      <template v-if="detail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="退货单号">{{ detail.return_no }}</el-descriptions-item>
          <el-descriptions-item label="原订单号">{{ detail.order_no }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="detail.status === 'completed' ? 'success' : 'warning'" size="small">{{ detail.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ detail.created_at }}</el-descriptions-item>
          <el-descriptions-item label="原因" :span="2">{{ detail.reason || '无' }}</el-descriptions-item>
        </el-descriptions>
        <el-descriptions v-if="detail.resolution_notes" style="margin-top:12px" :column="1" border>
          <el-descriptions-item label="处理备注">{{ detail.resolution_notes }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>

    <el-dialog v-model="showCreate" title="新建退货单" width="500px" destroy-on-close @closed="resetCreateForm">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="原订单号">
          <el-input v-model="createForm.order_no" />
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="createForm.reason" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePagination } from '../../composables/usePagination'
import { useExport } from '../../composables/useExport'
import apiClient from '../../api'

const { downloadCSV } = useExport()
const loading = ref(false)
const creating = ref(false)
const returns = ref<any[]>([])
const showCreate = ref(false)
const showDetail = ref(false)
const detail = ref<any>(null)
const filter = reactive({ return_no: '', status: '' })
const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()
const createForm = reactive({ order_no: '', reason: '' })

async function fetchReturns() {
  loading.value = true
  try {
    const params = new URLSearchParams({ page: String(page.value), page_size: String(pageSize.value) })
    if (filter.return_no) params.set('return_no', filter.return_no)
    if (filter.status) params.set('status', filter.status)
    const res = await apiClient.get(`/return-orders?${params}`)
    const d = res.data?.data ?? res.data ?? []
    let items
    if (Array.isArray(d)) { items = d; total.value = d.length }
    else { items = d.items ?? []; total.value = d.total ?? d.items?.length ?? 0 }
    returns.value = items
  } catch { returns.value = [] }
  loading.value = false
}

function resetCreateForm() { createForm.order_no = ''; createForm.reason = '' }

async function submitCreate() {
  creating.value = true
  try {
    await apiClient.post('/return-orders', createForm)
    ElMessage.success('创建成功')
    showCreate.value = false
    fetchReturns()
  } catch { /* ignore */ }
  creating.value = false
}

async function updateStatus(row: any, status: string) {
  if (status === 'cancelled') {
    try { await ElMessageBox.confirm('确定取消此退货单？', '确认', { type: 'warning' }) } catch { return }
  }
  try {
    await apiClient.patch(`/return-orders/${row.id}/status`, { status })
    ElMessage.success(`已更新为 ${status}`)
    fetchReturns()
  } catch { /* ignore */ }
}

async function viewDetail(row: any) {
  detail.value = null; showDetail.value = true
  try {
    const res = await apiClient.get(`/return-orders/${row.id}`)
    detail.value = res.data?.data ?? res.data
  } catch { detail.value = { ...row } }
}

onMounted(fetchReturns)
</script>
