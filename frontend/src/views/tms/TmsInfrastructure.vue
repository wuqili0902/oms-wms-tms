<template>
  <div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="中转站" name="hubs">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>中转站管理</span>
              <el-button type="primary" @click="showCreateHub = true">新建中转站</el-button>
            </div>
          </template>
          <el-table :data="hubs" stripe v-loading="hubLoading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column prop="code" label="编码" width="100" />
            <el-table-column prop="name" label="名称" width="180" />
            <el-table-column prop="type" label="类型" width="120" />
            <el-table-column prop="city" label="城市" width="120" />
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="175" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="editHub(row)">编辑</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="承运商路由" name="routes">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>承运商路由</span>
              <el-button type="primary" @click="showCreateRoute = true">新建路由</el-button>
            </div>
          </template>
          <el-table :data="carrierRoutes" stripe v-loading="routeLoading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column prop="carrier_code" label="承运商" width="120" />
            <el-table-column prop="origin_city" label="出发城市" width="120" />
            <el-table-column prop="dest_city" label="目的城市" width="120" />
            <el-table-column prop="distance_km" label="距离(km)" width="100" />
            <el-table-column prop="transit_hours" label="时效(h)" width="80" />
            <el-table-column prop="base_price_per_kg" label="单价/kg" width="100" />
            <el-table-column prop="express_surcharge" label="加急附加费" width="120" />
            <el-table-column prop="created_at" label="创建时间" width="175" />
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="中转连接" name="connections">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>中转连接</span>
              <el-button type="primary" @click="showCreateConn = true">新建连接</el-button>
            </div>
          </template>
          <el-table :data="connections" stripe v-loading="connLoading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column prop="from_hub_code" label="来源中转站" width="150" />
            <el-table-column prop="to_hub_code" label="目标中转站" width="150" />
            <el-table-column prop="distance_km" label="距离(km)" width="100" />
            <el-table-column prop="transit_hours" label="时效(h)" width="100" />
            <el-table-column prop="created_at" label="创建时间" width="175" />
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="showCreateHub" title="新建中转站" width="500px" destroy-on-close>
      <el-form :model="hubForm" label-width="100px">
        <el-form-item label="编码"><el-input v-model="hubForm.code" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="hubForm.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="hubForm.type" style="width:100%">
            <el-option label="主站" value="primary" /><el-option label="副站" value="secondary" /><el-option label="货运站" value="cargo_station" />
          </el-select>
        </el-form-item>
        <el-form-item label="城市"><el-input v-model="hubForm.city" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateHub = false">取消</el-button>
        <el-button type="primary" :loading="hubCreating" @click="submitHub">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showEditHub" title="编辑中转站" width="500px" destroy-on-close>
      <el-form :model="hubEditForm" label-width="100px">
        <el-form-item label="编码"><el-input v-model="hubEditForm.code" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="hubEditForm.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="hubEditForm.type" style="width:100%">
            <el-option label="主站" value="primary" /><el-option label="副站" value="secondary" /><el-option label="货运站" value="cargo_station" />
          </el-select>
        </el-form-item>
        <el-form-item label="城市"><el-input v-model="hubEditForm.city" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditHub = false">取消</el-button>
        <el-button type="primary" :loading="hubUpdating" @click="submitEditHub">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCreateRoute" title="新建承运商路由" width="550px" destroy-on-close>
      <el-form :model="routeForm" label-width="120px">
        <el-form-item label="承运商">
          <el-select v-model="routeForm.carrier_code" style="width:100%">
            <el-option label="顺丰" value="sf_express" /><el-option label="中通" value="zto" />
            <el-option label="韵达" value="yunda" /><el-option label="京东物流" value="jd_logistics" /><el-option label="EMS" value="ems" />
          </el-select>
        </el-form-item>
        <el-form-item label="出发城市"><el-input v-model="routeForm.origin_city" /></el-form-item>
        <el-form-item label="目的城市"><el-input v-model="routeForm.dest_city" /></el-form-item>
        <el-form-item label="距离(km)"><el-input-number v-model="routeForm.distance_km" :min="1" style="width:100%" /></el-form-item>
        <el-form-item label="时效(h)"><el-input-number v-model="routeForm.transit_hours" :min="1" style="width:100%" /></el-form-item>
        <el-form-item label="单价/kg"><el-input-number v-model="routeForm.base_price_per_kg" :min="0" :precision="2" style="width:100%" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateRoute = false">取消</el-button>
        <el-button type="primary" :loading="routeCreating" @click="submitRoute">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCreateConn" title="新建中转连接" width="500px" destroy-on-close>
      <el-form :model="connForm" label-width="120px">
        <el-form-item label="来源中转站"><el-input v-model="connForm.from_hub_code" /></el-form-item>
        <el-form-item label="目标中转站"><el-input v-model="connForm.to_hub_code" /></el-form-item>
        <el-form-item label="距离(km)"><el-input-number v-model="connForm.distance_km" :min="1" style="width:100%" /></el-form-item>
        <el-form-item label="时效(h)"><el-input-number v-model="connForm.transit_hours" :min="1" style="width:100%" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateConn = false">取消</el-button>
        <el-button type="primary" :loading="connCreating" @click="submitConn">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

const activeTab = ref('hubs')
const hubLoading = ref(false); const hubCreating = ref(false)
const routeLoading = ref(false); const routeCreating = ref(false)
const connLoading = ref(false); const connCreating = ref(false)
const hubs = ref<any[]>([]); const carrierRoutes = ref<any[]>([]); const connections = ref<any[]>([])
const showCreateHub = ref(false); const showCreateRoute = ref(false); const showCreateConn = ref(false)
const showEditHub = ref(false); const editHubId = ref<number|null>(null)
const hubForm = reactive({ code: '', name: '', type: 'primary', city: '' })
const hubEditForm = reactive({ code: '', name: '', type: 'primary', city: '' })
const hubUpdating = ref(false)
const routeForm = reactive({ carrier_code: 'sf_express', origin_city: '', dest_city: '', distance_km: 100, transit_hours: 24, base_price_per_kg: 10 })
const connForm = reactive({ from_hub_code: '', to_hub_code: '', distance_km: 100, transit_hours: 6 })

async function fetchHubs() {
  hubLoading.value = true
  try { const res = await apiClient.get('/transfer-hubs'); const d = res.data?.data ?? res.data ?? []; hubs.value = Array.isArray(d) ? d : (d.items ?? []) } catch { hubs.value = [] }
  hubLoading.value = false
}
async function fetchRoutes() {
  routeLoading.value = true
  try { const res = await apiClient.get('/carrier-routes'); const d = res.data?.data ?? res.data ?? []; carrierRoutes.value = Array.isArray(d) ? d : (d.items ?? []) } catch { carrierRoutes.value = [] }
  routeLoading.value = false
}
async function fetchConns() {
  connLoading.value = true
  try { const res = await apiClient.get('/hub-connections'); const d = res.data?.data ?? res.data ?? []; connections.value = Array.isArray(d) ? d : (d.items ?? []) } catch { connections.value = [] }
  connLoading.value = false
}
async function submitHub() {
  hubCreating.value = true
  try { await apiClient.post('/transfer-hubs', hubForm); ElMessage.success('创建成功'); showCreateHub.value = false; fetchHubs() } catch { /* ignore */ }
  hubCreating.value = false
}
async function editHub(row: any) {
  editHubId.value = row.id
  hubEditForm.code = row.code || ''; hubEditForm.name = row.name || ''
  hubEditForm.type = row.type || 'primary'; hubEditForm.city = row.city || ''
  showEditHub.value = true
}
async function submitEditHub() {
  hubUpdating.value = true
  try { await apiClient.patch(`/transfer-hubs/${editHubId.value}`, hubEditForm); ElMessage.success('已更新'); showEditHub.value = false; fetchHubs() } catch { /* ignore */ }
  hubUpdating.value = false
}
async function submitRoute() {
  routeCreating.value = true
  try { await apiClient.post('/carrier-routes', routeForm); ElMessage.success('创建成功'); showCreateRoute.value = false; fetchRoutes() } catch { /* ignore */ }
  routeCreating.value = false
}
async function submitConn() {
  connCreating.value = true
  try { await apiClient.post('/hub-connections', connForm); ElMessage.success('创建成功'); showCreateConn.value = false; fetchConns() } catch { /* ignore */ }
  connCreating.value = false
}
onMounted(() => { fetchHubs(); fetchRoutes(); fetchConns() })
</script>
