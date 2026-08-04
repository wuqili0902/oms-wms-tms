<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

const carriers = [
  { value: 'sf', label: '顺丰速运' },
  { value: 'zto', label: '中通快递' },
  { value: 'yto', label: '圆通速递' },
  { value: 'sto', label: '申通快递' },
  { value: 'yunda', label: '韵达快递' },
  { value: 'ems', label: 'EMS邮政' },
  { value: 'jd', label: '京东物流' },
]

const originProvince = ref('')
const originCity = ref('')
const destProvince = ref('')
const destCity = ref('')
const weight = ref(0)
const packageType = ref('parcel')
const selectedCarrier = ref('')

interface QuoteResult {
  carrier: string
  carrier_name: string
  estimated_fee: number
  estimated_days: number
  confidence: string
}

const results = ref<QuoteResult[]>([])
const loading = ref(false)
const quoted = ref(false)

async function queryQuote() {
  if (!originProvince.value || !destProvince.value || !weight.value || weight.value <= 0) {
    ElMessage.warning('请填写发货地、目的地和重量')
    return
  }
  loading.value = true
  quoted.value = false
  results.value = []
  try {
    const params: Record<string, any> = {
      origin: `${originProvince.value} ${originCity.value}`,
      destination: `${destProvince.value} ${destCity.value}`,
      weight: weight.value,
      package_type: packageType.value,
    }
    if (selectedCarrier.value) params.carrier = selectedCarrier.value
    const res = await apiClient.get('/logistics/freight/quote', { params })
    const d = res.data?.data ?? res.data ?? []
    results.value = Array.isArray(d) ? d : d.quotes ?? []
    quoted.value = true
    if (!results.value.length) ElMessage.info('未获取到报价')
  } catch (e: any) {
    ElMessage.error('查询报价失败: ' + (e?.response?.data?.detail ?? e.message))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="freight-quote">
    <el-card>
      <template #header><span>运费试算</span></template>

      <el-alert title="输入发货地和目的地信息，获取各承运商预估运费和时效" type="info" :closable="false" />

      <el-form label-width="100px" class="quote-form">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="发货省份">
              <el-input v-model="originProvince" placeholder="如 广东省" />
            </el-form-item>
            <el-form-item label="发货城市">
              <el-input v-model="originCity" placeholder="如 深圳市" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="目的省份">
              <el-input v-model="destProvince" placeholder="如 浙江省" />
            </el-form-item>
            <el-form-item label="目的城市">
              <el-input v-model="destCity" placeholder="如 杭州市" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="16">
          <el-col :span="8">
            <el-form-item label="重量 (kg)">
              <el-input-number v-model="weight" :min="0" :step="0.5" />
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="包裹类型">
              <el-select v-model="packageType">
                <el-option label="普通包裹" value="parcel" />
                <el-option label="文件" value="document" />
                <el-option label="大件" value="bulky" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="8">
            <el-form-item label="承运商">
              <el-select v-model="selectedCarrier" placeholder="全部" clearable>
                <el-option v-for="c in carriers" :key="c.value" :label="c.label" :value="c.value" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item>
          <el-button type="primary" :loading="loading" @click="queryQuote">查询报价</el-button>
        </el-form-item>
      </el-form>

      <div v-if="quoted" class="quote-results">
        <h3>报价结果</h3>
        <el-table :data="results" border v-loading="loading" v-if="results.length">
          <el-table-column prop="carrier_name" label="承运商" width="120" />
          <el-table-column label="预估运费" width="120">
            <template #default="{ row }">¥{{ row.estimated_fee?.toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="预计时效" width="120">
            <template #default="{ row }">{{ row.estimated_days }} 天</template>
          </el-table-column>
          <el-table-column prop="confidence" label="可信度" width="100">
            <template #default="{ row }">
              <el-tag :type="row.confidence === 'high' ? 'success' : row.confidence === 'medium' ? 'warning' : 'info'" size="small">{{ row.confidence }}</el-tag>
            </template>
          </el-table-column>
          <template #empty><el-empty description="暂无数据" /></template>
        </el-table>
        <el-empty v-else description="未获取到报价数据" />
      </div>
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.freight-quote { padding: 16px; }
.quote-form { margin-top: 16px; }
.quote-results { margin-top: 24px;
  h3 { margin-bottom: 12px; font-size: 16px; font-weight: 600; }
}
</style>
