<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>设备管理</span>
          <el-button type="primary" @click="showCreate = true">注册设备</el-button>
        </div>
      </template>
      <el-table :data="devices" stripe v-loading="loading" style="width:100%">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="device_code" label="设备编码" width="140" />
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">{{ row.device_type || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_online ? 'success' : 'danger'" size="small">{{ row.is_online ? '在线' : '离线' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_heartbeat" label="最后心跳" width="175" />
        <el-table-column prop="created_at" label="注册时间" width="175" />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="editDevice(row)">编辑</el-button>
            <el-button size="small" type="danger" link @click="deleteDevice(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="display:flex;justify-content:flex-end;margin-top:12px">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="onPageChange" @size-change="onSizeChange" />
      </div>
    </el-card>

    <el-dialog v-model="showEdit" title="编辑设备" width="500px" destroy-on-close>
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="设备编码"><el-input v-model="editForm.device_code" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="editForm.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="editForm.device_type" style="width:100%">
            <el-option label="PDA" value="pda" />
            <el-option label="扫描枪" value="scanner" />
            <el-option label="打印机" value="printer" />
            <el-option label="终端" value="terminal" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEdit = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCreate" title="注册设备" width="500px" destroy-on-close @closed="resetCreateForm">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="设备编码">
          <el-input v-model="createForm.device_code" placeholder="唯一编码" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="createForm.name" placeholder="设备名称" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="createForm.device_type" style="width:100%">
            <el-option label="PDA" value="pda" />
            <el-option label="扫描枪" value="scanner" />
            <el-option label="打印机" value="printer" />
            <el-option label="终端" value="terminal" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { usePagination } from '../../composables/usePagination'
import apiClient from '../../api'

const loading = ref(false)
const creating = ref(false)
const editing = ref(false)
const devices = ref<any[]>([])
const showCreate = ref(false)
const showEdit = ref(false)
const editId = ref<number|null>(null)
const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()
const createForm = reactive({ device_code: '', name: '', device_type: 'pda' })
const editForm = reactive({ device_code: '', name: '', device_type: 'pda' })

async function fetchDevices() {
  loading.value = true
  try {
    const res = await apiClient.get(`/devices?page=${page.value}&page_size=${pageSize.value}`)
    const d = res.data?.data ?? res.data ?? []
    let items
    if (Array.isArray(d)) { items = d; total.value = d.length }
    else { items = d.items ?? []; total.value = d.total ?? d.items?.length ?? 0 }
    devices.value = items
  } catch (e: any) { devices.value = []; ElMessage.error(e?.response?.data?.detail ?? e.message) }
  loading.value = false
}

function resetCreateForm() { Object.assign(createForm, { device_code: '', name: '', device_type: 'pda' }) }

async function submitCreate() {
  creating.value = true
  try {
    await apiClient.post('/devices', createForm)
    ElMessage.success('设备注册成功')
    showCreate.value = false
    fetchDevices()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? e.message) }
  creating.value = false
}

async function editDevice(row: any) {
  editId.value = row.id
  editForm.device_code = row.device_code || ''
  editForm.name = row.name || ''
  editForm.device_type = row.device_type || 'pda'
  showEdit.value = true
}

async function submitEdit() {
  editing.value = true
  try {
    await apiClient.patch(`/devices/${editId.value}`, editForm)
    ElMessage.success('设备已更新')
    showEdit.value = false
    fetchDevices()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? e.message) }
  editing.value = false
}

async function deleteDevice(row: any) {
  try {
    await ElMessageBox.confirm('确定要删除此设备？', '确认', { type: 'warning' })
    await apiClient.delete(`/devices/${row.id}`)
    ElMessage.success('设备已删除')
    fetchDevices()
  } catch { /* ignore */ }
}

onMounted(fetchDevices)
</script>
