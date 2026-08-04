<template>
  <div class="dashboard">
    <el-row :gutter="16">
      <el-col v-for="card in stats" :key="card.label" :span="6">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-value">{{ card.value }}</div>
          <div class="stat-label">{{ card.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="16">
        <el-card>
          <template #header>最近订单</template>
          <el-table :data="recentOrders" stripe style="width: 100%" v-loading="loading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column prop="order_no" label="订单号" width="180" />
            <el-table-column prop="customer_name" label="客户" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
      <el-table-column prop="total_amount" label="金额" width="120">
          <template #default="{ row }">¥{{ (Number(row.total_amount) || 0).toFixed(2) }}</template>
        </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="180" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header>快捷操作</template>
          <div class="quick-actions">
            <el-button type="primary" style="width:100%;margin-bottom:8px" @click="$router.push('/orders?action=create')">新建订单</el-button>
            <el-button style="width:100%;margin-bottom:8px" @click="$router.push('/warehouses')">仓库管理</el-button>
            <el-button style="width:100%;margin-bottom:8px" @click="$router.push('/transport')">运输管理</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import apiClient from '../api'
import type { Order } from '../api/types'

const loading = ref(false)
const recentOrders = ref<Order[]>([])
const stats = ref([
  { label: '今日订单', value: '0' },
  { label: '待发货', value: '0' },
  { label: '运输中', value: '0' },
  { label: '仓库库存', value: '0' },
])

async function fetchDashboard() {
  loading.value = true
  try {
    const res = await apiClient.get('/analytics/dashboard')
    const d = res.data?.data ?? res.data
    if (d) {
      const s = d.stats ?? {}
      const pendingTotal = (d.status_distribution ?? [])
        .filter((x: any) => x.status === 'confirmed' || x.status === 'processing')
        .reduce((sum: number, x: any) => sum + (x.count ?? 0), 0)
      stats.value = [
        { label: '总订单数', value: String(s.order_count ?? 0) },
        { label: '待处理', value: String(pendingTotal) },
        { label: '用户数', value: String(s.user_count ?? 0) },
        { label: '库存SKU', value: String(s.inventory_count ?? 0) },
      ]
      if (d.recent_orders) recentOrders.value = d.recent_orders as Order[]
    }
  } catch (e: any) {
    console.warn('[dashboard] fetchStats failed:', e?.response?.data ?? e)
  }
  loading.value = false
}

function statusType(s: string) {
  const map: Record<string, string> = { draft: 'info', confirmed: 'primary', processing: 'warning', picking: 'warning', completed: 'success', cancelled: 'danger', failed: 'danger' }
  return map[s] || 'info'
}

onMounted(fetchDashboard)
</script>

<style scoped>
.stat-card { text-align: center; }
.stat-value { font-size: 32px; font-weight: 700; color: #409eff; }
.stat-label { font-size: 14px; color: #909399; margin-top: 4px; }
.quick-actions { display: flex; flex-direction: column; }
</style>
