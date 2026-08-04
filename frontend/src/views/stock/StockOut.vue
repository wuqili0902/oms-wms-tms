<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>出库管理</span>
          <el-button type="primary" @click="showCreate = true">新建出库单</el-button>
        </div>
      </template>
      <el-table :data="records" stripe v-loading="loading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column prop="id" label="ID" width="200" />
        <el-table-column prop="warehouse_name" label="仓库" width="140" />
        <el-table-column prop="type" label="类型" width="100" />
        <el-table-column prop="ref_no" label="参考号" width="140" />
        <el-table-column prop="total_qty" label="总数量" width="90" />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }"><el-tag :type="row.status === 'SHIPPED' ? 'success' : 'warning'" size="small">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="175" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="showDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="display:flex;justify-content:flex-end;margin-top:12px">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="fetchRecords" @size-change="fetchRecords" />
      </div>
    </el-card>

    <el-dialog v-model="showCreate" title="新建出库单" width="600px" destroy-on-close @closed="resetForm">
      <el-form :model="form" label-width="100px">
        <el-form-item label="仓库">
          <el-select v-model="form.warehouse_id" filterable placeholder="选择仓库" style="width:100%">
            <el-option v-for="wh in warehouses" :key="wh.id" :label="wh.name" :value="wh.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width:100%">
            <el-option label="销售出库" value="SALE" />
            <el-option label="调拨出库" value="TRANSFER" />
            <el-option label="手动出库" value="MANUAL" />
          </el-select>
        </el-form-item>
        <el-form-item label="参考号">
          <el-input v-model.trim="form.ref_no" placeholder="订单号/调拨单号" />
        </el-form-item>
        <el-form-item label="商品明细">
          <div v-for="(line, idx) in form.lines" :key="idx" style="display:flex;gap:8px;margin-bottom:8px">
            <el-input v-model="line.sku" placeholder="SKU" style="width:200px" />
            <el-input-number v-model="line.qty" :min="1" style="width:120px" />
            <el-button type="danger" size="small" @click="form.lines.splice(idx, 1)">删除</el-button>
          </div>
          <el-button type="primary" text @click="form.lines.push({ sku: '', qty: 1 })">+ 添加商品</el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showDetailDialog" title="出库单详情" width="700px" destroy-on-close>
      <el-descriptions border column="1" v-if="detail">
        <el-descriptions-item label="ID">{{ detail.id }}</el-descriptions-item>
        <el-descriptions-item label="仓库">{{ detail.warehouse_name }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ detail.type }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ detail.status }}</el-descriptions-item>
        <el-descriptions-item label="总数量">{{ detail.total_qty }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ detail.created_at }}</el-descriptions-item>
      </el-descriptions>
      <el-table :data="detail?.lines ?? []" stripe style="margin-top:16px">
        <el-table-column prop="sku" label="SKU" />
        <el-table-column prop="qty_shipped" label="数量" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'
import { usePagination } from '../../composables/usePagination'

const loading = ref(false)
const saving = ref(false)
const records = ref<any[]>([])
const warehouses = ref<any[]>([])
const showCreate = ref(false)
const showDetailDialog = ref(false)
const detail = ref<any>(null)
const { page, pageSize, total } = usePagination()

const form = reactive({
  warehouse_id: '',
  type: 'MANUAL',
  ref_no: '',
  lines: [] as Array<{ sku: string; qty: number }>,
})

function resetForm() {
  form.warehouse_id = ''
  form.type = 'MANUAL'
  form.ref_no = ''
  form.lines = []
}

async function fetchRecords() {
  loading.value = true
  try {
    const res = await apiClient.get(`/stock-out?page=${page.value}&page_size=${pageSize.value}`)
    const d = res.data?.data ?? res.data ?? []
    records.value = Array.isArray(d) ? d : d.items ?? []
    if (!Array.isArray(d) && d.total) total.value = d.total
    else total.value = records.value.length
  } catch (e: any) {
    ElMessage.error('获取出库记录失败: ' + (e?.response?.data?.detail ?? e.message))
    records.value = []
  } finally { loading.value = false }
}

async function fetchWarehouses() {
  try {
    const res = await apiClient.get('/warehouses')
    const d = res.data?.data ?? res.data
    warehouses.value = Array.isArray(d) ? d : d?.items ?? []
  } catch (e: any) { ElMessage.error('获取仓库列表失败: ' + (e?.response?.data?.detail ?? e.message)) }
}

async function submit() {
  if (!form.warehouse_id || !form.lines.length) {
    ElMessage.warning('请选择仓库并添加商品')
    return
  }
  saving.value = true
  try {
    await apiClient.post('/stock-out', { data: { warehouse_id: form.warehouse_id, type: form.type, ref_no: form.ref_no, lines: form.lines } })
    ElMessage.success('出库单已创建')
    showCreate.value = false
    fetchRecords()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? '创建失败')
  } finally { saving.value = false }
}

async function showDetail(row: any) {
  try {
    const res = await apiClient.get(`/stock-out/${row.id}`)
    detail.value = res.data?.data ?? res.data
    showDetailDialog.value = true
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? '获取详情失败')
  }
}

onMounted(() => { fetchRecords(); fetchWarehouses() })
</script>
