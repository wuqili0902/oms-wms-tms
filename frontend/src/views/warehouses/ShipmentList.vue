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
                <el-tag :type="statusTag(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="carrier" label="承运商" width="110">
              <template #default="{ row }">{{ carrierLabel(row.carrier) }}</template>
            </el-table-column>
            <el-table-column prop="tracking_number" label="运单号" width="170" />
            <el-table-column prop="warehouse_id" label="仓库ID" width="180" />
            <el-table-column prop="created_at" label="创建时间" width="175" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button size="small" type="primary" link :disabled="['shipped', 'delivered', 'cancelled'].includes(row.status)" @click="markShipped(row)">发货</el-button>
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
            <el-form-item label="箱数">
              <el-input-number v-model="packForm.box_count" :min="1" style="width:100%" />
            </el-form-item>
            <el-form-item label="打包人">
              <el-input v-model="packForm.packed_by" placeholder="打包人工号/姓名" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="packLoading" @click="submitPacking">记录打包</el-button>
            </el-form-item>
          </el-form>
          <el-alert v-if="packResult" type="success" :title="`打包记录成功: ${packResult.box_count} 箱`" show-icon closable />
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
        <el-form-item label="承运商">
          <!-- 承运商 is free text on the server, so the list is a shortcut, not a cage. -->
          <el-select v-model="shipForm.carrier" clearable filterable allow-create default-first-option
                     placeholder="交接给哪家承运商" style="width:100%">
            <el-option v-for="c in CARRIERS" :key="c.value" :label="c.label" :value="c.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="运单号">
          <el-input v-model="shipForm.tracking_number" placeholder="承运商运单号（可留空，发货时补录）" />
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
import { errText } from '../../api/errors'
import { CARRIERS, carrierLabel } from '../../constants/carriers'

const activeTab = ref('shipments')
const loading = ref(false)
const shipCreating = ref(false)
const packLoading = ref(false)
const shipments = ref<any[]>([])
const showCreateShipment = ref(false)
const packResult = ref<any>(null)
const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()

const shipForm = reactive({ warehouse_id: '', order_ids: '', carrier: '', tracking_number: '' })
const packForm = reactive({ wave_id: '', box_count: 1, packed_by: '' })

// The server's ShipmentStatus words, in the words the 仓管员 uses for them.
// The table used to render ``picked`` / ``packed`` to the clerk verbatim.
const SHIPMENT_STATUS: Record<string, { label: string; tag: 'success' | 'warning' | 'info' | 'primary' }> = {
  pending: { label: '待拣货', tag: 'info' },
  picked: { label: '已拣货', tag: 'primary' },
  packed: { label: '已打包', tag: 'primary' },
  shipped: { label: '已发货', tag: 'success' },
  delivered: { label: '已签收', tag: 'success' },
  cancelled: { label: '已取消', tag: 'info' },
}
const statusLabel = (s: string) => SHIPMENT_STATUS[s]?.label ?? s
const statusTag = (s: string) => SHIPMENT_STATUS[s]?.tag ?? 'warning'

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
    ElMessage.error(errText(e))
    shipments.value = []
  }
  loading.value = false
}

function resetShipForm() {
  shipForm.warehouse_id = ''; shipForm.order_ids = ''
  shipForm.carrier = ''; shipForm.tracking_number = ''
}

async function submitShipment() {
  shipCreating.value = true
  try {
    const orderIds = shipForm.order_ids.split('\n').map(s => s.trim()).filter(Boolean)
    const res = await apiClient.post('/warehouses/shipments', {
      warehouse_id: shipForm.warehouse_id,
      order_ids: orderIds,
      carrier: shipForm.carrier,
      tracking_number: shipForm.tracking_number,
    })
    // One shipment per order line, and the answer says how many: the dialog's
    // textarea can list five orders, and "创建成功" over five is not one.
    const count = res.data?.data?.count ?? orderIds.length
    ElMessage.success(`发货单创建成功：${count} 单`)
    showCreateShipment.value = false
    fetchShipments()
  } catch (e: any) {
    ElMessage.error(errText(e, '发货单创建失败'))
  }
  shipCreating.value = false
}

async function markShipped(row: any) {
  // The button sends no body — the tracking number belongs to the screen that
  // has it, and the record keeps the one it already carries.  A failure used
  // to go to console.warn alone, so 发货 on a cancelled row, a row already
  // shipped, or a row the server refuses looked exactly like a click that did
  // nothing.
  try {
    await apiClient.post(`/warehouses/shipments/${row.id}/ship`)
    ElMessage.success(`已发货：${row.shipment_no || row.id}`)
    fetchShipments()
  } catch (e: any) {
    ElMessage.error(errText(e, '发货失败'))
  }
}

async function submitPacking() {
  packLoading.value = true
  packResult.value = null
  try {
    const res = await apiClient.post('/warehouses/packing', {
      wave_id: packForm.wave_id,
      box_count: packForm.box_count,
      packed_by: packForm.packed_by,
    })
    packResult.value = res.data?.data ?? res.data
    ElMessage.success('打包记录成功')
  } catch (e: any) {
    ElMessage.error(errText(e, '打包记录失败'))
  }
  packLoading.value = false
}

onMounted(fetchShipments)
</script>
