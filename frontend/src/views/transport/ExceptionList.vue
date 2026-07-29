<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>运输异常</span>
          <div>
            <el-button @click="downloadCSV('/admin/export/exceptions', 'exceptions.csv')">导出 CSV</el-button>
            <el-button type="primary" @click="showCreate = true">报告异常</el-button>
          </div>
        </div>
      </template>
      <el-table :data="exceptions" stripe v-loading="loading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="transport_order_no" label="运单号" width="160" />
        <el-table-column label="类型" width="140">
          <template #default="{ row }">
            <el-tag :type="row.exception_type === 'delayed' ? 'warning' : 'danger'" size="small">{{ row.exception_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="200" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'resolved' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="175" />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="viewDetail(row)">详情</el-button>
            <el-button size="small" type="success" link :disabled="row.status==='resolved'" @click="resolveException(row)">处理</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="display:flex;justify-content:flex-end;margin-top:12px">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="onPageChange" @size-change="onSizeChange" />
      </div>
    </el-card>

    <el-dialog v-model="showDetail" title="异常详情" width="600px" destroy-on-close>
      <template v-if="detail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="运单号">{{ detail.transport_order_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="类型">
            <el-tag :type="detail.exception_type === 'delayed' ? 'warning' : 'danger'" size="small">{{ detail.exception_type }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="detail.status === 'resolved' ? 'success' : 'danger'" size="small">{{ detail.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ detail.created_at }}</el-descriptions-item>
          <el-descriptions-item label="描述" :span="2">{{ detail.description || '无' }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.resolved_at" label="处理时间">{{ detail.resolved_at }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>

    <el-dialog v-model="showCreate" title="报告异常" width="500px" destroy-on-close @closed="resetCreateForm">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="运单号">
          <el-input v-model="createForm.transport_order_no" />
        </el-form-item>
        <el-form-item label="异常类型">
          <el-select v-model="createForm.exception_type" style="width:100%">
            <el-option label="延迟" value="delayed" />
            <el-option label="破损" value="damaged_in_transit" />
            <el-option label="丢失" value="lost" />
            <el-option label="地址错误" value="address_issue" />
            <el-option label="客户不在" value="customer_unavailable" />
            <el-option label="天气" value="weather" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showResolve" title="处理异常" width="500px" destroy-on-close @closed="resetResolveForm">
      <el-form :model="resolveForm" label-width="100px">
        <el-form-item label="处理备注">
          <el-input v-model="resolveForm.resolution_notes" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showResolve = false">取消</el-button>
        <el-button type="primary" :loading="resolving" @click="submitResolve">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { usePagination } from '../../composables/usePagination'
import { useExport } from '../../composables/useExport'
import apiClient from '../../api'

const { downloadCSV } = useExport()
const loading = ref(false)
const creating = ref(false)
const exceptions = ref<any[]>([])
const showCreate = ref(false)
const showDetail = ref(false)
const showResolve = ref(false)
const detail = ref<any>(null)
const resolveTarget = ref<any>(null)
const resolving = ref(false)
const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()
const resolveForm = reactive({ resolution_notes: '' })
const createForm = reactive({ transport_order_no: '', exception_type: 'delayed', description: '' })

async function fetchExceptions() {
  loading.value = true
  try {
    const res = await apiClient.get(`/exceptions?page=${page.value}&page_size=${pageSize.value}`)
    const d = res.data?.data ?? res.data ?? []
    let items
    if (Array.isArray(d)) { items = d; total.value = d.length }
    else { items = d.items ?? []; total.value = d.total ?? d.items?.length ?? 0 }
    exceptions.value = items
  } catch { exceptions.value = [] }
  loading.value = false
}

function resetCreateForm() { Object.assign(createForm, { transport_order_no: '', exception_type: 'delayed', description: '' }) }
function resetResolveForm() { resolveForm.resolution_notes = '' }

async function submitCreate() {
  creating.value = true
  try {
    await apiClient.post('/exceptions', createForm)
    ElMessage.success('异常已报告')
    showCreate.value = false
    fetchExceptions()
  } catch { /* ignore */ }
  creating.value = false
}

async function resolveException(row: any) {
  resolveTarget.value = row
  resolveForm.resolution_notes = ''
  showResolve.value = true
}

async function submitResolve() {
  resolving.value = true
  try {
    await apiClient.patch(`/exceptions/${resolveTarget.value.id}`, resolveForm)
    ElMessage.success('异常已处理')
    showResolve.value = false
    fetchExceptions()
  } catch { /* ignore */ }
  resolving.value = false
}

async function viewDetail(row: any) {
  detail.value = null; showDetail.value = true
  try {
    const res = await apiClient.get(`/exceptions?exception_id=${row.id}`)
    const items = res.data?.data ?? res.data ?? []
    detail.value = (Array.isArray(items) ? items : (items.items ?? [])).find((e: any) => e.id === row.id) || { ...row }
  } catch { detail.value = { ...row } }
}

onMounted(fetchExceptions)
</script>
