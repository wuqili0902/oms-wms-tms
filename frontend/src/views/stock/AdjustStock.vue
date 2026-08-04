<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>库存调整</span>
          <el-button type="primary" @click="showAdjust = true">新建调整</el-button>
        </div>
      </template>
      <el-table :data="logs" stripe v-loading="loading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column prop="id" label="ID" width="200" />
        <el-table-column prop="sku" label="SKU" width="120" />
        <el-table-column prop="type" label="类型" width="130" />
        <el-table-column prop="quantity_change" label="变化量" width="100">
          <template #default="{ row }">
            <span :style="{ color: Number(row.quantity_change) > 0 ? '#67c23a' : '#f56c6c' }">{{ row.quantity_change }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="160" />
        <el-table-column prop="operator" label="操作人" width="100" />
        <el-table-column prop="created_at" label="时间" width="175" />
      </el-table>
      <div style="display:flex;justify-content:flex-end;margin-top:12px">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="fetchLogs" @size-change="fetchLogs" />
      </div>
    </el-card>

    <el-dialog v-model="showAdjust" title="库存调整" width="500px" destroy-on-close @closed="resetForm">
      <el-form :model="form" label-width="100px">
        <el-form-item label="SKU ID">
          <el-input v-model.trim="form.sku_id" placeholder="输入 SKU ID" />
        </el-form-item>
        <el-form-item label="仓库">
          <el-select v-model="form.warehouse_id" filterable placeholder="选择仓库" style="width:100%">
            <el-option v-for="wh in warehouses" :key="wh.id" :label="wh.name" :value="wh.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="变化数量">
          <el-input-number v-model="form.quantity" :min="-99999" :max="99999" style="width:100%" />
          <div style="color:#999;font-size:12px">正数=盘盈，负数=盘亏</div>
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model.trim="form.reason" placeholder="盘点差异/损耗/报废" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAdjust = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">提交</el-button>
      </template>
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
const logs = ref<any[]>([])
const warehouses = ref<any[]>([])
const showAdjust = ref(false)
const { page, pageSize, total } = usePagination()

const form = reactive({
  sku_id: '',
  warehouse_id: '',
  quantity: 0,
  reason: '',
})

function resetForm() {
  form.sku_id = ''
  form.warehouse_id = ''
  form.quantity = 0
  form.reason = ''
}

async function fetchLogs() {
  loading.value = true
  try {
    const res = await apiClient.get(`/inventory-log?page=${page.value}&page_size=${pageSize.value}`)
    const d = res.data?.data ?? res.data ?? []
    logs.value = Array.isArray(d) ? d : d.items ?? []
    if (!Array.isArray(d) && d.total) total.value = d.total
    else total.value = logs.value.length
  } catch (e: any) {
    ElMessage.error('获取调整记录失败: ' + (e?.response?.data?.detail ?? e.message))
    logs.value = []
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
  if (!form.sku_id || !form.warehouse_id || form.quantity === 0) {
    ElMessage.warning('请填写SKU、仓库，且数量不能为0')
    return
  }
  saving.value = true
  try {
    await apiClient.post('/adjust-stock', { data: { sku_id: form.sku_id, warehouse_id: form.warehouse_id, quantity: form.quantity, reason: form.reason } })
    ElMessage.success('调整已提交')
    showAdjust.value = false
    fetchLogs()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? '调整失败')
  } finally { saving.value = false }
}

onMounted(() => { fetchLogs(); fetchWarehouses() })
</script>
