<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>库存管理</span>
          <div style="display:flex;gap:8px">
            <el-button type="success" @click="showStockIn = true">入库</el-button>
            <el-button type="warning" @click="showAdjustDialog = true">库存调整</el-button>
          </div>
        </div>
      </template>

      <!-- Filters -->
      <el-form :inline="true" :model="filters" style="margin-bottom:16px">
        <el-form-item label="仓库">
          <el-select v-model="filters.warehouse_id" clearable filterable placeholder="选择仓库" @change="fetchInventory()">
            <el-option v-for="wh in warehouses" :key="wh.id" :label="wh.name" :value="wh.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="SKU">
          <el-input v-model="filters.sku" placeholder="搜索 SKU" clearable @input="debouncedFetch()" />
        </el-form-item>
      </el-form>

      <!-- Stock In / Stock Out Actions -->
      <div style="margin-bottom:16px;display:flex;gap:8px">
        <el-button type="success" @click="showStockIn = true">入库</el-button>
        <el-button type="warning" @click="showAdjustDialog = true">库存调整</el-button>
      </div>

      <!-- Table -->
      <el-table :data="inventory" stripe v-loading="loading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="sku" label="SKU" width="120" sortable />
        <el-table-column prop="product_name" label="产品名称" min-width="160" />
        <el-table-column prop="warehouse_name" label="仓库" width="120" />
        <el-table-column prop="location_name" label="库位" width="120" />
        <el-table-column prop="quantity_on_hand" label="现有库存" width="100">
          <template #default="{ row }">
            <span :style="{ color: (row.quantity_on_hand ?? 0) <= row.reorder_level ? '#f56c6c' : '' }">
              {{ row.quantity_on_hand ?? '-' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="unit_price" label="单价" width="100">
          <template #default="{ row }">¥{{ Number(row.unit_price||0).toFixed(2) }}</template>
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
        <el-form-item label="采购单ID">
          <el-select v-model="stockInForm.po_id" filterable placeholder="选择采购单 (可选)">
            <el-option v-for="po in purchaseOrders" :key="po.id" :label="`${po.po_no} - ${po.vendor_name || ''}`" :value="po.id" />
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

        <el-form-item label="备注">
          <el-input v-model="stockInForm.remark" type="textarea" :rows="2" />
        </el-form-item>
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
    <el-dialog v-model="showAdjustDialog" title="库存调整" width="500px" destroy-on-close @closed="resetAdjustForm">
      <el-form :model="adjustForm" label-width="120px">
        <el-form-item label="商品ID">
          <el-input v-model="adjustForm.item_id" placeholder="输入库存记录 ID" />
        </el-form-item>
        <el-form-item label="变化数量">
          <el-input-number v-model="adjustForm.quantity_change" :precision="0" style="width:100%" />
        </el-form-item>
        <el-form-item label="原因">
          <el-select v-model="adjustForm.reason_code" filterable placeholder="选择调整原因">
            <el-option label="盘点差异" value="COUNT_DIFF" />
            <el-option label="损耗/报废" value="DAMAGE" />
            <el-option label="退货入库" value="RETURN_IN" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="adjustForm.remark" type="textarea" :rows="2" />
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
import { getInventory, adjustStock, createStockIn } from '../../services/inventory'

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

async function fetchWarehouses() {
  try {
    const res = await apiClient.get('/warehouses')
    warehouses.value = (res.data?.data ?? res.data)?.items ?? []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
}

async function fetchPurchaseOrders() {
  try {
    const res = await apiClient.get('/warehouses/purchase-orders?page=1&page_size=50&status=approved')
    purchaseOrders.value = (res.data?.data ?? res.data)?.items ?? []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
}

async function fetchInventory() {
  loading.value = true
  try {
    const params: Record<string, string> = {}
    if (filters.warehouse_id) params.warehouse_id = filters.warehouse_id
    if (filters.sku) params.sku = filters.sku
    const res = await getInventory(params)
    inventory.value = res.data?.data ?? res.data ?? []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
    inventory.value = []
  }
  loading.value = false
}

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
    const items = Object.entries(deduped).map(([sku, quantity]) => ({ sku, quantity }))

    await createStockIn({ warehouse_id: stockInForm.warehouse_id, po_id: stockInForm.po_id || undefined, items })
    ElMessage.success('入库成功')
    showStockIn.value = false
    fetchInventory()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? '入库失败')
  } finally { submitting.value = false }
}

// ═══ Stock Adjust helpers ═══════════════════════════════════

const adjustForm = reactive({ item_id: '', quantity_change: 0, reason_code: '', remark: '' })
function resetAdjustForm() { adjustForm.item_id = ''; adjustForm.quantity_change = 0; adjustForm.reason_code = ''; adjustForm.remark = '' }

async function submitAdjust() {
  submitting.value = true
  try {
    await adjustStock({ item_id: adjustForm.item_id, quantity_change: adjustForm.quantity_change, reason: adjustForm.reason_code })
    ElMessage.success('库存调整成功')
    showAdjustDialog.value = false
    fetchInventory()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? '库存调整失败')
  } finally { submitting.value = false }
}

onMounted(() => { fetchWarehouses(); fetchPurchaseOrders(); fetchInventory() })
</script>
