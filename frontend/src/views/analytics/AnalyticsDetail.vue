<template>
  <div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="数据分析" name="dashboard">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-card>
            <template #header>
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span>订单趋势</span>
                <el-select v-model="days" size="small" style="width:120px" @change="fetchTrends">
                  <el-option label="近7天" :value="7" />
                  <el-option label="近30天" :value="30" />
                  <el-option label="近90天" :value="90" />
                </el-select>
              </div>
            </template>
              <el-table :data="trends" stripe v-loading="trendLoading" max-height="400">
                <template #empty><el-empty description="暂无数据" /></template>
                <el-table-column prop="date" label="日期" width="120" />
                <el-table-column prop="count" label="订单数" />
              </el-table>
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card>
              <template #header>状态分布</template>
              <el-table :data="distribution" stripe v-loading="distLoading">
                <template #empty><el-empty description="暂无数据" /></template>
                <el-table-column label="状态" width="120">
                  <template #default="{ row }">
                    <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="count" label="数量" />
              </el-table>
            </el-card>
          </el-col>
        </el-row>

        <el-card style="margin-top:16px">
          <template #header>低库存预警</template>
          <el-table :data="lowStock" stripe v-loading="lowLoading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column prop="sku" label="SKU" width="150" />
            <el-table-column prop="warehouse" label="仓库" width="180" />
            <el-table-column prop="quantity" label="当前库存" width="100" />
            <el-table-column prop="min_qty" label="最低库存" width="100" />
            <el-table-column label="状态" width="100">
              <template #default>
                <el-tag type="danger" size="small">低于安全库存</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="运量预测" name="forecast">
        <el-card>
          <el-form :model="fcForm" inline>
            <el-form-item label="路线KEY">
              <el-input v-model="fcForm.key" placeholder="如: SH-BJ" style="width:180px" />
            </el-form-item>
            <el-form-item label="天数">
              <el-select v-model="fcForm.days" style="width:100px">
                <el-option label="7天" :value="7" />
                <el-option label="30天" :value="30" />
                <el-option label="90天" :value="90" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="fcLoading" @click="fetchForecast">查询预测</el-button>
              <el-button :loading="fcTraining" @click="trainForecast">训练模型</el-button>
            </el-form-item>
          </el-form>

          <el-table :data="forecast" stripe v-loading="fcLoading">
            <template #empty><el-empty description="暂无预测数据，请先训练模型" /></template>
            <el-table-column label="日期" prop="date" width="120" />
            <el-table-column label="预测订单量" width="120">
              <template #default="{ row }">{{ Number(row.count || 0).toFixed(1) }}</template>
            </el-table-column>
            <el-table-column prop="key" label="路线" width="120" />
          </el-table>
        </el-card>

        <el-card style="margin-top:16px">
          <template #header>记录观测值</template>
          <el-form :model="obsForm" inline>
            <el-form-item label="路线KEY">
              <el-input v-model="obsForm.key" placeholder="如: SH-BJ" style="width:180px" />
            </el-form-item>
            <el-form-item label="订单量">
              <el-input-number v-model="obsForm.count" :min="0" style="width:120px" />
            </el-form-item>
            <el-form-item label="日期">
              <el-date-picker v-model="obsForm.date" type="date" value-format="YYYY-MM-DD" style="width:140px" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="obsLoading" @click="recordObservation">记录</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

const activeTab = ref('dashboard')

const trendLoading = ref(false); const distLoading = ref(false); const lowLoading = ref(false)
const trends = ref<any[]>([]); const distribution = ref<any[]>([]); const lowStock = ref<any[]>([])
const days = ref(30)

const fcForm = reactive({ key: '', days: 7 })
const fcLoading = ref(false)
const fcTraining = ref(false)
const forecast = ref<any[]>([])

const obsForm = reactive({ key: '', count: 0, date: '' })
const obsLoading = ref(false)

function statusType(s: string) {
  const map: Record<string, string> = { draft: 'info', confirmed: 'primary', processing: 'warning', picking: 'warning', completed: 'success', cancelled: 'danger', failed: 'danger' }
  return map[s] || 'info'
}

async function fetchTrends() {
  trendLoading.value = true
  try { const res = await apiClient.get(`/analytics/order-trends?days=${days.value}`); const d = res.data?.data ?? res.data; trends.value = d?.trends ?? [] } catch { /* ignore */ }
  trendLoading.value = false
}

async function fetchForecast() {
  fcLoading.value = true
  forecast.value = []
  try {
    const res = await apiClient.get(`/forecast?key=${fcForm.key}&days=${fcForm.days}`)
    forecast.value = res.data?.data ?? res.data ?? []
  } catch { /* ignore */ }
  fcLoading.value = false
}

async function trainForecast() {
  fcTraining.value = true
  try {
    const res = await apiClient.post('/forecast/training', { months: 6 })
    const msg = (res.data?.data ?? res.data)?.message || '模型训练完成'
    ElMessage.success(msg)
  } catch { /* ignore */ }
  fcTraining.value = false
}

async function recordObservation() {
  obsLoading.value = true
  try {
    await apiClient.post('/forecast/observations', obsForm)
    ElMessage.success('观测值已记录')
    obsForm.count = 0
    obsForm.date = ''
  } catch { /* ignore */ }
  obsLoading.value = false
}

onMounted(async () => {
  await fetchTrends()
  distLoading.value = true
  try { const res = await apiClient.get('/analytics/status-distribution'); const d = res.data?.data ?? res.data ?? []; distribution.value = Array.isArray(d) ? d : [] } catch { /* ignore */ }
  distLoading.value = false

  lowLoading.value = true
  try { const res = await apiClient.get('/analytics/low-stock'); const d = res.data?.data ?? res.data; lowStock.value = d?.items ?? [] } catch { /* ignore */ }
  lowLoading.value = false
})
</script>
