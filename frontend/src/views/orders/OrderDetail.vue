<template>
  <div>
    <el-button text style="margin-bottom:12px" @click="$router.push('/orders')">
      <el-icon><ArrowLeft /></el-icon> 返回订单列表
    </el-button>

    <el-card v-loading="loading">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>订单详情：{{ order?.order_no }}</span>
          <div>
            <el-button size="small" @click="printPage">打印</el-button>
            <el-tag :type="statusType(order?.status||'')" size="large">{{ statusLabel(order?.status||'') }}</el-tag>
          </div>
        </div>
      </template>

      <el-descriptions :column="3" border>
        <el-descriptions-item label="订单号">{{ order?.order_no }}</el-descriptions-item>
        <el-descriptions-item label="客户ID">{{ order?.customer_id }}</el-descriptions-item>
        <el-descriptions-item label="优先级">
          <el-tag :type="priorityType(order?.priority||'')" size="small">{{ order?.priority }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="总金额">¥{{ Number(order?.total_amount||0).toFixed(2) }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ order?.created_at }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ order?.updated_at }}</el-descriptions-item>
        <el-descriptions-item label="备注" :span="3">{{ order?.notes || '无' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card style="margin-top:16px" v-loading="loading">
      <template #header>订单商品</template>
      <el-table :data="order?.items||[]" stripe>
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column label="SKU" prop="sku" width="150" />
        <el-table-column label="GTIN" prop="gtin" width="150" />
        <el-table-column label="名称" prop="product_name" min-width="180" />
        <el-table-column label="数量" prop="quantity" width="80" />
        <el-table-column label="单价" width="120">
          <template #default="{ row }">¥{{ Number(row.unit_price||0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="小计" width="120">
          <template #default="{ row }">¥{{ (Number(row.unit_price||0)*(row.quantity||0)).toFixed(2) }}</template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card style="margin-top:16px">
      <template #header>状态变更历史</template>
      <el-table :data="history" stripe v-loading="historyLoading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column label="从" prop="from_status" width="120">
          <template #default="{ row }">{{ statusLabel(row.from_status) }}</template>
        </el-table-column>
        <el-table-column label="到" prop="to_status" width="120">
          <template #default="{ row }">{{ statusLabel(row.to_status) }}</template>
        </el-table-column>
        <el-table-column label="操作人" prop="operator" width="120" />
        <el-table-column label="备注" prop="remark" min-width="200" />
        <el-table-column label="时间" prop="created_at" width="175" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import apiClient from '../../api'

const route = useRoute()
const order = ref<any>(null)
const loading = ref(false)
const history = ref<any[]>([])
const historyLoading = ref(false)

function printPage() {
  window.print()
}

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

onMounted(async () => {
  const id = route.params.id as string
  if (!id) return
  loading.value = true
  try {
    const res = await apiClient.get(`/orders/${id}`)
    order.value = res.data?.data ?? res.data
  } catch { /* ignore */ }
  loading.value = false

  historyLoading.value = true
  try {
    const res = await apiClient.get(`/orders/${id}/history`)
    history.value = res.data?.data ?? res.data ?? []
  } catch { history.value = [] }
  historyLoading.value = false
})
</script>

<style>
@media print {
  .app-header, .app-aside, .el-button { display: none !important; }
  .app-main { padding: 0 !important; }
  .el-card { box-shadow: none !important; border: 1px solid #ddd !important; }
}
</style>
