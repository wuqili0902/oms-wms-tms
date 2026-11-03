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
      <!-- The fields this endpoint answers: total_freight_yuan, the rule that
           priced it, and the bracket that matched.  It quotes no ETA — a rate
           card prices a shipment, a lane carries a transit. -->
      <el-alert v-if="calcResult" type="success" show-icon>
        <template #title>
          预估运费：¥{{ calcResult.total_freight_yuan }}
          <span v-if="calcResult.rule_type"> | 计费规则：{{ ruleLabel(calcResult.rule_type) }}</span>
          <span v-if="calcResult.tier_min_value"> | 区间：{{ calcResult.tier_min_value }} ~ {{ calcResult.tier_max_value ?? '∞' }}</span>
        </template>
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
        <!-- The rate-card record's own fields: min_value / max_value are the
             bracket's bounds (the unit is the rule's measure, not always kg) and
             price_per_unit is the price inside it. -->
        <el-table-column prop="carrier_code" label="承运商" width="120" />
        <el-table-column label="计费规则" width="120">
          <template #default="{ row }">{{ ruleLabel(row.rule_type) }}</template>
        </el-table-column>
        <el-table-column label="区间起" width="110">
          <template #default="{ row }">{{ row.min_value }}</template>
        </el-table-column>
        <el-table-column label="区间止" width="110">
          <template #default="{ row }">{{ row.max_value ?? '不限' }}</template>
        </el-table-column>
        <el-table-column label="单价" width="110">
          <template #default="{ row }">{{ row.price_per_unit }}</template>
        </el-table-column>
        <el-table-column prop="surcharge_express" label="加急附加费" width="110" />
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
        <el-form-item label="计费规则">
          <el-select v-model="tierForm.rule_type" style="width:100%">
            <el-option v-for="r in FREIGHT_RULES" :key="r.value" :label="r.label" :value="r.value" />
          </el-select>
        </el-form-item>
        <el-form-item :label="`区间起(${ruleUnit(tierForm.rule_type)})`">
          <el-input-number v-model="tierForm.min_value" :min="0" :precision="4" style="width:100%" />
        </el-form-item>
        <el-form-item :label="`区间止(${ruleUnit(tierForm.rule_type)})`">
          <el-input-number v-model="tierForm.max_value" :min="0" :precision="4" style="width:100%" />
        </el-form-item>
        <el-form-item :label="`单价(元/${ruleUnit(tierForm.rule_type)})`">
          <el-input-number v-model="tierForm.price_per_unit" :min="0" :precision="4" style="width:100%" />
        </el-form-item>
        <el-form-item label="加急附加费"><el-input-number v-model="tierForm.surcharge_express" :min="0" :precision="2" style="width:100%" /></el-form-item>
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
// The rule decides what the bracket's bounds measure, so the form sends the
// API's own keys (min_value / max_value / price_per_unit) and never says "kg".
const FREIGHT_RULES = [
  { value: 'weight_tiered', label: '按重量分档', unit: 'kg' },
  { value: 'volume_based', label: '按体积计费', unit: 'm³' },
  { value: 'distance_tiered', label: '按距离计费', unit: 'km' },
  { value: 'flat_rate', label: '固定价格', unit: '单' },
]
function ruleLabel(r: string) {
  return FREIGHT_RULES.find((x) => x.value === r)?.label || r || '—'
}
function ruleUnit(r: string) {
  return FREIGHT_RULES.find((x) => x.value === r)?.unit ?? ''
}
const tierForm = reactive({
  carrier_code: 'sf_express',
  rule_type: 'weight_tiered',
  min_value: 0,
  max_value: 50,
  price_per_unit: 5,
  surcharge_express: 0,
})

async function calculateFreight() {
  calcLoading.value = true; calcResult.value = null
  try { const res = await apiClient.post('/freight/calculate', calcForm); calcResult.value = res.data?.data ?? res.data } catch (e: any) { ElMessage.error(e?.userMessage ?? '运费计算失败') }
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
  } catch (e: any) {
    // A refusal is the API's own sentence ("max_value … is below min_value …");
    // the operator has to see it, not read a console line.
    ElMessage.error(e?.userMessage ?? '创建运费等级失败')
  }
  tierCreating.value = false
}

onMounted(async () => {
  tierLoading.value = true
  try { const res = await apiClient.get('/freight-tiers?page=1&page_size=50'); const d = res.data?.data ?? res.data ?? []; tiers.value = Array.isArray(d) ? d : (d.items ?? []) } catch (e: any) { tiers.value = []; ElMessage.error(e?.userMessage ?? '运费等级加载失败') }
  tierLoading.value = false
})
</script>
