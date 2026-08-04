<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'
import { useRoute } from 'vue-router'

const route = useRoute()
const connectorId = route.params.connectorId as string

const shopUrl = ref('')
const apiToken = ref('')
const loading = ref(false)
const saving = ref(false)

async function fetchConfig() {
  loading.value = true
  try {
    const res = await apiClient.get(`/connectors/${connectorId}`)
    const d = res.data?.data ?? res.data ?? {}
    if (d.config) {
      shopUrl.value = d.config.shop_url ?? ''
      apiToken.value = d.config.api_token ?? ''
    }
  } catch (e: any) {
    ElMessage.error('获取配置失败: ' + (e?.response?.data?.detail ?? e.message))
  } finally {
    loading.value = false
  }
}

async function saveConfig() {
  if (!shopUrl.value || !apiToken.value) {
    ElMessage.warning('请填写店铺 URL 和 API Token')
    return
  }
  saving.value = true
  try {
    await apiClient.put(`/connectors/${connectorId}/config`, {
      shop_url: shopUrl.value,
      api_token: apiToken.value,
    })
    ElMessage.success('配置保存成功')
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e?.response?.data?.detail ?? e.message))
  } finally {
    saving.value = false
  }
}

onMounted(fetchConfig)
</script>

<template>
  <div class="shopify-config">
    <el-card v-loading="loading">
      <template #header>
        <span>Shopify 店铺配置 — {{ connectorId }}</span>
      </template>

      <el-alert title="请输入您的 Shopify 店铺信息和 API Token" type="info" :closable="false" />

      <el-form label-width="140px" class="config-form">
        <el-form-item label="店铺 URL">
          <el-input v-model="shopUrl" placeholder="https://your-store.myshopify.com" />
        </el-form-item>
        <el-form-item label="Admin API Token">
          <el-input v-model="apiToken" type="password" show-password placeholder="shpat_xxxxxxxxxxxxxxxx" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveConfig">保存配置</el-button>
          <el-button @click="$router.back()">返回</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.shopify-config { padding: 16px; }
.config-form { margin-top: 16px; max-width: 600px; }
</style>
