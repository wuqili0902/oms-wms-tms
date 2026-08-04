<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

interface BatchItem {
  order_id: string
  recipient_name: string
  recipient_phone: string
  recipient_address: string
  carrier_code: string
  tracking?: string
  status?: string
}

const carriers = [
  { value: 'sf', label: '顺丰速运' },
  { value: 'zto', label: '中通快递' },
  { value: 'yto', label: '圆通速递' },
  { value: 'sto', label: '申通快递' },
  { value: 'yunda', label: '韵达快递' },
  { value: 'ems', label: 'EMS邮政' },
  { value: 'jd', label: '京东物流' },
]

const items = ref<BatchItem[]>([])
const loading = ref(false)
const printing = ref(false)

function addRow() {
  items.value.push({
    order_id: '',
    recipient_name: '',
    recipient_phone: '',
    recipient_address: '',
    carrier_code: '',
  })
}

function removeRow(index: number) {
  items.value.splice(index, 1)
}

function handleCsvUpload(file: File) {
  const reader = new FileReader()
  reader.onload = (e) => {
    const text = e.target?.result as string
    if (!text) { ElMessage.warning('文件为空'); return }

    const lines = text.split(/\r?\n/).filter(Boolean)
    if (lines.length < 2) { ElMessage.warning('CSV 至少需要标题行和一行数据'); return }

    const headers = lines[0].split(',').map(h => h.trim().toLowerCase().replace(/^["']|["']$/g, ''))
    const orderIdx = headers.findIndex(h => h.includes('订单') || h === 'order_id' || h === 'order')
    const nameIdx = headers.findIndex(h => h.includes('收件') || h.includes('姓名') || h === 'recipient_name' || h === 'name')
    const phoneIdx = headers.findIndex(h => h.includes('电话') || h.includes('手机') || h === 'recipient_phone' || h === 'phone')
    const addrIdx = headers.findIndex(h => h.includes('地址') || h === 'recipient_address' || h === 'address')
    const carrierIdx = headers.findIndex(h => h.includes('承运') || h.includes('快递') || h === 'carrier_code' || h === 'carrier')

    if (orderIdx === -1) { ElMessage.warning('CSV 缺少订单号列'); return }
    if (nameIdx === -1) { ElMessage.warning('CSV 缺少收件人列'); return }
    if (addrIdx === -1) { ElMessage.warning('CSV 缺少地址列'); return }

    const parsed: BatchItem[] = []
    for (let i = 1; i < lines.length; i++) {
      const cols = parseCsvLine(lines[i])
      const item: BatchItem = {
        order_id: cols[orderIdx]?.trim() || '',
        recipient_name: cols[nameIdx]?.trim() || '',
        recipient_phone: cols[phoneIdx]?.trim() || '',
        recipient_address: cols[addrIdx]?.trim() || '',
        carrier_code: carrierIdx !== -1 ? (cols[carrierIdx]?.trim() || '') : '',
      }
      if (item.order_id && item.recipient_name) {
        parsed.push(item)
      }
    }

    if (!parsed.length) { ElMessage.warning('未解析到有效数据'); return }

    items.value = parsed
    ElMessage.success(`成功导入 ${parsed.length} 条记录`)
  }
  reader.readAsText(file)
}

function parseCsvLine(line: string): string[] {
  const result: string[] = []
  let current = ''
  let inQuotes = false
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]
    if (ch === '"') {
      inQuotes = !inQuotes
    } else if (ch === ',' && !inQuotes) {
      result.push(current)
      current = ''
    } else {
      current += ch
    }
  }
  result.push(current)
  return result
}

async function createAllWaybills() {
  const valid = items.value.filter(i => i.order_id && i.recipient_name && i.recipient_address)
  if (!valid.length) {
    ElMessage.warning('请至少填写一个有效的运单')
    return
  }
  loading.value = true
  try {
    const results = await Promise.allSettled(
      valid.map(item =>
        apiClient.post('/logistics/waybill/create', {
          order_id: item.order_id,
          recipient_name: item.recipient_name,
          recipient_phone: item.recipient_phone,
          recipient_address: item.recipient_address,
          carrier_code: item.carrier_code || 'zto',
        })
      )
    )
    for (let i = 0; i < results.length; i++) {
      const r = results[i]
      if (r.status === 'fulfilled') {
        const d = r.value.data?.data ?? r.value.data ?? {}
        items.value[i].tracking = d.tracking_number
        items.value[i].status = 'success'
      } else {
        items.value[i].status = 'failed'
      }
    }
    ElMessage.success(`成功创建 ${results.filter(r => r.status === 'fulfilled').length} / ${results.length} 个面单`)
  } catch (e: any) {
    ElMessage.error('批量下单失败: ' + (e?.response?.data?.detail ?? e.message))
  } finally {
    loading.value = false
  }
}

async function batchPrint() {
  const trackings = items.value.filter(i => i.tracking).map(i => i.tracking!)
  if (!trackings.length) {
    ElMessage.warning('没有可打印的面单')
    return
  }
  printing.value = true
  try {
    const calls = trackings.map(t => apiClient.post(`/logistics/waybill/${t}/print`))
    const results = await Promise.allSettled(calls)
    const urls: string[] = []
    for (const r of results) {
      if (r.status === 'fulfilled') {
        const url = r.value.data?.print_callback_url ?? r.value.data?.data?.print_callback_url
        if (url) urls.push(url)
      }
    }
    if (urls.length) {
      urls.forEach(url => window.open(url, '_blank'))
      ElMessage.success(`已打开 ${urls.length} 个打印页面`)
    } else {
      ElMessage.warning('未获取到打印回调地址')
    }
  } catch (e: any) {
    ElMessage.error('批量打印失败: ' + (e?.response?.data?.detail ?? e.message))
  } finally {
    printing.value = false
  }
}

function downloadTemplate() {
  const csv = 'order_id,recipient_name,recipient_phone,recipient_address,carrier_code\nORD001,张三,13800138000,上海市浦东新区,zto\nORD002,李四,13900139000,北京市朝阳区,sf'
  const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '批量打单模板.csv'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="batch-print">
    <el-card>
      <template #header>
        <span>批量打单</span>
      </template>

      <el-alert title="支持逐行填写或导入 CSV 文件批量创建电子面单" type="info" :closable="false" />

      <div class="upload-area">
        <el-upload
          accept=".csv"
          :show-file-list="false"
          :auto-upload="false"
          :on-change="(u: any) => handleCsvUpload(u.raw)"
        >
          <el-button type="primary" plain>
            <el-icon style="margin-right:4px"><Upload /></el-icon>
            导入 CSV
          </el-button>
        </el-upload>
        <el-button text type="primary" @click="downloadTemplate">下载模板</el-button>
      </div>

      <div class="toolbar">
        <el-button type="primary" @click="addRow">添加行</el-button>
        <el-button type="success" :loading="loading" @click="createAllWaybills" :disabled="!items.length">批量下单</el-button>
        <el-button type="warning" :loading="printing" @click="batchPrint" :disabled="!items.some(i => i.tracking)">批量打印</el-button>
      </div>

      <el-table :data="items" border v-loading="loading" max-height="600">
        <el-table-column type="index" width="50" />
        <el-table-column label="订单号" min-width="140">
          <template #default="{ row }">
            <el-input v-model="row.order_id" placeholder="订单号" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="收件人" min-width="100">
          <template #default="{ row }">
            <el-input v-model="row.recipient_name" placeholder="姓名" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="电话" min-width="120">
          <template #default="{ row }">
            <el-input v-model="row.recipient_phone" placeholder="手机号" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="地址" min-width="200">
          <template #default="{ row }">
            <el-input v-model="row.recipient_address" placeholder="详细地址" size="small" />
          </template>
        </el-table-column>
        <el-table-column label="承运商" width="120">
          <template #default="{ row }">
            <el-select v-model="row.carrier_code" placeholder="选择承运商" size="small" clearable>
              <el-option v-for="c in carriers" :key="c.value" :label="c.label" :value="c.value" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="面单号" width="160">
          <template #default="{ row }">
            <span v-if="row.tracking" class="tracking-cell">{{ row.tracking }}</span>
            <el-tag v-else-if="row.status === 'failed'" type="danger" size="small">失败</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="60" fixed="right">
          <template #default="{ $index }">
            <el-button text type="danger" size="small" @click="removeRow($index)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无数据" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped lang="scss">
.batch-print { padding: 16px; }
.upload-area { display: flex; align-items: center; gap: 8px; margin: 12px 0; }
.toolbar { display: flex; gap: 8px; margin: 16px 0; }
.tracking-cell { font-family: monospace; font-size: 12px; color: var(--el-color-primary); }
</style>
