<template>
  <div class="page-container">
    <!-- Desktop: tabs layout -->
    <el-tabs v-if="!isMobile" v-model="activeTab">
      <el-tab-pane label="库存变动" name="mutation">
        <el-card>
          <template #header><span>记录库存变动</span></template>
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

    <!-- Mobile: bottom tabs + card list -->
    <div v-else class="mobile-container">
      <!-- Header with offline indicator -->
      <div class="mobile-header" :class="{ offline: !online }">
        <span>{{ online ? 'PDA 作业' : '⚠️ 已断开，部分功能不可用' }}</span>
        <el-button text @click="$router.push('/dashboard')">退出</el-button>
      </div>

      <!-- Tab content area -->
      <div class="mobile-content" v-if="activeTab === 'mutation'">
        <el-card shadow="never" style="border-radius:0">
          <template #header>
            <span>库存变动</span>
          </template>
          <el-form :model="mutationForm" label-position="top">
            <el-form-item label="设备ID"><el-input v-model="mutationForm.device_id" placeholder="扫描器/PDA 编号" /></el-form-item>
            <el-form-item label="实体类型">
              <el-select v-model="mutationForm.entity_type" style="width:100%">
                <el-option label="库存" value="inventory" />
                <el-option label="库位" value="location" />
                <el-option label="订单" value="order" />
                <el-option label="设备" value="device" />
              </el-select>
            </el-form-item>
            <el-form-item label="实体ID"><el-input v-model="mutationForm.entity_id" placeholder="扫描条码 / 输入UUID" /></el-form-item>
            <el-form-item label="操作">
              <el-radio-group v-model="mutationForm.operation">
                <el-radio value="create">新增</el-radio>
                <el-radio value="update">更新</el-radio>
                <el-radio value="delete">删除</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="数量"><el-input-number v-model="mutationForm.qty" :min="0" style="width:100%" /></el-form-item>
            <el-form-item label="备注"><el-input v-model="mutationForm.remark" type="textarea" placeholder="可选备注" rows="2" /></el-form-item>
          </el-form>
        </el-card>

        <div style="padding:10px">
          <el-button type="primary" @click="submitMutation" :loading="mutLoading" style="width:100%;height:48px;font-size:16px">提交变动</el-button>
        </div>

        <div v-if="mutResult" style="padding:10px"><el-alert :title="'变动已入队列，ID:' + mutResult.id" type="success" show-icon closable /></div>
      </div>

      <div class="mobile-content" v-else-if="activeTab === 'sync'">
        <!-- Sync status card -->
        <el-card shadow="never" style="border-radius:0">
          <template #header><span>同步状态</span></template>
          <el-button type="primary" @click="triggerSync" :loading="syncLoading" icon="Refresh" size="large" style="width:100%;height:48px;font-size:16px">触发同步</el-button>
        </el-card>

        <!-- Mutation list as cards -->
        <div v-if="mutations.length > 0" style="padding:10px">
          <div v-for="m in mutations" :key="m.id" class="mobile-mutation-card">
            <span class="mutation-id">#{{ m.id }} - {{ m.entity_type }}</span>
            <el-tag size="small" :type="m.synced_at ? 'success' : 'warning'">{{ m.synced_at ? '已同步' : '待同步' }}</el-tag>
          </div>
        </div>

        <!-- Empty state -->
        <div v-else style="padding:40px;text-align:center;color:#999">暂无待同步数据</div>
      </div>

      <!-- Bottom navigation bar -->
      <div class="mobile-bottom-bar">
        <el-button :type="activeTab === 'mutation' ? 'primary' : ''" @click="activeTab = 'mutation'" icon="Plus" size="small">库存变动</el-button>
        <el-button :type="activeTab === 'sync' ? 'primary' : ''" @click="activeTab = 'sync'" icon="Upload" size="small">同步队列</el-button>
      </div>
    </div>

    <!-- Desktop: bottom spacer -->
    <div v-if="!isMobile"><el-backtop /></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

const activeTab = ref('mutation')
const isMobile = ref(window.innerWidth < 768)
const online = ref(navigator.onLine)

// Mutation form state
const mutationForm = ref({ device_id: '', entity_type: 'inventory', entity_id: '', operation: 'update', qty: 0, remark: '' })
const mutLoading = ref(false)
const mutResult = ref<{ id: number } | null>(null)

// Sync state
const syncLoading = ref(false)
const mutations = ref<any[]>([])
const listLoading = ref(false)

function clearMutation() { mutationForm.value.entity_id = ''; mutationForm.value.qty = 0; mutationForm.value.remark = '' }

async function submitMutation() {
  mutLoading.value = true
  try {
    const { qty, remark, ...rest } = mutationForm.value
    const payload = { ...rest, payload: { quantity: qty, remark } }
    await apiClient.post('/pda/mutations', payload)
    ElMessage.success('变动已入队列')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '提交失败') }
  mutLoading.value = false
}

async function triggerSync() {
  syncLoading.value = true
  try {
    const res = await apiClient.post('/pda/sync')
    if (res.data?.failed === 0) ElMessage.success(`同步完成，${res.data.accepted} 条处理成功`)
    fetchMutations()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '同步失败') }
  syncLoading.value = false
}

async function fetchMutations() {
  listLoading.value = true
  try {
    const res = await apiClient.get('/pda/mutations')
    mutations.value = Array.isArray(res.data) ? res.data : []
  } catch {}
  listLoading.value = false
}

// Offline detection — show warning banner when disconnected
const handleOnline = () => { online.value = true }
const handleOffline = () => { online.value = false }

function debounce<T extends (...args: any[]) => void>(fn: T, delay = 200) {
  let timer: ReturnType<typeof setTimeout> | null = null
  return (...args: Parameters<T>) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => fn(...args), delay)
  }
}

const handleResize = debounce(() => { isMobile.value = window.innerWidth < 768 })

onMounted(() => {
  if (activeTab.value === 'sync') fetchMutations()
  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)
  window.addEventListener('resize', handleResize)
})
onUnmounted(() => {
  window.removeEventListener('online', handleOnline)
  window.removeEventListener('offline', handleOffline)
  window.removeEventListener('resize', handleResize)
})
</script>

<style scoped>
.page-container { padding: 16px; }

/* Mobile-specific overrides */
@media (max-width: 768px) {
  .mobile-content { flex: 1; overflow-y: auto; }

  /* Bottom navigation bar — PDA style */
  .mobile-bottom-bar {
    position: fixed; bottom: 0; left: 0; right: 0;
    display: flex; gap: 8px; padding: 8px;
    background: #f1f5f9; border-top: 1px solid #e4e7ed; z-index: 100;
  }

  .mobile-mutation-card {
    display: flex; justify-content: space-between; align-items: center;
    padding: 12px 16px; background: white; border-radius: 8px; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }

  .mobile-header {
    display: flex; justify-content: space-between; align-items: center; padding: 12px 16px;
    background: #f1f5f9; font-size: 18px; font-weight: 600;
  }

  .mobile-header.offline {
    background: #fef3c7; color: #d97706;
  }
}

/* Desktop tab overrides */
.el-tabs__header { margin-bottom: 24px !important; }
</style>
