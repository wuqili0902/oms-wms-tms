<template>
  <div>
    <div style="display:flex;justify-content:flex-end;margin-bottom:8px">
      <!-- The registry screen lists which connectors exist and which actions each
           one actually performs; this page is where the work is done. -->
      <el-button size="small" @click="$router.push('/connectors/manage')">连接器管理</el-button>
    </div>
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card>
          <template #header>
            <div style="display:flex;align-items:center;gap:8px">
              <el-icon><Shop /></el-icon><span>Shopify</span>
            </div>
          </template>
          <p style="font-size:13px;color:#909399;margin-bottom:12px">接收 Shopify 订单推送通知</p>
          <el-alert type="info" :title="'Webhook 端点: POST /api/v1/connectors/shopify/webhook'" show-icon :closable="false" />
          <p style="font-size:12px;color:#909399;margin-top:10px">
            订单由 Shopify 主动推送（需带 HMAC 签名），此页只登记端点，不发起导入。
          </p>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card>
          <template #header>
            <div style="display:flex;align-items:center;gap:8px">
              <el-icon><Connection /></el-icon><span>Amazon SP-API</span>
            </div>
          </template>
          <p style="font-size:13px;color:#909399;margin-bottom:12px">导入 Amazon 订单 / 记录发货交接</p>

          <el-form :model="orderForm" label-width="70px">
            <el-form-item label="订单JSON">
              <el-input v-model="orderForm.json" type="textarea" :rows="6"
                        placeholder="粘贴 SP-API 返回的 Order 对象（含 AmazonOrderId / OrderItems）" />
            </el-form-item>
            <el-form-item>
              <el-button size="small" type="primary" :loading="amzLoading"
                         :disabled="!orderForm.json.trim()" @click="importAmazonOrders">导入订单</el-button>
              <el-button size="small" @click="fillSample">填入示例</el-button>
            </el-form-item>
          </el-form>

          <el-divider style="margin:8px 0 12px" />

          <el-form :model="trackForm" label-width="70px">
            <el-form-item label="亚马逊单号">
              <el-input v-model="trackForm.amazon_order_id" size="small" placeholder="402-3138915-0004487" />
            </el-form-item>
            <el-form-item label="承运商">
              <el-select v-model="trackForm.carrier_code" size="small" clearable filterable
                         allow-create default-first-option placeholder="Amazon 认可的承运商编码" style="width:100%">
                <el-option v-for="c in AMAZON_CARRIERS" :key="c.value" :label="c.label" :value="c.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="运单号">
              <el-input v-model="trackForm.tracking_number" size="small" placeholder="SF1234567890" />
            </el-form-item>
            <el-form-item>
              <el-button size="small" type="primary" :loading="amzTrackLoading"
                         :disabled="!trackReady" @click="syncAmazonTracking">记录发货交接</el-button>
            </el-form-item>
          </el-form>

          <el-alert v-if="amzError" type="error" :title="amzError" show-icon closable style="margin-top:8px" />

          <div v-if="amzResult" style="margin-top:10px;font-size:13px">
            <template v-if="amzResult.kind === 'order'">
              <el-tag type="success" size="small">已导入</el-tag>
              <div style="margin-top:6px;color:#606266">
                订单号 {{ amzResult.order_no }}<span v-if="amzResult.amazon_order_id">（亚马逊 {{ amzResult.amazon_order_id }}）</span><br />
                {{ amzResult.line_count }} 行 · 金额 {{ amzResult.total_amount }}
              </div>
            </template>
            <template v-else>
              <el-tag type="success" size="small">已记录</el-tag>
              <el-tag :type="amzResult.sync_status === 'queued' ? 'success' : 'warning'" size="small" style="margin-left:6px">
                回传亚马逊: {{ syncLabel(amzResult.sync_status) }}
              </el-tag>
              <div style="margin-top:6px;color:#606266">
                {{ amzResult.amazon_order_id }} · {{ carrierLabel(amzResult.carrier_code) }} · {{ amzResult.tracking_number }}
              </div>
            </template>
          </div>

          <!-- Two of the four features this card used to advertise are unimplemented:
               poll_order_status / sync_inventory_to_amazon are stubs, and SP-API
               credentials do not exist in config.  Advertising them as working
               features promised the operator a sync that never happens. -->
          <el-alert type="warning" :closable="false" show-icon style="margin-top:12px"
                    title="订单状态轮询与库存同步尚未接入（需在配置中填入 SP-API 凭据）" />
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card>
          <template #header>
            <div style="display:flex;align-items:center;gap:8px">
              <el-icon><Connection /></el-icon><span>ERP 连接器</span>
            </div>
          </template>
          <p style="font-size:13px;color:#909399;margin-bottom:12px">SAP PI/PO 和 Oracle EDI 集成</p>
          <el-tag type="info">状态: 未启用</el-tag>
          <p style="font-size:12px;color:#909399;margin-top:10px">
            订单接口已就绪：<code>POST /api/v1/orders</code>（逐单录入），无定时同步。
          </p>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Shop, Connection } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'
import { errText } from '../../api/errors'

const amzLoading = ref(false)
const amzTrackLoading = ref(false)
const amzResult = ref<any>(null)
const amzError = ref('')

const orderForm = ref({ json: '' })
const trackForm = ref({ amazon_order_id: '', carrier_code: '', tracking_number: '' })

// Amazon wants its own carrier codes ("SF", "ZTO", "UPS"), which are not the
// internal shipment codes the 发货管理 screen offers.  The list is a shortcut;
// the unlisted ones are typed in.
const AMAZON_CARRIERS = [
  { value: 'SF', label: 'SF 顺丰 (SF)' },
  { value: 'ZTO', label: '中通 (ZTO)' },
  { value: 'YTO', label: '圆通 (YTO)' },
  { value: 'YUNDA', label: '韵达 (YUNDA)' },
  { value: 'JD', label: '京东 (JD)' },
  { value: 'EMS', label: 'EMS' },
  { value: 'UPS', label: 'UPS' },
  { value: 'FEDEX', label: 'FedEx' },
]
const carrierLabel = (code: string) => AMAZON_CARRIERS.find(c => c.value === code)?.label ?? (code || '—')
const syncLabel = (s: string) => ({ queued: '已排队', not_configured: '未配置凭据' } as Record<string, string>)[s] ?? s

const trackReady = computed(() =>
  !!(trackForm.value.amazon_order_id.trim() && trackForm.value.carrier_code.trim() && trackForm.value.tracking_number.trim()))

function fillSample() {
  orderForm.value.json = JSON.stringify({
    AmazonOrderId: '402-3138915-0004487',
    OrderStatus: 'Unshipped',
    BuyerEmail: 'buyer@example.com',
    BuyerName: 'Wei Chen',
    MarketplaceId: 'AAHKV2X7AFYLW',
    OrderTotal: { Amount: '150.00', CurrencyCode: 'CNY' },
    ShippingAddress: { Name: 'Wei Chen', AddressLine1: '1 Nanjing Rd', City: 'Shanghai', PostalCode: '200000', CountryCode: 'CN' },
    OrderItems: [{ SellerSKU: 'SKU-BOLT-100', Title: 'M8 Bolt 100-pack', QuantityOrdered: 2, ItemPrice: { Amount: '75.00' } }],
  }, null, 2)
}

async function importAmazonOrders() {
  amzLoading.value = true
  amzResult.value = null
  amzError.value = ''
  let payload: unknown
  try {
    payload = JSON.parse(orderForm.value.json)
  } catch (e: any) {
    // The server never saw this body; telling the clerk "导入失败，请检查配置"
    // pointed at the API configuration for a clipboard that held prose.
    amzError.value = `订单 JSON 解析失败：${e.message}`
    amzLoading.value = false
    return
  }
  try {
    const res = await apiClient.post('/connectors/amazon/orders', payload)
    const d = res.data?.data ?? res.data
    amzResult.value = { kind: 'order', ...d }
    ElMessage.success(`订单 ${d.order_no} 已导入`)
  } catch (e: any) {
    // A 422 names the key at fault ("OrderItems[1].QuantityOrdered 0 is not an
    // order quantity"); the server's own sentence is what the clerk needs.
    amzError.value = errText(e, '订单导入失败')
    ElMessage.error(amzError.value)
  }
  amzLoading.value = false
}

async function syncAmazonTracking() {
  amzTrackLoading.value = true
  amzResult.value = null
  amzError.value = ''
  try {
    const res = await apiClient.post('/connectors/amazon/tracking', {
      amazon_order_id: trackForm.value.amazon_order_id.trim(),
      carrier_code: trackForm.value.carrier_code.trim(),
      tracking_number: trackForm.value.tracking_number.trim(),
    })
    const d = res.data?.data ?? res.data
    amzResult.value = { kind: 'tracking', ...d }
    // "received" is what we recorded here; the response's own sync_status says
    // how far it got on the Amazon side.
    ElMessage.success(d.sync_status === 'queued' ? '发货交接已记录，等待回传亚马逊' : '发货交接已记录（未配置 SP-API 凭据，未回传亚马逊）')
  } catch (e: any) {
    amzError.value = errText(e, '发货交接记录失败')
    ElMessage.error(amzError.value)
  }
  amzTrackLoading.value = false
}
</script>
