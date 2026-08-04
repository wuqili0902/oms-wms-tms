<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import apiClient from '../../api'

interface Waybill {
  id: string
  tracking_number: string
  order_id: string
  carrier_code: string
  carrier_name: string
  recipient_name: string
  recipient_phone: string
  recipient_address: string
  status: string
  print_count: number
  last_printed_at: string | null
  created_at: string
  updated_at: string | null
}

const router = useRouter()
const loading = ref(false)
const list = ref<Waybill[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filterStatus = ref('')
const filterCarrier = ref('')
const searchQuery = ref('')

const carriers = [
  { value: '', label: '全部承运商' },
  { value: 'sf', label: '顺丰速运' },
  { value: 'zto', label: '中通快递' },
  { value: 'yto', label: '圆通速递' },
  { value: 'sto', label: '申通快递' },
  { value: 'yunda', label: '韵达快递' },
  { value: 'ems', label: 'EMS邮政' },
  { value: 'jd', label: '京东物流' },
]

const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'created', label: '已创建' },
  { value: 'picked_up', label: '已揽收' },
  { value: 'in_transit', label: '运输中' },
  { value: 'out_for_delivery', label: '派送中' },
  { value: 'delivered', label: '已签收' },
  { value: 'voided', label: '已作废' },
]

async function fetchList() {
  loading.value = true
  try {
    const params: Record<string, any> = { page: page.value, page_size: pageSize.value }
    if (filterStatus.value) params.status = filterStatus.value
    if (filterCarrier.value) params.carrier = filterCarrier.value
    if (searchQuery.value) params.q = searchQuery.value

    const res = await apiClient.get('/logistics/waybill/list', { params })
    const d = res.data?.data ?? res.data ?? {}
    list.value = d.items ?? []
    total.value = d.total ?? 0
  } catch (e: any) {
    ElMessage.error('查询面单失败: ' + (e?.response?.data?.detail ?? e.message))
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  fetchList()
}

function handlePageChange(p: number) {
  page.value = p
  fetchList()
}

function handlePrint(tracking: string) {
  router.push({ name: 'WaybillPrint', params: { tracking } })
}

function handleBatchPrint() {
  router.push({ name: 'BatchPrint' })
}

async function handleVoid(tracking: string) {
  try {
    await ElMessageBox.confirm(`确定作废运单 ${tracking} 吗？`, '确认', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await apiClient.post(`/logistics/waybill/${tracking}/void`)
    ElMessage.success('已作废')
    fetchList()
  } catch {
  }
}

onMounted(fetchList)
</script>

<template>
  <div class="waybill-list">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>面单管理</span>
          <el-button type="primary" size="small" @click="handleBatchPrint">批量打单</el-button>
        </div>
      </template>

      <el-form :inline="true" class="filters">
        <el-form-item label="搜索">
          <el-input v-model="searchQuery" placeholder="运单号/订单号/收件人" clearable @keyup.enter="handleSearch" />
        </el-form-item>
        <el-form-item label="承运商">
          <el-select v-model="filterCarrier" @change="handleSearch" style="width:130px">
            <el-option v-for="c in carriers" :key="c.value" :label="c.label" :value="c.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filterStatus" @change="handleSearch" style="width:120px">
            <el-option v-for="s in statusOptions" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSearch">查询</el-button>
          <el-button @click="searchQuery='';filterStatus='';filterCarrier='';handleSearch()">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="list" border v-loading="loading" stripe>
        <el-table-column prop="tracking_number" label="运单号" width="180" />
        <el-table-column prop="order_id" label="订单号" width="140" />
        <el-table-column prop="carrier_name" label="承运商" width="100" />
        <el-table-column prop="recipient_name" label="收件人" width="100" />
        <el-table-column prop="recipient_address" label="地址" min-width="200" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag
              :type="row.status === 'delivered' ? 'success' : row.status === 'voided' ? 'danger' : row.status === 'in_transit' || row.status === 'out_for_delivery' ? 'warning' : 'info'"
              size="small"
            >
              {{ ({ created: '已创建', picked_up: '已揽收', in_transit: '运输中', out_for_delivery: '派送中', delivered: '已签收', voided: '已作废' } as Record<string, string>)[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="print_count" label="打印" width="60" align="center" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="handlePrint(row.tracking_number)">打印</el-button>
            <el-button link type="primary" size="small" @click="router.push({ name: 'WaybillPrint', params: { tracking: row.tracking_number } })">详情</el-button>
            <el-button v-if="row.status !== 'voided'" link type="danger" size="small" @click="handleVoid(row.tracking_number)">作废</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无数据" />
        </template>
      </el-table>

      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :page-sizes="[10, 20, 50]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          @current-change="handlePageChange"
          @size-change="handlePageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.waybill-list { padding: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.filters { margin-bottom: 0; }
.pagination-wrapper { display: flex; justify-content: flex-end; margin-top: 16px; }
</style>
