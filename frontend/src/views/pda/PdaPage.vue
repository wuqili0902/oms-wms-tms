<template>
  <div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="库存变动" name="mutation">
        <el-card>
          <template #header>记录库存变动</template>
          <el-form :model="mutationForm" label-width="100px" style="max-width:500px" @keyup.enter="submitMutation">
            <el-form-item label="设备ID">
              <el-input v-model="mutationForm.device_id" placeholder="扫描器/PDA 编号" />
            </el-form-item>
            <el-form-item label="实体类型">
              <el-select v-model="mutationForm.entity_type" style="width:100%">
                <el-option label="库存" value="inventory" />
                <el-option label="库位" value="location" />
                <el-option label="订单" value="order" />
                <el-option label="设备" value="device" />
              </el-select>
            </el-form-item>
            <el-form-item label="实体ID">
              <el-input v-model="mutationForm.entity_id" placeholder="扫描条码 / 输入UUID" />
            </el-form-item>
            <el-form-item label="操作">
              <el-select v-model="mutationForm.operation" style="width:100%">
                <el-option label="新增 (CREATE)" value="create" />
                <el-option label="更新 (UPDATE)" value="update" />
                <el-option label="删除 (DELETE)" value="delete" />
              </el-select>
            </el-form-item>
            <el-form-item label="数量">
              <el-input-number v-model="mutationForm.qty" :min="0" style="width:100%" />
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="mutationForm.remark" type="textarea" :rows="2" placeholder="可选备注" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="mutLoading" @click="submitMutation">提交变动</el-button>
              <el-button @click="clearMutation">清空</el-button>
            </el-form-item>
          </el-form>
          <el-alert v-if="mutResult" type="success" :title="`变动已入队列，ID: ${mutResult.id}`" show-icon closable style="margin-top:12px" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="同步队列" name="sync">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>待同步变动</span>
              <el-button type="primary" :loading="syncLoading" @click="triggerSync">触发同步</el-button>
            </div>
          </template>
          <el-alert v-if="syncResult" :title="`同步完成：${syncResult.accepted} 成功，${syncResult.failed} 失败`" :type="syncResult.failed > 0 ? 'warning' : 'success'" show-icon closable style="margin-bottom:12px" />
          <el-table :data="mutations" stripe v-loading="listLoading">
            <template #empty><el-empty description="暂无待同步数据" /></template>
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="device_id" label="设备" width="100" />
            <el-table-column prop="entity_type" label="类型" width="80" />
            <el-table-column prop="entity_id" label="实体ID" width="200" />
            <el-table-column prop="operation" label="操作" width="80" />
            <el-table-column prop="created_at" label="创建时间" width="175" />
            <el-table-column label="同步状态" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.synced_at" type="success" size="small">已同步</el-tag>
                <el-tag v-else type="warning" size="small">待同步</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

const activeTab = ref('mutation')

const mutationForm = reactive({
  device_id: '', entity_type: 'inventory', entity_id: '',
  operation: 'update', qty: 0, remark: '',
})
const mutLoading = ref(false)
const mutResult = ref<{ id: number } | null>(null)

const syncLoading = ref(false)
const syncResult = ref<{ accepted: number; failed: number } | null>(null)

const listLoading = ref(false)
const mutations = ref<any[]>([])

function clearMutation() {
  mutationForm.entity_id = ''
  mutationForm.qty = 0
  mutationForm.remark = ''
  mutResult.value = null
}

async function submitMutation() {
  mutLoading.value = true
  mutResult.value = null
  try {
    const payload: Record<string, any> = { ...mutationForm }
    payload.payload = { quantity: mutationForm.qty, remark: mutationForm.remark }
    delete payload.qty
    delete payload.remark
    const res = await apiClient.post('/pda/mutations', payload)
    mutResult.value = res.data ?? null
    ElMessage.success('变动已入队列')
  } catch { /* ignore */ }
  mutLoading.value = false
}

async function triggerSync() {
  syncLoading.value = true
  syncResult.value = null
  try {
    const res = await apiClient.post('/pda/sync')
    syncResult.value = res.data ?? null
    if (syncResult.value && syncResult.value.failed === 0) {
      ElMessage.success(`同步完成，${syncResult.value.accepted} 条处理成功`)
    }
    fetchMutations()
  } catch { /* ignore */ }
  syncLoading.value = false
}

async function fetchMutations() {
  listLoading.value = true
  try {
    const res = await apiClient.get('/pda/mutations')
    const d = res.data?.data ?? res.data ?? []
    mutations.value = Array.isArray(d) ? d : []
  } catch { mutations.value = [] }
  listLoading.value = false
}

onMounted(() => {
  if (activeTab.value === 'sync') fetchMutations()
})
</script>
