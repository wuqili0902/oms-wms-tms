<template>
  <div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="仓库列表" name="list">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>仓库列表</span>
              <el-button type="primary" @click="showCreate = true">新建仓库</el-button>
            </div>
          </template>
          <el-table :data="warehouses" stripe v-loading="loading" style="width:100%">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="code" label="编码" width="120" />
            <el-table-column prop="name" label="名称" width="180" />
            <el-table-column prop="type" label="类型" width="100">
              <template #default="{ row }">{{ typeLabel(row.type||row.warehouse_type) }}</template>
            </el-table-column>
            <el-table-column prop="address" label="地址" min-width="200" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.is_active !== false ? 'success' : 'danger'" size="small">
                  {{ row.is_active !== false ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="175" />
            <el-table-column label="操作" width="160" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="viewDetail(row)">详情</el-button>
                <el-button size="small" type="primary" link @click="showLocations(row)">库位</el-button>
                <el-button size="small" type="danger" link @click="handleDelete(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="库存查询" name="inventory">
        <el-card>
          <template #header>
            <div style="display:flex;align-items:center;gap:12px">
              <span>库存查询</span>
              <el-input v-model="invFilters.sku" placeholder="SKU" clearable style="width:150px" />
              <el-input v-model="invFilters.warehouse_id" placeholder="仓库ID" clearable style="width:180px" />
              <el-button type="primary" @click="fetchInventory">查询</el-button>
            </div>
          </template>
          <el-table :data="inventory" stripe v-loading="invLoading" style="width:100%">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column prop="warehouse_id" label="仓库ID" width="180" />
            <el-table-column prop="location_id" label="库位ID" width="180" />
            <el-table-column prop="sku" label="SKU" width="150" />
            <el-table-column prop="quantity" label="数量" width="100" />
            <el-table-column prop="reserved_qty" label="已预留" width="100" />
            <el-table-column prop="available_qty" label="可用" width="100">
              <template #default="{ row }">
                <span :style="{color: (row.available_qty||0) < 0 ? '#f56c6c' : '#67c23a'}">
                  {{ row.available_qty ?? (row.quantity - row.reserved_qty) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button size="small" type="warning" link @click="openAdjust(row)">调整</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="库存变动" name="movements">
        <el-card>
          <template #header>
            <div style="display:flex;align-items:center;gap:12px">
              <span>库存变动记录</span>
              <el-input v-model="movFilters.warehouse_id" placeholder="仓库ID" clearable style="width:180px" />
              <el-button type="primary" @click="fetchMovements">查询</el-button>
            </div>
          </template>
          <el-table :data="movements" stripe v-loading="movLoading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column prop="warehouse_id" label="仓库ID" width="180" />
            <el-table-column prop="sku" label="SKU" width="140" />
            <el-table-column prop="type" label="类型" width="120">
              <template #default="{ row }">
                <el-tag :type="row.quantity > 0 ? 'success' : 'danger'" size="small">
                  {{ row.type }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="quantity" label="数量" width="100" />
            <el-table-column prop="reference_no" label="参考单号" width="160" />
            <el-table-column prop="from_location_id" label="来源库位" width="180" />
            <el-table-column prop="to_location_id" label="目标库位" width="180" />
            <el-table-column prop="created_at" label="时间" width="175" />
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="拣货波次" name="picking">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>拣货波次</span>
              <el-button type="primary" size="small" @click="showCreateWave = true">新建波次</el-button>
            </div>
          </template>
          <el-table :data="waves" stripe v-loading="waveLoading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column prop="wave_no" label="波次号" width="160" />
            <el-table-column prop="warehouse_id" label="仓库ID" width="180" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.status === 'active' ? 'success' : row.status === 'completed' ? 'info' : 'warning'" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="total_items" label="商品数" width="80" />
            <el-table-column label="操作" width="200">
              <template #default="{ row }">
                <el-button size="small" type="success" link :disabled="row.status!=='active'" @click="startWave(row)">开始</el-button>
                <el-button size="small" type="info" link :disabled="row.status!=='picking'" @click="completeWave(row)">完成</el-button>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="175" />
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="showCreate" title="新建仓库" width="550px" destroy-on-close>
      <el-form :model="createForm" label-width="100px" :rules="createRules" ref="createFormRef">
        <el-form-item label="编码" prop="code">
          <el-input v-model="createForm.code" placeholder="仓库编码" />
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="createForm.name" placeholder="仓库名称" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="createForm.type" style="width:100%">
            <el-option label="中心仓" value="center" />
            <el-option label="区域仓" value="regional" />
            <el-option label="前置仓" value="front" />
          </el-select>
        </el-form-item>
        <el-form-item label="地址">
          <el-input v-model="createForm.address" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="createForm.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showLocationDialog" title="库位管理" width="800px" destroy-on-close>
      <template v-if="currentWarehouse">
        <div style="margin-bottom:12px;display:flex;justify-content:space-between;align-items:center">
          <span>{{ currentWarehouse.name }} - 库位列表</span>
          <el-button size="small" type="primary" @click="showAddLocation = true">新建库位</el-button>
        </div>
        <el-table :data="locations" stripe v-loading="locLoading">
          <template #empty><el-empty description="暂无数据" /></template>
          <el-table-column prop="location_code" label="库位编码" width="130" />
          <el-table-column prop="zone" label="区域" width="90" />
          <el-table-column prop="aisle" label="通道" width="80" />
          <el-table-column prop="shelf" label="货架" width="80" />
          <el-table-column prop="bin" label="货位" width="80" />
          <el-table-column prop="type" label="类型" width="120">
            <template #default="{ row }">
              <el-tag size="small">{{ locTypeLabel(row.type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="占用" width="70">
            <template #default="{ row }">
              <el-tag :type="row.is_occupied ? 'danger' : 'success'" size="small">
                {{ row.is_occupied ? '是' : '否' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <template #footer><el-button @click="showLocationDialog = false">关闭</el-button></template>
    </el-dialog>

    <el-dialog v-model="showAddLocation" title="新建库位" width="500px" destroy-on-close>
      <el-form :model="locationForm" label-width="100px">
        <el-form-item label="区域" prop="zone">
          <el-input v-model="locationForm.zone" placeholder="A/B/C" />
        </el-form-item>
        <el-form-item label="通道" prop="aisle">
          <el-input v-model="locationForm.aisle" placeholder="01/02" />
        </el-form-item>
        <el-form-item label="货架" prop="shelf">
          <el-input v-model="locationForm.shelf" placeholder="01/02" />
        </el-form-item>
        <el-form-item label="货位" prop="bin">
          <el-input v-model="locationForm.bin" placeholder="01/02" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="locationForm.type" style="width:100%">
            <el-option label="存储" value="storage" />
            <el-option label="拣货" value="picking" />
            <el-option label="收货" value="receiving" />
            <el-option label="发货" value="shipping" />
            <el-option label="报废" value="damage" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddLocation = false">取消</el-button>
        <el-button type="primary" :loading="locCreating" @click="submitLocation">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showAdjust" title="库存调整" width="450px" destroy-on-close>
      <el-form :model="adjustForm" label-width="100px">
        <el-form-item label="仓库ID">
          <el-input v-model="adjustForm.warehouse_id" disabled />
        </el-form-item>
        <el-form-item label="库位ID">
          <el-input v-model="adjustForm.location_id" disabled />
        </el-form-item>
        <el-form-item label="SKU">
          <el-input v-model="adjustForm.sku" disabled />
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="adjustForm.quantity" :min="-999999" :max="999999" style="width:100%" />
          <span style="font-size:12px;color:#909399">正数=入库，负数=出库</span>
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="adjustForm.reason" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAdjust = false">取消</el-button>
        <el-button type="primary" :loading="adjusting" @click="submitAdjust">确认调整</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCreateWave" title="新建拣货波次" width="500px" destroy-on-close @closed="createWaveForm.warehouse_id='';createWaveForm.order_ids=''">
      <el-form :model="createWaveForm" label-width="100px">
        <el-form-item label="仓库ID">
          <el-input v-model="createWaveForm.warehouse_id" placeholder="仓库UUID" />
        </el-form-item>
        <el-form-item label="订单ID列表">
          <el-input v-model="createWaveForm.order_ids" type="textarea" :rows="4" placeholder="每行一个订单ID" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateWave = false">取消</el-button>
        <el-button type="primary" :loading="waveCreating" @click="submitWave">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import apiClient from '../../api'
import type { FormInstance, FormRules } from 'element-plus'

const router = useRouter()
const activeTab = ref('list')
const loading = ref(false)
const creating = ref(false)
const invLoading = ref(false)
const locLoading = ref(false)
const locCreating = ref(false)
const adjusting = ref(false)
const warehouses = ref<any[]>([])
const inventory = ref<any[]>([])
const locations = ref<any[]>([])
const currentWarehouse = ref<any>(null)
const showCreate = ref(false)
const showLocationDialog = ref(false)
const showAddLocation = ref(false)
const showAdjust = ref(false)
const createFormRef = ref<FormInstance>()

const createForm = reactive({ code: '', name: '', type: 'center', address: '', is_active: true })
const createRules: FormRules = {
  code: [{ required: true, message: '请输入编码', trigger: 'blur' }],
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
}

const invFilters = reactive({ sku: '', warehouse_id: '' })

const locationForm = reactive({ zone: '', aisle: '', shelf: '', bin: '', type: 'storage' })

const adjustForm = reactive({ warehouse_id: '', location_id: '', sku: '', quantity: 0, reason: 'adjustment' })

const movements = ref<any[]>([])
const movLoading = ref(false)
const movFilters = reactive({ warehouse_id: '' })

const waves = ref<any[]>([])
const waveLoading = ref(false)
const showCreateWave = ref(false)
const createWaveForm = reactive({ warehouse_id: '', order_ids: '' })
const waveCreating = ref(false)

function typeLabel(t: string) {
  const map: Record<string, string> = { center: '中心仓', regional: '区域仓', front: '前置仓' }
  return map[t] || t
}

function locTypeLabel(t: string) {
  const map: Record<string, string> = { storage: '存储', picking: '拣货', receiving: '收货', shipping: '发货', quarantine: '待检', damage: '报废' }
  return map[t] || t
}

async function fetchWarehouses() {
  loading.value = true
  try {
    const res = await apiClient.get('/warehouses?page=1&page_size=50')
    const body = res.data?.data ?? res.data ?? {}
    warehouses.value = body.items ?? body ?? []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
    warehouses.value = []
  }
  loading.value = false
}

async function fetchInventory() {
  invLoading.value = true
  try {
    const params = new URLSearchParams()
    if (invFilters.sku) params.set('sku', invFilters.sku)
    if (invFilters.warehouse_id) params.set('warehouse_id', invFilters.warehouse_id)
    const res = await apiClient.get(`/warehouses/inventory?${params}`)
    const body = res.data?.data ?? res.data ?? []
    inventory.value = Array.isArray(body) ? body : []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
    inventory.value = []
  }
  invLoading.value = false
}

function viewDetail(row: any) {
  router.push(`/warehouses/${row.id}`)
}

async function showLocations(row: any) {
  currentWarehouse.value = row
  showLocationDialog.value = true
  locLoading.value = true
  try {
    const res = await apiClient.get(`/warehouses/${row.id}/locations?page=1&page_size=100`)
    const body = res.data?.data ?? res.data ?? {}
    locations.value = body.items ?? body ?? []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
    locations.value = []
  }
  locLoading.value = false
}

async function submitCreate() {
  const valid = await createFormRef.value?.validate().catch(() => false)
  if (!valid) return
  creating.value = true
  try {
    await apiClient.post('/warehouses', createForm)
    ElMessage.success('创建成功')
    showCreate.value = false
    fetchWarehouses()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
  creating.value = false
}

async function submitLocation() {
  locCreating.value = true
  try {
    await apiClient.post(`/warehouses/${currentWarehouse.value!.id}/locations`, locationForm)
    ElMessage.success('库位创建成功')
    showAddLocation.value = false
    showLocations(currentWarehouse.value!)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
  locCreating.value = false
}

async function handleDelete(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除仓库 ${row.name}？`, '提示')
    await apiClient.delete(`/warehouses/${row.id}`)
    ElMessage.success('删除成功')
    fetchWarehouses()
  } catch { /* ignore */ }
}

function openAdjust(row: any) {
  adjustForm.warehouse_id = row.warehouse_id
  adjustForm.location_id = row.location_id
  adjustForm.sku = row.sku
  adjustForm.quantity = 0
  adjustForm.reason = 'adjustment'
  showAdjust.value = true
}

async function submitAdjust() {
  adjusting.value = true
  try {
    await apiClient.post('/warehouses/inventory/adjust', adjustForm)
    ElMessage.success('调整成功')
    showAdjust.value = false
    fetchInventory()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
  adjusting.value = false
}

async function fetchMovements() {
  movLoading.value = true
  try {
    const params = new URLSearchParams()
    if (movFilters.warehouse_id) params.set('warehouse_id', movFilters.warehouse_id)
    const res = await apiClient.get(`/warehouses/inventory/movements?${params}`)
    const body = res.data?.data ?? res.data ?? []
    movements.value = Array.isArray(body) ? body : []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
    movements.value = []
  }
  movLoading.value = false
}

async function fetchWaves() {
  waveLoading.value = true
  try {
    const res = await apiClient.get('/warehouses/picking-waves?page=1&page_size=50')
    const body = res.data?.data ?? res.data ?? []
    waves.value = Array.isArray(body) ? body : (body.items ?? [])
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
    waves.value = []
  }
  waveLoading.value = false
}

async function submitWave() {
  waveCreating.value = true
  try {
    const orderIds = createWaveForm.order_ids.split('\n').map(s => s.trim()).filter(Boolean)
    await apiClient.post('/warehouses/picking-waves', {
      warehouse_id: createWaveForm.warehouse_id,
      order_ids: orderIds,
    })
    ElMessage.success('波次创建成功')
    showCreateWave.value = false
    fetchWaves()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
  waveCreating.value = false
}

async function startWave(row: any) {
  try {
    await apiClient.post(`/warehouses/picking-waves/${row.id}/start`)
    ElMessage.success('波次已开始')
    fetchWaves()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
}

async function completeWave(row: any) {
  try {
    await apiClient.post(`/warehouses/picking-waves/${row.id}/complete`)
    ElMessage.success('波次已完成')
    fetchWaves()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
}

onMounted(() => {
  fetchWarehouses()
})
</script>
