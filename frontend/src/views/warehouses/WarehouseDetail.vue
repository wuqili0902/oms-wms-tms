<template>
  <div>
    <el-button text style="margin-bottom:12px" @click="$router.push('/warehouses')">
      <el-icon><ArrowLeft /></el-icon> 返回仓库列表
    </el-button>

    <el-card v-loading="loading">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>仓库详情：{{ wh?.name }}</span>
          <el-tag :type="wh?.is_active !== false ? 'success' : 'danger'">
            {{ wh?.is_active !== false ? '启用' : '停用' }}
          </el-tag>
        </div>
      </template>

      <el-descriptions :column="2" border>
        <el-descriptions-item label="编码">{{ wh?.code }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ wh?.type || wh?.warehouse_type }}</el-descriptions-item>
        <el-descriptions-item label="地址" :span="2">{{ wh?.address || '无' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ wh?.created_at }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ wh?.updated_at }}</el-descriptions-item>
      </el-descriptions>
      <el-button type="primary" size="small" style="margin-top:12px" @click="showEdit = true">编辑</el-button>
    </el-card>

    <el-card style="margin-top:16px">
      <template #header>库存概览</template>
      <el-table :data="inventory" stripe v-loading="invLoading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column prop="sku" label="SKU" width="150" />
        <el-table-column prop="quantity" label="数量" width="100" />
        <el-table-column prop="reserved_qty" label="已预留" width="100" />
        <el-table-column label="可用" width="100">
          <template #default="{ row }">
            <span :style="{color: (row.available_qty||0) < 0 ? '#f56c6c' : '#67c23a'}">
              {{ row.available_qty ?? (row.quantity - row.reserved_qty) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="location_id" label="库位ID" width="180" />
      </el-table>
    </el-card>

    <el-card style="margin-top:16px">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>库位管理</span>
          <div>
            <el-button size="small" @click="fetchLocations">刷新</el-button>
            <el-button size="small" type="primary" @click="showCreateLoc = true">新建库位</el-button>
          </div>
        </div>
      </template>
      <el-table :data="locations" stripe v-loading="locLoading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column prop="code" label="库位编码" width="140" />
        <el-table-column prop="zone" label="区域" width="100" />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">{{ row.location_type || row.type || '—' }}</template>
        </el-table-column>
        <el-table-column label="可用" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active !== false ? 'success' : 'danger'" size="small">{{ row.is_active !== false ? '是' : '否' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="175" />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="editLoc(row)">编辑</el-button>
            <el-button size="small" type="danger" link @click="deleteLoc(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreateLoc" title="新建库位" width="500px" destroy-on-close>
      <el-form :model="locCreateForm" label-width="100px">
        <el-form-item label="库位编码"><el-input v-model="locCreateForm.code" /></el-form-item>
        <el-form-item label="区域"><el-input v-model="locCreateForm.zone" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="locCreateForm.location_type" style="width:100%">
            <el-option label="货架" value="shelf" /><el-option label="地面堆垛" value="floor" /><el-option label="冷藏" value="cold_storage" /><el-option label="暂存区" value="staging" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateLoc = false">取消</el-button>
        <el-button type="primary" :loading="locCreating" @click="submitCreateLoc">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showEditLoc" title="编辑库位" width="500px" destroy-on-close>
      <el-form :model="locEditForm" label-width="100px">
        <el-form-item label="库位编码"><el-input v-model="locEditForm.code" /></el-form-item>
        <el-form-item label="区域"><el-input v-model="locEditForm.zone" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="locEditForm.location_type" style="width:100%">
            <el-option label="货架" value="shelf" /><el-option label="地面堆垛" value="floor" /><el-option label="冷藏" value="cold_storage" /><el-option label="暂存区" value="staging" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="locEditForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditLoc = false">取消</el-button>
        <el-button type="primary" :loading="locUpdating" @click="submitEditLoc">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showEdit" title="编辑仓库" width="500px" destroy-on-close>
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="名称"><el-input v-model="editForm.name" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="editForm.address" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="editForm.type" style="width:100%">
            <el-option label="中心仓" value="center" /><el-option label="区域仓" value="regional" /><el-option label="前置仓" value="front" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="editForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEdit = false">取消</el-button>
        <el-button type="primary" :loading="editLoading" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import apiClient from '../../api'

const route = useRoute()
const wh = ref<any>(null)
const loading = ref(false)
const inventory = ref<any[]>([])
const invLoading = ref(false)
const showEdit = ref(false)
const editLoading = ref(false)
const editForm = reactive({ name: '', address: '', type: 'center', is_active: true })
const locations = ref<any[]>([])
const locLoading = ref(false)
const showCreateLoc = ref(false)
const showEditLoc = ref(false)
const locCreating = ref(false)
const locUpdating = ref(false)
const editLocId = ref<number|null>(null)
const locCreateForm = reactive({ code: '', zone: '', location_type: 'shelf' })
const locEditForm = reactive({ code: '', zone: '', location_type: 'shelf', is_active: true })

async function submitEdit() {
  editLoading.value = true
  try {
    await apiClient.put(`/warehouses/${route.params.id}`, editForm)
    ElMessage.success('保存成功')
    showEdit.value = false
    const res = await apiClient.get(`/warehouses/${route.params.id}`)
    wh.value = res.data?.data ?? res.data
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '保存失败') }
  editLoading.value = false
}

const whId = () => route.params.id as string

async function fetchLocations() {
  locLoading.value = true
  try {
    const res = await apiClient.get(`/warehouses/${whId()}/locations`)
    const d = res.data?.data ?? res.data ?? []
    locations.value = Array.isArray(d) ? d : (d.items ?? [])
  } catch (e: any) { console.warn('[WarehouseDetail] fetchLocations failed:', e?.response?.data ?? e); locations.value = [] }
  locLoading.value = false
}

async function submitCreateLoc() {
  locCreating.value = true
  try {
    await apiClient.post(`/warehouses/${whId()}/locations`, locCreateForm)
    ElMessage.success('创建成功')
    showCreateLoc.value = false
    fetchLocations()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '创建失败') }
  locCreating.value = false
}

function editLoc(row: any) {
  editLocId.value = row.id
  locEditForm.code = row.code || ''
  locEditForm.zone = row.zone || ''
  locEditForm.location_type = row.location_type || row.type || 'shelf'
  locEditForm.is_active = row.is_active !== false
  showEditLoc.value = true
}

async function submitEditLoc() {
  locUpdating.value = true
  try {
    await apiClient.put(`/warehouses/${whId()}/locations/${editLocId.value}`, locEditForm)
    ElMessage.success('保存成功')
    showEditLoc.value = false
    fetchLocations()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '保存失败') }
  locUpdating.value = false
}

async function deleteLoc(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除库位 ${row.code}？`, '提示')
    await apiClient.delete(`/warehouses/${whId()}/locations/${row.id}`)
    ElMessage.success('删除成功')
    fetchLocations()
  } catch (e: any) {
    if (!e?.response && e !== true) ElMessage.error(e?.response?.data?.detail ?? '删除失败')
  }
}

onMounted(async () => {
  const id = route.params.id as string
  if (!id) return
  loading.value = true
  try {
    const res = await apiClient.get(`/warehouses/${id}`)
    wh.value = res.data?.data ?? res.data
    editForm.name = wh.value?.name ?? ''
    editForm.address = wh.value?.address ?? ''
    editForm.type = wh.value?.type ?? wh.value?.warehouse_type ?? 'center'
    editForm.is_active = wh.value?.is_active ?? true
  } catch (e: any) { console.error('[WarehouseDetail] onMounted fetch failed:', e?.response?.data ?? e); ElMessage.error('获取仓库信息失败') }
  loading.value = false

  invLoading.value = true
  try {
    const res = await apiClient.get(`/warehouses/inventory?warehouse_id=${id}`)
    inventory.value = (res.data?.data ?? res.data?.items ?? res.data) || []
  } catch (e: any) { console.warn('[WarehouseDetail] fetchInventory failed:', e?.response?.data ?? e); inventory.value = [] }
  invLoading.value = false

  fetchLocations()
})
</script>
