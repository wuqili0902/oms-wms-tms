<template>
  <div>
    <el-button text style="margin-bottom:12px" @click="$router.push('/transport')">
      <el-icon><ArrowLeft /></el-icon> 返回运输列表
    </el-button>

    <el-card v-loading="loading">
      <template #header>
        <span>路线规划</span>
      </template>
      <el-form :model="searchForm" inline @keyup.enter="searchPlan">
        <el-form-item label="路线规划ID">
          <el-input v-model="searchForm.plan_id" placeholder="输入路线规划UUID" style="width:280px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="searchPlan">查询</el-button>
        </el-form-item>
      </el-form>

      <template v-if="plan">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="路线ID">{{ plan.id }}</el-descriptions-item>
          <el-descriptions-item label="运单ID">{{ plan.transport_order_id }}</el-descriptions-item>
          <el-descriptions-item label="出发城市">{{ plan.origin_city }}</el-descriptions-item>
          <el-descriptions-item label="目的城市">{{ plan.destination_city }}</el-descriptions-item>
          <el-descriptions-item label="总距离">{{ plan.total_distance_km }} km</el-descriptions-item>
          <el-descriptions-item label="总费用">¥{{ plan.total_cost_amount }}</el-descriptions-item>
          <el-descriptions-item label="预计时效">{{ plan.estimated_transit_hours }} h</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="plan.status === 'completed' ? 'success' : 'warning'" size="small">{{ plan.status }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <el-steps :active="plan.segments?.length || 0" align-center style="margin:20px 0">
          <el-step v-for="(seg, idx) in plan.segments" :key="idx" :title="seg.origin_hub_code" :description="seg.dest_hub_code" />
        </el-steps>

        <el-table :data="plan.segments||[]" stripe>
          <template #empty><el-empty description="暂无数据" /></template>
          <el-table-column prop="segment_no" label="序号" width="60" />
          <el-table-column prop="origin_hub_code" label="起点" width="140" />
          <el-table-column prop="dest_hub_code" label="终点" width="140" />
          <el-table-column prop="carrier_code" label="承运商" width="120" />
          <el-table-column label="状态" width="140">
            <template #default="{ row }">
              <el-select :model-value="row.status" size="small" @change="(v:string)=>updateSegmentStatus(row, v)" style="width:100px">
                <el-option label="待发" value="pending" />
                <el-option label="运输中" value="in_transit" />
                <el-option label="已完成" value="completed" />
                <el-option label="异常" value="exception" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column prop="tracking_number" label="追踪号" width="160" />
          <el-table-column prop="estimated_departure_time" label="预计出发" width="160" />
          <el-table-column prop="actual_departure_time" label="实际出发" width="160" />
        </el-table>
      </template>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

const loading = ref(false)
const plan = ref<any>(null)
const searchForm = reactive({ plan_id: '' })

async function searchPlan() {
  if (!searchForm.plan_id) return
  loading.value = true; plan.value = null
  try {
    const res = await apiClient.get(`/route-plans/${searchForm.plan_id}`)
    plan.value = res.data?.data ?? res.data
  } catch (e: any) {
    console.warn('[route-plan-detail] searchPlan failed:', e?.response?.data ?? e)
  }
  loading.value = false
}

async function updateSegmentStatus(seg: any, status: string) {
  try {
    await apiClient.patch(`/segments/${seg.id}/status`, { status })
    ElMessage.success(`路段已更新为 ${status}`)
    seg.status = status
  } catch (e: any) {
    console.warn('[route-plan-detail] updateSegmentStatus failed:', e?.response?.data ?? e)
  }
}
</script>
