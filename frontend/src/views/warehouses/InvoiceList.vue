<template>
  <div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="发票" name="invoices">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>发票列表</span>
              <el-button type="primary" @click="showCreateInvoice = true">新建发票</el-button>
            </div>
          </template>
          <el-table :data="invoices" stripe v-loading="invLoading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="invoice_no" label="发票号" width="180" />
            <el-table-column prop="vendor_name" label="供应商" width="150" />
            <el-table-column prop="total_amount" label="金额" width="130">
              <template #default="{ row }">¥{{ Number(row.total_amount||0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.status === 'paid' ? 'success' : 'warning'" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="175" />
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="viewInvoice(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div style="display:flex;justify-content:flex-end;margin-top:12px">
            <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="onPageChange" @size-change="onSizeChange" />
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="贷项通知单" name="creditMemos">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>贷项通知单</span>
              <el-button type="primary" @click="showCreateMemo = true">新建贷项通知单</el-button>
            </div>
          </template>
          <el-table :data="creditMemos" stripe v-loading="memoLoading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="memo_no" label="通知单号" width="180" />
            <el-table-column prop="reason" label="原因" min-width="200" />
            <el-table-column prop="total_amount" label="金额" width="130">
              <template #default="{ row }">¥{{ Number(row.total_amount||0).toFixed(2) }}</template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="175" />
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="viewMemo(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div style="display:flex;justify-content:flex-end;margin-top:12px">
            <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="onPageChange" @size-change="onSizeChange" />
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="showCreateInvoice" title="新建发票" width="500px" destroy-on-close @closed="resetInvoiceForm">
      <el-form :model="invoiceForm" label-width="100px">
        <el-form-item label="供应商ID">
          <el-input v-model="invoiceForm.vendor_id" />
        </el-form-item>
        <el-form-item label="金额">
          <el-input-number v-model="invoiceForm.total_amount" :min="0" :precision="2" style="width:100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateInvoice = false">取消</el-button>
        <el-button type="primary" :loading="invCreating" @click="submitInvoice">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCreateMemo" title="新建贷项通知单" width="500px" destroy-on-close @closed="resetMemoForm">
      <el-form :model="memoForm" label-width="100px">
        <el-form-item label="发票ID">
          <el-input v-model="memoForm.invoice_id" />
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="memoForm.reason" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="金额">
          <el-input-number v-model="memoForm.total_amount" :min="0" :precision="2" style="width:100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateMemo = false">取消</el-button>
        <el-button type="primary" :loading="memoCreating" @click="submitMemo">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showInvDetail" title="发票详情" width="600px" destroy-on-close>
      <template v-if="invDetail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="发票号">{{ invDetail.invoice_no }}</el-descriptions-item>
          <el-descriptions-item label="供应商">{{ invDetail.vendor_name || invDetail.vendor_id }}</el-descriptions-item>
          <el-descriptions-item label="金额">¥{{ Number(invDetail.total_amount||0).toFixed(2) }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ invDetail.status }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ invDetail.created_at }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>

    <el-dialog v-model="showMemoDetail" title="贷项通知单详情" width="600px" destroy-on-close>
      <template v-if="memoDetail">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="通知单号">{{ memoDetail.memo_no }}</el-descriptions-item>
          <el-descriptions-item label="原因">{{ memoDetail.reason }}</el-descriptions-item>
          <el-descriptions-item label="金额">¥{{ Number(memoDetail.total_amount||0).toFixed(2) }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ memoDetail.created_at }}</el-descriptions-item>
        </el-descriptions>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { usePagination } from '../../composables/usePagination'
import apiClient from '../../api'

const activeTab = ref('invoices')
const invLoading = ref(false)
const memoLoading = ref(false)
const invCreating = ref(false)
const memoCreating = ref(false)
const invoices = ref<any[]>([])
const creditMemos = ref<any[]>([])
const showCreateInvoice = ref(false)
const showCreateMemo = ref(false)
const showInvDetail = ref(false)
const showMemoDetail = ref(false)
const invDetail = ref<any>(null)
const memoDetail = ref<any>(null)
const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()
const invoiceForm = reactive({ vendor_id: '', total_amount: 0 })
const memoForm = reactive({ invoice_id: '', reason: '', total_amount: 0 })

async function fetchInvoices() {
  invLoading.value = true
  try {
    const res = await apiClient.get(`/warehouses/invoices?page=${page.value}&page_size=${pageSize.value}`)
    const d = res.data?.data ?? res.data ?? []
    let items
    if (Array.isArray(d)) { items = d; total.value = d.length }
    else { items = d.items ?? []; total.value = d.total ?? d.items?.length ?? 0 }
    invoices.value = items
  } catch { invoices.value = [] }
  invLoading.value = false
}

async function fetchMemos() {
  memoLoading.value = true
  try {
    const res = await apiClient.get(`/warehouses/credit-memos?page=${page.value}&page_size=${pageSize.value}`)
    const d = res.data?.data ?? res.data ?? []
    let items
    if (Array.isArray(d)) { items = d; total.value = d.length }
    else { items = d.items ?? []; total.value = d.total ?? d.items?.length ?? 0 }
    creditMemos.value = items
  } catch { creditMemos.value = [] }
  memoLoading.value = false
}

function resetInvoiceForm() { invoiceForm.vendor_id = ''; invoiceForm.total_amount = 0 }
function resetMemoForm() { memoForm.invoice_id = ''; memoForm.reason = ''; memoForm.total_amount = 0 }

async function submitInvoice() {
  invCreating.value = true
  try {
    await apiClient.post('/warehouses/invoices', invoiceForm)
    ElMessage.success('发票创建成功')
    showCreateInvoice.value = false
    fetchInvoices()
  } catch { /* ignore */ }
  invCreating.value = false
}

async function submitMemo() {
  memoCreating.value = true
  try {
    await apiClient.post('/warehouses/credit-memos', memoForm)
    ElMessage.success('贷项通知单创建成功')
    showCreateMemo.value = false
    fetchMemos()
  } catch { /* ignore */ }
  memoCreating.value = false
}

async function viewInvoice(row: any) {
  invDetail.value = null; showInvDetail.value = true
  try {
    const res = await apiClient.get(`/warehouses/invoices/${row.id}`)
    invDetail.value = res.data?.data ?? res.data
  } catch { invDetail.value = { ...row } }
}

async function viewMemo(row: any) {
  memoDetail.value = null; showMemoDetail.value = true
  try {
    const res = await apiClient.get(`/warehouses/credit-memos/${row.id}`)
    memoDetail.value = res.data?.data ?? res.data
  } catch { memoDetail.value = { ...row } }
}

onMounted(() => { fetchInvoices(); fetchMemos() })
</script>
