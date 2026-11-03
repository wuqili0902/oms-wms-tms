<!-- ShopifyConfig.vue — Shopify Webhook 配置说明（只读）

     旧版要求填 **店铺 URL + Admin API Token（shpat_…）**，并 `PUT` 到
     `/connectors/{id}/config`——该端点不存在。本系统不拉取 Shopify：订单是
     Shopify 通过 Webhook 推过来的，用 HMAC-SHA256 验签，验签用的密钥就是应用
     自己的 `SECRET_KEY`。也就是说这个页面收集的 Admin Token 没有任何代码使用它，
     而一个把长期有效的店铺令牌收进浏览器、再 `PUT` 到一个不存在端点的表单，
     只是把密钥写进浏览器历史和请求日志而已。

     现在这一页说明"在哪里配置"：Shopify 后台注册 Webhook + 服务器 .env 里的
     `SECRET_KEY`，并通过 `GET /connectors/shopify` 只读显示当前是否已配置。 -->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import apiClient from '../../api'
import { errText } from '../../api/errors'

const route = useRoute()
const connectorId = computed(() => (route.params.connectorId as string) || 'shopify')

const loading = ref(false)
const credentials = ref<{ env: string; set?: boolean | null; value?: string | null }[]>([])
const capabilities = ref<Record<string, string>>({})
const note = ref('')
const configured = ref(false)

const webhookUrl = `${window.location.origin}/api/v1/connectors/shopify/webhook`

async function fetchConfig() {
  loading.value = true
  try {
    const res = await apiClient.get(`/connectors/${connectorId.value}`)
    const d = res.data?.data ?? res.data ?? {}
    credentials.value = d.credentials ?? []
    capabilities.value = d.capabilities ?? {}
    note.value = d.note ?? ''
    configured.value = Boolean(d.configured)
  } catch (e: any) {
    ElMessage.error(errText(e, '读取连接器状态失败'))
  } finally {
    loading.value = false
  }
}

const stateLabel = (s: string) =>
  ({ implemented: '已实现', not_implemented: '未实现', not_available: '不适用' } as Record<string, string>)[s] ?? s
const stateTag = (s: string) =>
  ({ implemented: 'success', not_implemented: 'warning', not_available: 'info' } as Record<string, 'success' | 'warning' | 'info'>)[s] ?? 'info'

onMounted(fetchConfig)
</script>

<template>
  <div class="shopify-config">
    <el-card v-loading="loading">
      <template #header>
        <span>Shopify 配置说明 — {{ connectorId }}</span>
      </template>

      <el-alert type="warning" :closable="false" show-icon
                title="Shopify 是推送式对接：在 Shopify 后台注册 Webhook，不需要 Admin API Token"
                description="订单由 Shopify 主动推送到下面的地址，请求头里的 X-Shopify-Hmac-Sha256 用应用自己的 SECRET_KEY 验签。本系统不调用 Shopify Admin API，因此不收集、也不使用任何 shpat_ 令牌。" />

      <el-descriptions :column="1" border style="margin-top:12px">
        <el-descriptions-item label="Webhook 地址">
          <span style="font-family:monospace">{{ webhookUrl }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="订阅主题">
          orders/create、orders/fulfilled（其他主题会被跳过，返回 status: skipped）
        </el-descriptions-item>
        <el-descriptions-item label="验签请求头">
          X-Shopify-Hmac-Sha256（HMAC-SHA256，密钥 = SECRET_KEY；签名不符返回 401）
        </el-descriptions-item>
        <el-descriptions-item label="SECRET_KEY">
          <el-tag :type="configured ? 'success' : 'danger'" size="small">
            {{ configured ? '已配置' : '未配置' }}
          </el-tag>
          <span style="font-size:12px;color:#909399;margin-left:8px">
            写在服务器 .env / 环境变量里，长度至少 32 字符；本页不显示它的值。
          </span>
        </el-descriptions-item>
      </el-descriptions>

      <el-table :data="credentials" style="margin-top:12px">
        <el-table-column prop="env" label="配置项" width="240" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.set ? 'success' : 'warning'" size="small">
              {{ row.set ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="说明">
          <template #default>
            <span style="font-size:12px;color:#909399">只回报是否已配置，不回报密钥值</span>
          </template>
        </el-table-column>
      </el-table>

      <div style="margin-top:12px">
        <el-tag v-for="(state, action) in capabilities" :key="action" :type="stateTag(state)"
                size="small" style="margin:2px 6px 2px 0">
          {{ action }}: {{ stateLabel(state) }}
        </el-tag>
      </div>

      <p v-if="note" style="font-size:12px;color:#909399;margin-top:10px">{{ note }}</p>

      <template #footer>
        <el-button @click="$router.back()">返回</el-button>
      </template>
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.shopify-config { padding:16px; }
</style>
