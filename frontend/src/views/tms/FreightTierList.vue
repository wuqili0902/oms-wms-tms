<template>
  <div>
    <el-card style="margin-bottom:16px">
      <template #header><span>运费计算器</span></template>
      <el-form :model="calcForm" inline>
        <el-form-item label="承运商">
          <el-select v-model="calcForm.carrier_code" style="width:140px">
            <el-option label="顺丰" value="sf_express" /><el-option label="中通" value="zto" />
            <el-option label="韵达" value="yunda" /><el-option label="京东物流" value="jd_logistics" /><el-option label="EMS" value="ems" />
          </el-select>
        </el-form-item>
        <el-form-item label="服务类型">
          <el-select v-model="calcForm.service_type" style="width:120px">
            <el-option label="标准" value="standard" /><el-option label="加急" value="express" />
          </el-select>
        </el-form-item>
        <el-form-item label="距离(km)">
          <el-input-number v-model="calcForm.distance_km" :min="1" style="width:120px" />
        </el-form-item>
        <el-form-item label="重量(kg)">
          <el-input-number v-model="calcForm.total_weight_kg" :min="0.1" :precision="1" style="width:120px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="calcLoading" @click="calculateFreight">计算</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="calcResult" type="success" show-icon>
        <template #title>预估运费：¥{{ calcResult.estimated_cost }} | ETA：{{ calcResult.eta_days }}天</template>
      </el-alert>
    </el-card>

    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>运费等级</span>
          <el-button type="primary" size="small" @click="showCreate=true">新建等级</el-button>
        </div>
      </template>
      <el-table :data="tiers" stripe v-loading="tierLoading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column prop="carrier_code" label="承运商" width="120" />
        <el-table-column prop="weight_from" label="重量起(kg)" width="120" />
        <el-table-column prop="weight_to" label="重量止(kg)" width="120" />
        <el-table-column prop="price_per_kg" label="单价/kg" width="120" />
        <el-table-column prop="created_at" label="创建时间" width="175" />
      </el-table>
    </el-card>

    <el-dialog v-model="showCreate" title="新建运费等级" width="500px" destroy-on-close>
      <el-form :model="tierForm" label-width="120px">
        <el-form-item label="承运商">
          <el-select v-model="tierForm.carrier_code" style="width:100%">
            <el-option label="顺丰" value="sf_express" /><el-option label="中通" value="zto" />
            <el-option label="韵达" value="yunda" /><el-option label="京东物流" value="jd_logistics" /><el-option label="EMS" value="ems" />
          </el-select>
        </el-form-item>
        <el-form-item label="重量起(kg)"><el-input-number v-model="tierForm.weight_from" :min="0" style="width:100%" /></el-form-item>
        <el-form-item label="重量止(kg)"><el-input-number v-model="tierForm.weight_to" :min="0" style="width:100%" /></el-form-item>
        <el-form-item label="单价/kg"><el-input-number v-model="tierForm.price_per_kg" :min="0" :precision="2" style="width:100%" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="tierCreating" @click="submitTier">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

const calcLoading = ref(false)
const calcResult = ref<any>(null)
const calcForm = reactive({ carrier_code: 'sf_express', service_type: 'standard', distance_km: 100, total_weight_kg: 10 })
const tierLoading = ref(false)
const tierCreating = ref(false)
const tiers = ref<any[]>([])
const showCreate = ref(false)
const tierForm = reactive({ carrier_code: 'sf_express', weight_from: 0, weight_to: 50, price_per_kg: 5 })

async function calculateFreight() {
  calcLoading.value = true; calcResult.value = null
  try { const res = await apiClient.post('/freight/calculate', calcForm); calcResult.value = res.data?.data ?? res.data } catch { /* ignore */ }
  calcLoading.value = false
}

async function submitTier() {
  tierCreating.value = true
  try {
    await apiClient.post('/freight-tiers', tierForm)
    ElMessage.success('创建成功')
    showCreate.value = false
    const res = await apiClient.get('/freight-tiers?page=1&page_size=50')
    const d = res.data?.data ?? res.data ?? []
    tiers.value = Array.isArray(d) ? d : (d.items ?? [])
  } catch { /* ignore */ }
  tierCreating.value = false
}

onMounted(async () => {
  tierLoading.value = true
  try { const res = await apiClient.get('/freight-tiers?page=1&page_size=50'); const d = res.data?.data ?? res.data ?? []; tiers.value = Array.isArray(d) ? d : (d.items ?? []) } catch { /* ignore */ }
  tierLoading.value = false
})
</script>
