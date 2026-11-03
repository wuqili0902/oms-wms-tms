<!-- AmazonConfig.vue — Amazon SP-API 配置说明（只读）

     旧版是一个表单，要求填 **AWS Access Key / Secret**，并提交到
     `POST /connectors/amazon/config/{id}`（该端点不存在）。SP-API 用的是
     LWA 的 client id / client secret + refresh token，不是 AWS IAM 密钥；
     也就是说这个页面收集的密钥本系统根本用不上，而密钥一旦进入浏览器和请求体，
     就进了浏览器历史、代理日志和任何记录请求体的地方。

     现在这里只说明"凭据写在哪儿"：服务器配置（.env / 环境变量），
     页面上通过 `GET /connectors/amazon` 只读地显示每项凭据**是否已配置**——
     接口不会把密钥值传回浏览器。 -->
<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import apiClient from '../../api'
import { errText } from '../../api/errors'

// The id comes from the route, not from props: this route does not pass props
// (`props` is not enabled on it), so reading ``props.params.connectorId`` throws
// on mount and the page would show nothing but an error toast.
const route = useRoute()
const connectorId = computed(() => (route.params.connectorId as string) || 'amazon')

const loading = ref(false)
const credentials = ref<{ env: string; set?: boolean | null; value?: string | null }[]>([])
const capabilities = ref<Record<string, string>>({})
const note = ref('')

async function fetchConfig() {
  loading.value = true
  try {
    const res = await apiClient.get(`/connectors/${connectorId.value}`)
    const d = res.data?.data ?? res.data ?? {}
    credentials.value = d.credentials ?? []
    capabilities.value = d.capabilities ?? {}
    note.value = d.note ?? ''
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
  <div class="amazon-config">
    <el-card v-loading="loading">
      <template #header>
        <span>Amazon SP-API 配置说明 — {{ connectorId }}</span>
      </template>

      <el-alert type="warning" :closable="false" show-icon
                title="凭据写在服务器配置里，不在网页填写"
                description="SP-API 使用 LWA 的 Client ID / Client Secret / Refresh Token（不是 AWS Access Key）。请写入服务器的 .env 或环境变量后重启服务；本页面不接收也不显示密钥值。" />

      <el-table :data="credentials" style="margin-top:12px">
        <el-table-column prop="env" label="配置项" width="280" />
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.env === 'AMAZON_SP_API_REGION'" size="small">{{ row.value }}</el-tag>
            <el-tag v-else :type="row.set ? 'success' : 'warning'" size="small">
              {{ row.set ? '已配置' : '未配置' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="说明">
          <template #default="{ row }">
            <span style="font-size:12px;color:#909399">
              {{ row.env === 'AMAZON_SP_API_REGION' ? '卖家站点区域（us / eu / fe 等）' : '只回报是否已配置，不回报密钥值' }}
            </span>
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
.amazon-config { padding:16px; }
</style>
