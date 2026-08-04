<!-- AmazonConfig.vue — AWS Access Key / Secret 配置 -->
<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import apiClient from '../../api'
import { ElMessage } from 'element-plus'

const props = defineProps<{ params: { connectorId: string } }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const saving = ref(false)
const form = reactive({
  access_key_id: '',
  secret_access_key: '',
  marketplace_ids: '', // CSV: US,CA,MX,...
})

async function fetchConfig() {
  try {
    const res = await apiClient.get(`/connectors/amazon/config/${props.params.connectorId}`)
    const d = res.data?.data ?? res.data ?? {}
    form.access_key_id = d.access_key_id || ''
    form.secret_access_key = d.secret_access_key || ''
    form.marketplace_ids = d.marketplace_ids || ''
  } catch (e: any) {
    console.warn('[AmazonConfig] fetch failed:', e?.response?.data ?? e)
  }
}

async function save() {
  saving.value = true
  try {
    await apiClient.post(`/connectors/amazon/config/${props.params.connectorId}`, form)
    ElMessage.success('配置已保存')
    emit('close')
  } catch (e: any) {
    console.error('[AmazonConfig] save failed:', e?.response?.data ?? e)
    ElMessage.error(e?.response?.data?.detail ?? '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(fetchConfig)
</script>

<template>
  <div class="amazon-config">
    <el-card>
      <template #header>
        <span>AWS Access Key / Secret 配置</span>
      </template>

      <el-form :model="form" label-width="160px">
        <el-form-item label="Access Key ID">
          <el-input v-model.trim="form.access_key_id" placeholder="AKIA..." />
        </el-form-item>
        <el-form-item label="Secret Access Key">
          <el-input v-model.trim="form.secret_access_key" type="password" show-password />
        </el-form-item>
        <el-form-item label="Marketplaces (CSV)">
          <el-input
            v-model.trim="form.marketplace_ids"
            placeholder="US,CA,MX,UK,DE,FR,IT,ES,JP,CN,AU"
            :rows="3"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="$router.back()">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.amazon-config { padding:16px; }
</style>
