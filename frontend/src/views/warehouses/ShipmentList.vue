<template>
  <div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="发货管理" name="shipments">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>发货单</span>
              <el-button type="primary" @click="showCreateShipment = true">新建发货单</el-button>
            </div>
          </template>
          <el-table :data="shipments" stripe v-loading="loading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="shipment_no" label="发货单号" width="180" />
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.status === 'shipped' ? 'success' : 'warning'" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="warehouse_id" label="仓库ID" width="180" />
            <el-table-column prop="created_at" label="创建时间" width="175" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button size="small" type="primary" link :disabled="row.status==='shipped'" @click="markShipped(row)">发货</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div style="display:flex;justify-content:flex-end;margin-top:12px">
            <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="onPageChange" @size-change="onSizeChange" />
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="打包记录" name="packing">
        <el-card>
          <template #header>
            <span>打包记录</span>
          </template>
          <el-form :model="packForm" label-width="100px" style="max-width:500px;margin-bottom:16px">
            <el-form-item label="波次ID">
              <el-input v-model="packForm.wave_id" placeholder="拣货波次UUID" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="packLoading" @click="submitPacking">记录打包</el-button>
            </el-form-item>
          </el-form>
          <el-alert v-if="packResult" type="success" :title="`打包记录成功: ${packResult.id}`" show-icon closable />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="showCreateShipment" title="新建发货单" width="500px" destroy-on-close @closed="resetShipForm">
      <el-form :model="shipForm" label-width="100px">
        <el-form-item label="仓库ID">
          <el-input v-model="shipForm.warehouse_id" placeholder="仓库UUID" />
        </el-form-item>
        <el-form-item label="订单ID列表">
          <el-input v-model="shipForm.order_ids" type="textarea" :rows="4" placeholder="每行一个订单ID" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateShipment = false">取消</el-button>
        <el-button type="primary" :loading="shipCreating" @click="submitShipment">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { usePagination } from '../../composables/usePagination'
import apiClient from '../../api'

const activeTab = ref('shipments')
const loading = ref(false)
const shipCreating = ref(false)
const packLoading = ref(false)
const shipments = ref<any[]>([])
const showCreateShipment = ref(false)
const packResult = ref<any>(null)
const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()

const shipForm = reactive({ warehouse_id: '', order_ids: '' })
const packForm = reactive({ wave_id: '' })

async function fetchShipments() {
  loading.value = true
  try {
    const res = await apiClient.get(`/warehouses/shipments?page=${page.value}&page_size=${pageSize.value}`)
    const d = res.data?.data ?? res.data ?? []
    let items
    if (Array.isArray(d)) { items = d; total.value = d.length }
    else { items = d.items ?? []; total.value = d.total ?? d.items?.length ?? 0 }
    shipments.value = items
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
    shipments.value = []
  }
  loading.value = false
}

function resetShipForm() { shipForm.warehouse_id = ''; shipForm.order_ids = '' }

async function submitShipment() {
  shipCreating.value = true
  try {
    const orderIds = shipForm.order_ids.split('\n').map(s => s.trim()).filter(Boolean)
    await apiClient.post('/warehouses/shipments', { warehouse_id: shipForm.warehouse_id, order_ids: orderIds })
    ElMessage.success('发货单创建成功')
    showCreateShipment.value = false
    fetchShipments()
   } catch (e: any) {
      ElMessage.error(e?.response?.data?.detail ?? '发货单创建失败')
    }
    shipCreating.value = false
  }

  async function markShipped(row: any) {
    try {
      await apiClient.post(`/warehouses/shipments/${row.id}/ship`)
      ElMessage.success('已标记为已发货')
      fetchShipments()
    } catch (e: any) {
      console.warn('[shipment-list] markShipped failed:', e?.response?.data ?? e)
    }
  }

  async function submitPacking() {
    packLoading.value = true
    packResult.value = null
    try {
      const res = await apiClient.post('/warehouses/packing', { wave_id: packForm.wave_id })
      packResult.value = res.data?.data ?? res.data
      ElMessage.success('打包记录成功')
    } catch (e: any) {
      console.warn('[shipment-list] submitPacking failed:', e?.response?.data ?? e)
    }
    packLoading.value = false
  }

onMounted(fetchShipments)
</script>
