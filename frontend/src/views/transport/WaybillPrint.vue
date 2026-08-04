<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import apiClient from '../../api'

const props = defineProps<{ params: { tracking: string } }>()
const router = useRouter()

const tracking = ref(props.params.tracking)
const waybill = ref<any>(null)
const loading = ref(false)
const printing = ref(false)

async function fetchWaybill() {
  loading.value = true
  try {
    const res = await apiClient.get(`/logistics/waybill/${tracking.value}`)
    waybill.value = res.data?.data ?? res.data
  } catch (e: any) {
    ElMessage.error('查询面单失败: ' + (e?.response?.data?.detail ?? e.message))
  } finally {
    loading.value = false
  }
}

async function handlePrint() {
  printing.value = true
  try {
    const res = await apiClient.post(`/logistics/waybill/${tracking.value}/print`)
    const url = res.data?.print_callback_url ?? ''
    if (url) {
      window.open(url, '_blank')
    }
    ElMessage.success('已提交打印')
    setTimeout(() => window.print(), 500)
  } catch (e: any) {
    ElMessage.error('打印失败: ' + (e?.response?.data?.detail ?? e.message))
  } finally {
    printing.value = false
  }
}

function statusText(s: string) {
  const m: Record<string, string> = {
    created: '已创建', picked_up: '已揽收', in_transit: '运输中',
    out_for_delivery: '派送中', delivered: '已签收', voided: '已作废',
  }
  return m[s] || s
}

onMounted(fetchWaybill)
</script>

<template>
  <div class="waybill-print-page">
    <div class="toolbar" v-if="waybill">
      <el-button type="primary" :loading="printing" @click="handlePrint">
        {{ printing ? '打印中...' : '打印电子面单' }}
      </el-button>
      <el-button @click="router.back()">返回</el-button>
    </div>

    <div v-loading="loading" class="label-preview" v-if="waybill">
      <div class="label-wrapper" id="print-area">
        <div class="label-header">
          <div class="label-title">{{ waybill.carrier_name }} 电子面单</div>
          <div class="label-barcode">{{ waybill.tracking_number }}</div>
        </div>

        <div class="label-body">
          <div class="label-row">
            <span class="label-key">运单号</span>
            <span class="label-val mono">{{ waybill.tracking_number }}</span>
          </div>
          <div class="label-row">
            <span class="label-key">订单号</span>
            <span class="label-val">{{ waybill.order_id }}</span>
          </div>
          <div class="label-divider"></div>

          <div class="label-row">
            <span class="label-key">收件人</span>
            <span class="label-val">{{ waybill.recipient_name }}</span>
          </div>
          <div class="label-row">
            <span class="label-key">电话</span>
            <span class="label-val">{{ waybill.recipient_phone }}</span>
          </div>
          <div class="label-row">
            <span class="label-key">地址</span>
            <span class="label-val">{{ waybill.recipient_address }}</span>
          </div>
          <div class="label-divider"></div>

          <div class="label-row">
            <span class="label-key">承运商</span>
            <span class="label-val">{{ waybill.carrier_name }}</span>
          </div>
          <div class="label-row">
            <span class="label-key">状态</span>
            <span class="label-val">{{ statusText(waybill.status) }}</span>
          </div>
          <div class="label-row" v-if="waybill.items?.length">
            <span class="label-key">物品</span>
            <span class="label-val">{{ waybill.items.map((i: any) => `${i.sku || i.name || ''} x${i.qty || 1}`).join(', ') }}</span>
          </div>
        </div>

        <div class="label-footer">
          <div class="print-time">{{ new Date().toLocaleString('zh-CN') }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.waybill-print-page { padding: 16px; }

.toolbar { display: flex; gap: 8px; margin-bottom: 16px; }

.label-preview {
  display: flex;
  justify-content: center;
}

.label-wrapper {
  width: 320px;
  border: 2px dashed #ccc;
  border-radius: 8px;
  padding: 20px;
  background: #fff;
  font-family: 'Microsoft YaHei', sans-serif;
}

.label-header {
  text-align: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 2px solid #333;

  .label-title {
    font-size: 18px;
    font-weight: bold;
    margin-bottom: 4px;
  }

  .label-barcode {
    font-family: 'Courier New', monospace;
    font-size: 14px;
    letter-spacing: 2px;
    color: #333;
  }
}

.label-body {
  .label-row {
    display: flex;
    margin-bottom: 6px;
    line-height: 1.6;
  }

  .label-key {
    width: 60px;
    color: #999;
    font-size: 12px;
    flex-shrink: 0;
  }

  .label-val {
    flex: 1;
    font-size: 13px;
    color: #333;
    word-break: break-all;
  }

  .label-divider {
    border-top: 1px dotted #ddd;
    margin: 8px 0;
  }
}

.label-footer {
  margin-top: 16px;
  padding-top: 8px;
  border-top: 1px solid #eee;
  text-align: center;

  .print-time {
    font-size: 11px;
    color: #999;
  }
}

@media print {
  .toolbar { display: none !important; }
  .waybill-print-page { padding: 0 !important; }
  .label-preview { display: block !important; }
  .label-wrapper {
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    width: 100% !important;
  }
}
</style>
