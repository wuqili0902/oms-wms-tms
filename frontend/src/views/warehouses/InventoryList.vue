<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>库存管理</span>
          <div style="display:flex;gap:8px">
            <el-button type="success" @click="showStockIn = true">入库</el-button>
            <el-button type="warning" @click="openAdjust">库存调整</el-button>
          </div>
        </div>
      </template>

      <!-- Filters -->
      <el-form :inline="true" :model="filters" style="margin-bottom:16px">
        <el-form-item label="仓库">
          <el-select v-model="filters.warehouse_id" clearable filterable placeholder="选择仓库" @change="onFilterWarehouse()">
            <el-option v-for="wh in warehouses" :key="wh.id" :label="wh.name" :value="wh.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="SKU">
          <el-input v-model="filters.sku" placeholder="搜索 SKU" clearable @input="debouncedFetch()" />
        </el-form-item>
      </el-form>

      <!-- Table -->
      <!--
        These columns are the fields ``GET /warehouses/inventory`` answers
        (``InventoryResponse`` in ``src/wms/schemas.py``).  The table used to
        bind ``product_name``, ``location_name``, ``quantity_on_hand``,
        ``reorder_level`` and ``unit_price`` — no endpoint of this API returns
        any of those names, so every cell rendered empty and the low-stock
        highlight compared ``undefined`` with ``undefined``.
      -->
      <el-table :data="inventory" stripe v-loading="loading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="sku" label="SKU" width="150" sortable />
        <el-table-column label="仓库" width="140">
          <template #default="{ row }">{{ warehouseName(row.warehouse_id) }}</template>
        </el-table-column>
        <el-table-column prop="batch_no" label="批次" width="120">
          <template #default="{ row }">{{ row.batch_no || '-' }}</template>
        </el-table-column>
        <el-table-column prop="quantity" label="库存数量" width="100" />
        <el-table-column prop="available_qty" label="可用" width="90" />
        <el-table-column prop="reserved_qty" label="锁定" width="90" />
        <el-table-column prop="expiry_date" label="有效期" width="110">
          <template #default="{ row }">{{ row.expiry_date || '-' }}</template>
        </el-table-column>
        <el-table-column prop="updated_at" label="更新时间" width="175" />
      </el-table>

      <div style="display:flex;justify-content:flex-end;margin-top:12px">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50]" layout="total, sizes, prev, pager, next" @current-change="fetchInventory()" @size-change="fetchInventory()" />
      </div>
    </el-card>

    <!-- ═══ Stock In Dialog ═══ -->
    <el-dialog v-model="showStockIn" title="入库" width="700px" destroy-on-close @closed="resetStockInForm">
      <el-form :model="stockInForm" label-width="120px">
        <el-form-item label="采购单号">
          <el-select v-model="stockInForm.po_id" filterable clearable placeholder="选择采购单 (可选)">
            <el-option v-for="po in purchaseOrders" :key="po.id" :label="`${po.po_no} - ${po.vendor_name || ''}`" :value="po.po_no" />
          </el-select>
        </el-form-item>
        <el-form-item label="仓库">
          <el-select v-model="stockInForm.warehouse_id" filterable placeholder="选择仓库">
            <el-option v-for="wh in warehouses" :key="wh.id" :label="wh.name" :value="wh.id" />
          </el-select>
        </el-form-item>

        <!-- Dynamic item rows -->
        <div style="margin-bottom:8px;font-weight:bold">入库商品</div>
        <el-table :data="stockInForm.items" size="small" border style="width:100%">
          <el-table-column prop="sku" label="SKU" min-width="120">
            <template #default="{ row, $index }">
              <el-select v-model="row._selected_sku" @change="(val: any) => onSkuSelect($index, val)">
                <el-option v-for="p in products" :key="p.sku" :label="`${p.sku} - ${p.name}`" :value="p.sku" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="数量" width="150">
            <template #default="{ row }">
              <el-input-number v-model="row.quantity" :min="1" style="width:100%" />
            </template>
          </el-table-column>
          <el-table-column label="" width="40">
            <template #default="{ $index }">
              <el-button size="small" type="danger" link @click="removeStockInItem($index)">✕</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button type="primary" text @click="addStockInItem" style="margin-top:8px">+ 添加商品</el-button>
      </el-form>

      <!-- Preview -->
      <div style="margin:16px 0;padding:8px;background:#f5f7fa;border-radius:4px">
        <div style="font-weight:bold;margin-bottom:8px">入库预览</div>
        <template v-for="(item, idx) in stockInForm.items" :key="idx">
          <span>{{ item.sku }} × {{ item.quantity }}</span>
          <br v-if="idx < stockInForm.items.length - 1" />
        </template>
      </div>

      <template #footer>
        <el-button @click="showStockIn = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitStockIn">提交入库</el-button>
      </template>
    </el-dialog>

    <!-- ═══ Stock Adjust Dialog ═══ -->
    <!--
      ``POST /warehouses/inventory/adjust`` (``InventoryAdjust``) adjusts a SKU on
      a location of a warehouse.  The dialog used to collect an inventory-row id
      and a ``quantity_change`` and post them to ``/inventory/adjust`` — a path
      the API does not mount, so 提交调整 was a 404 on every press.
    -->
    <el-dialog v-model="showAdjustDialog" title="库存调整" width="560px" destroy-on-close @closed="resetAdjustForm">
      <el-form :model="adjustForm" label-width="120px">
        <el-form-item label="仓库">
          <el-select v-model="adjustForm.warehouse_id" filterable placeholder="选择仓库" @change="onAdjustWarehouse()">
            <el-option v-for="wh in warehouses" :key="wh.id" :label="wh.name" :value="wh.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="库位">
          <el-select v-model="adjustForm.location_id" filterable :disabled="!adjustForm.warehouse_id" placeholder="选择库位">
            <el-option
              v-for="loc in adjustLocations"
              :key="loc.id"
              :label="loc.location_code || `${loc.zone}-${loc.aisle}-${loc.shelf}-${loc.bin}`"
              :value="loc.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="SKU">
          <el-input v-model="adjustForm.sku" placeholder="商品编码，如 SKU-A001" />
        </el-form-item>
        <el-form-item label="变化数量">
          <el-input-number v-model="adjustForm.quantity" :precision="2" :step="1" style="width:100%" />
          <div style="color:#909399;font-size:12px">正数为盘盈入库，负数为盘亏出库；0 不会被接受</div>
        </el-form-item>
        <el-form-item label="原因">
          <el-select v-model="adjustForm.reason" filterable allow-create placeholder="选择或填写原因">
            <el-option label="盘盈" value="FOUND" />
            <el-option label="盘亏" value="COUNT_ERROR" />
            <el-option label="损耗/报废" value="DAMAGE" />
            <el-option label="过期" value="EXPIRED" />
            <el-option label="丢失" value="LOST" />
          </el-select>
        </el-form-item>
        <el-form-item label="批次">
          <el-input v-model="adjustForm.batch_no" placeholder="批次号 (可选，出库时留空则按策略自动选批)" />
        </el-form-item>
        <el-form-item label="出库选批">
          <el-radio-group v-model="adjustForm.picking_strategy">
            <el-radio-button value="fefo">先到期先出</el-radio-button>
            <el-radio-button value="fifo">先入库先出</el-radio-button>
            <el-radio-button value="batch">指定批次</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showAdjustDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitAdjust">提交调整</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'
import { getInventory, adjustStock, createStockIn, getLocations } from '../../services/inventory'
import { errText } from '../../api/errors'

const warehouses = ref<any[]>([])
const products = ref<any[]>([
  // Pre-populated with sample SKUs for the picker demo; real data would come from API
])
const purchaseOrders = ref<any[]>([])
const inventory = ref<any[]>([])
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const showStockIn = ref(false)
const showAdjustDialog = ref(false)
const submitting = ref(false)

// Filters
const filters = reactive({ warehouse_id: '', sku: '' })
let fetchTimer: ReturnType<typeof setTimeout> | undefined = undefined
function debouncedFetch() { clearTimeout(fetchTimer); fetchTimer = setTimeout(fetchInventory, 300) }

function warehouseName(id: string) {
  return warehouses.value.find((w) => w.id === id)?.name ?? id
}

async function fetchWarehouses() {
  try {
    const res = await apiClient.get('/warehouses')
    warehouses.value = (res.data?.data ?? res.data)?.items ?? res.data ?? []
  } catch (e: any) {
    ElMessage.error(errText(e))
  }
}

async function fetchPurchaseOrders() {
  try {
    const res = await apiClient.get('/warehouses/purchase-orders?page=1&page_size=50&status=approved')
    purchaseOrders.value = (res.data?.data ?? res.data)?.items ?? []
  } catch (e: any) {
    ElMessage.error(errText(e))
  }
}

async function fetchInventory() {
  loading.value = true
  try {
    const params: Record<string, string> = {}
    if (filters.warehouse_id) params.warehouse_id = filters.warehouse_id
    if (filters.sku) params.sku = filters.sku
    const res = await getInventory(params)
    const rows = res.data?.data ?? res.data ?? []
    inventory.value = Array.isArray(rows) ? rows : []
    total.value = inventory.value.length
  } catch (e: any) {
    ElMessage.error(errText(e))
    inventory.value = []
  }
  loading.value = false
}

function onFilterWarehouse() { fetchInventory() }

// ═══ Stock In helpers ══════════════════════════════════════

const stockInForm = reactive({ po_id: '', warehouse_id: '', items: [] as any[], remark: '' })

function resetStockInForm() { stockInForm.po_id = ''; stockInForm.warehouse_id = ''; stockInForm.items = []; stockInForm.remark = '' }
function addStockInItem() { stockInForm.items.push({ _selected_sku: '', sku: '', quantity: 1 }); fetchWarehouses(); fetchPurchaseOrders() }
function removeStockInItem(idx: number) { stockInForm.items.splice(idx, 1) }
function onSkuSelect(idx: number, val: any) {
  const item = stockInForm.items[idx]
  if (!item) return
  item.sku = val
}

async function submitStockIn() {
  submitting.value = true
  try {
    // Deduplicate items with same SKU (sum quantities)
    const deduped: Record<string, number> = {}
    for (const it of stockInForm.items) { if (it.sku) deduped[it.sku] = (deduped[it.sku] ?? 0) + it.quantity }
    const lines = Object.entries(deduped).map(([sku, qty]) => ({ sku, qty }))

    // ref_no is the external document number; po_id names no column and the
    // server refuses an undeclared key by name now rather than dropping it.
    await createStockIn({
      warehouse_id: stockInForm.warehouse_id,
      ref_no: stockInForm.po_id || undefined,
      lines,
    })
    ElMessage.success('入库成功')
    showStockIn.value = false
    fetchInventory()
  } catch (e: any) {
    ElMessage.error(errText(e, '入库失败'))
  } finally { submitting.value = false }
}

// ═══ Stock Adjust helpers ═══════════════════════════════════

const adjustForm = reactive({
  warehouse_id: '', location_id: '', sku: '', quantity: 0,
  reason: '', batch_no: '', picking_strategy: 'fefo' as 'fefo' | 'fifo' | 'batch',
})
const adjustLocations = ref<any[]>([])

function openAdjust() {
  adjustForm.warehouse_id = filters.warehouse_id || ''
  if (adjustForm.warehouse_id) onAdjustWarehouse()
  showAdjustDialog.value = true
}
function resetAdjustForm() {
  adjustForm.warehouse_id = ''; adjustForm.location_id = ''; adjustForm.sku = ''
  adjustForm.quantity = 0; adjustForm.reason = ''; adjustForm.batch_no = ''
  adjustForm.picking_strategy = 'fefo'
  adjustLocations.value = []
}

async function onAdjustWarehouse() {
  adjustForm.location_id = ''
  adjustLocations.value = []
  if (!adjustForm.warehouse_id) return
  try {
    const res = await getLocations(adjustForm.warehouse_id)
    const body = res.data?.data ?? res.data ?? {}
    adjustLocations.value = body.items ?? []
  } catch (e: any) {
    ElMessage.error(errText(e, '库位加载失败'))
  }
}

async function submitAdjust() {
  if (!adjustForm.warehouse_id || !adjustForm.location_id) {
    ElMessage.warning('请选择仓库和库位')
    return
  }
  if (!adjustForm.sku) {
    ElMessage.warning('请填写 SKU')
    return
  }
  if (adjustForm.quantity === 0) {
    ElMessage.warning('变化数量不能为 0')
    return
  }
  submitting.value = true
  try {
    await adjustStock({
      warehouse_id: adjustForm.warehouse_id,
      location_id: adjustForm.location_id,
      sku: adjustForm.sku,
      quantity: adjustForm.quantity,
      reason: adjustForm.reason || undefined,
      batch_no: adjustForm.batch_no || undefined,
      picking_strategy: adjustForm.picking_strategy,
    })
    ElMessage.success('库存调整成功')
    showAdjustDialog.value = false
    fetchInventory()
  } catch (e: any) {
    ElMessage.error(errText(e, '库存调整失败'))
  } finally { submitting.value = false }
}

onMounted(() => { fetchWarehouses(); fetchPurchaseOrders(); fetchInventory() })
</script>
