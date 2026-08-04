<template>
  <div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="生成条码" name="generate">
        <el-card>
          <el-form :model="genForm" label-width="120px" style="max-width:500px">
            <el-form-item label="GTIN 前缀" prop="gtin_prefix">
              <el-input v-model="genForm.gtin_prefix" placeholder="7-12位数字" />
            </el-form-item>
            <el-form-item label="实体类型">
              <el-select v-model="genForm.entity_type" style="width:100%">
                <el-option label="订单" value="order" />
                <el-option label="库存" value="inventory" />
                <el-option label="库位" value="location" />
                <el-option label="设备" value="device" />
              </el-select>
            </el-form-item>
            <el-form-item label="实体ID">
              <el-input v-model="genForm.entity_id" placeholder="实体UUID" />
            </el-form-item>
            <el-form-item label="格式">
              <el-select v-model="genForm.format" style="width:100%">
                <el-option label="EAN-13" value="ean13" />
                <el-option label="Code 128" value="code128" />
                <el-option label="QR Code" value="qr" />
                <el-option label="Data Matrix" value="datamatrix" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="genLoading" @click="generateBarcode">生成条码</el-button>
            </el-form-item>
          </el-form>
          <el-alert v-if="genResult?.gtin" type="success" :title="`条码生成成功: ${genResult.gtin}`" :description="`原始数据: ${genResult.raw_data}`" show-icon closable style="margin-top:12px" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="验证 GTIN" name="validate">
        <el-card>
          <el-form :model="validateForm" label-width="120px" style="max-width:500px">
            <el-form-item label="GTIN">
              <el-input v-model="validateForm.gtin" placeholder="8-14位数字" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="valLoading" @click="validateGtin">验证</el-button>
            </el-form-item>
          </el-form>
          <el-alert v-if="valResult !== null" :type="valResult ? 'success' : 'danger'" show-icon closable style="margin-top:12px">
            <template #title>{{ valResult ? 'GTIN 有效' : 'GTIN 无效' }}</template>
          </el-alert>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="扫描记录" name="scan">
        <el-card>
          <el-form :model="scanForm" label-width="120px" style="max-width:500px">
            <el-form-item label="扫描数据">
              <el-input v-model="scanForm.raw_data" placeholder="扫描枪数据" />
            </el-form-item>
            <el-form-item label="扫描器">
              <el-input v-model="scanForm.scanner_id" placeholder="扫描器ID（可选）" />
            </el-form-item>
            <el-form-item label="库位">
              <el-input v-model="scanForm.location_id" placeholder="库位ID（可选）" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="scanLoading" @click="submitScan">记录扫描</el-button>
            </el-form-item>
          </el-form>
          <el-alert v-if="scanResult" type="success" title="扫描记录成功" show-icon closable style="margin-top:12px" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="GTIN 查询" name="lookup">
        <el-card>
          <el-form :model="lookupForm" label-width="100px" style="max-width:500px">
            <el-form-item label="GTIN">
              <el-input v-model="lookupForm.gtin" placeholder="输入 GTIN 查询" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="lookupLoading" @click="lookupGtin">查询</el-button>
            </el-form-item>
          </el-form>
          <el-descriptions v-if="lookupResult" :column="2" border style="margin-top:12px">
            <el-descriptions-item label="GTIN">{{ lookupResult.gtin }}</el-descriptions-item>
            <el-descriptions-item label="实体类型">{{ lookupResult.entity_type }}</el-descriptions-item>
            <el-descriptions-item label="实体ID">{{ lookupResult.entity_id }}</el-descriptions-item>
            <el-descriptions-item label="格式">{{ lookupResult.format }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ lookupResult.created_at }}</el-descriptions-item>
          </el-descriptions>
          <el-empty v-if="lookupDone && !lookupResult" description="未找到该 GTIN" style="margin-top:12px" />
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="Excel 批量生成" name="excel">
        <el-card>
          <el-form label-width="120px" style="max-width:500px">
            <el-form-item label="Excel 文件">
              <el-upload
                :auto-upload="false"
                accept=".xlsx"
                :limit="1"
                :on-exceed="() => ElMessage.warning('每次只能上传一个文件')"
                :on-change="onFileChange"
              >
                <template #trigger>
                  <el-button type="primary">选择文件</el-button>
                </template>
              </el-upload>
            </el-form-item>
            <el-form-item>
              <el-button type="success" :loading="excelUploading" :disabled="!selectedFile" @click="uploadExcel">上传并生成条码</el-button>
            </el-form-item>
          </el-form>
          <el-alert v-if="excelResult" type="success" show-icon closable style="margin-top:12px">
            <template #title>生成成功！文件大小：{{ (excelResult.size / 1024).toFixed(1) }} KB</template>
          </el-alert>
          <el-button v-if="excelResult" type="primary" style="margin-top:12px" @click="downloadZip">下载 ZIP</el-button>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="标签模板" name="templates">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>标签模板</span>
              <el-button type="primary" size="small" @click="showCreateTemplate = true">新建模板</el-button>
            </div>
          </template>
          <el-table :data="templates" stripe v-loading="tmplLoading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column prop="name" label="名称" width="180" />
            <el-table-column prop="code" label="编码" width="120" />
            <el-table-column prop="format" label="格式" width="80" />
            <el-table-column label="尺寸" width="120">
              <template #default="{ row }">{{ row.width_mm }} × {{ row.height_mm }} mm</template>
            </el-table-column>
            <el-table-column label="默认" width="70">
              <template #default="{ row }">
                <el-tag v-if="row.is_default" size="small" type="success">是</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="175" />
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="showCreateTemplate" title="新建标签模板" width="550px" destroy-on-close>
      <el-form :model="tmplForm" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="tmplForm.name" placeholder="模板名称" />
        </el-form-item>
        <el-form-item label="编码">
          <el-input v-model="tmplForm.code" placeholder="唯一编码" />
        </el-form-item>
        <el-form-item label="格式">
          <el-select v-model="tmplForm.format" style="width:100%">
            <el-option label="ZPL" value="zpl" />
            <el-option label="EZPL" value="ezpl" />
          </el-select>
        </el-form-item>
        <el-form-item label="宽度(mm)">
          <el-input-number v-model="tmplForm.width_mm" :min="10" :max="200" style="width:100%" />
        </el-form-item>
        <el-form-item label="高度(mm)">
          <el-input-number v-model="tmplForm.height_mm" :min="10" :max="200" style="width:100%" />
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="tmplForm.is_default" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateTemplate = false">取消</el-button>
        <el-button type="primary" :loading="tmplCreating" @click="submitTemplate">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

const activeTab = ref('generate')

const genForm = reactive({ gtin_prefix: '6901234', entity_type: 'order', entity_id: '', format: 'ean13' })
const genLoading = ref(false)
const genResult = ref<any>(null)

const validateForm = reactive({ gtin: '' })
const valLoading = ref(false)
const valResult = ref<boolean | null>(null)

const scanForm = reactive({ raw_data: '', scanner_id: '', location_id: '' })
const scanLoading = ref(false)
const scanResult = ref(false)

const lookupForm = reactive({ gtin: '' })
const lookupLoading = ref(false)
const lookupResult = ref<any>(null)
const lookupDone = ref(false)

const selectedFile = ref<File | null>(null)
const excelUploading = ref(false)
const excelResult = ref<{ filename: string; size: number } | null>(null)

const tmplLoading = ref(false)
const tmplCreating = ref(false)
const templates = ref<any[]>([])
const showCreateTemplate = ref(false)
const tmplForm = reactive({ name: '', code: '', format: 'zpl', width_mm: 50, height_mm: 30, is_default: false })

async function generateBarcode() {
  genLoading.value = true
  genResult.value = null
  try {
    const res = await apiClient.post('/barcode/generate', genForm)
    genResult.value = res.data?.data ?? res.data
    ElMessage.success('条码生成成功')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '条码生成失败') }
  genLoading.value = false
}

async function validateGtin() {
  valLoading.value = true
  valResult.value = null
  try {
    const res = await apiClient.post('/barcode/validate', { gtin: validateForm.gtin })
    valResult.value = res.data?.data?.valid ?? res.data?.valid ?? false
  } catch (e: any) { console.warn('[barcode] validateGtin failed:', e?.response?.data ?? e); valResult.value = false }
  valLoading.value = false
}

async function submitScan() {
  scanLoading.value = true
  try {
    await apiClient.post('/barcode/scan', scanForm)
    scanResult.value = true
    ElMessage.success('扫描记录成功')
    scanForm.raw_data = ''
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '扫描记录失败') }
  scanLoading.value = false
}

async function lookupGtin() {
  lookupLoading.value = true; lookupResult.value = null; lookupDone.value = false
  try {
    const res = await apiClient.get(`/barcode/${lookupForm.gtin}`)
    lookupResult.value = res.data?.data ?? res.data
  } catch (e: any) { console.warn('[barcode] lookupGtin failed:', e?.response?.data ?? e); lookupResult.value = null }
  lookupDone.value = true
  lookupLoading.value = false
}

function onFileChange(uploadFile: any) {
  selectedFile.value = uploadFile.raw
}

async function uploadExcel() {
  if (!selectedFile.value) return
  excelUploading.value = true
  excelResult.value = null
  try {
    const form = new FormData()
    form.append('file', selectedFile.value)
    const res = await apiClient.post('/barcode/excel/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    excelResult.value = res.data ?? res.data?.data ?? res.data
    ElMessage.success('条码生成成功，请点击下载')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '上传失败') }
  excelUploading.value = false
}

async function downloadZip() {
  if (!excelResult.value) return
  try {
    const res = await apiClient.get(`/barcode/download/${excelResult.value.filename}`, { responseType: 'blob' })
    const blob = new Blob([res.data], { type: 'application/zip' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = excelResult.value.filename
    link.click()
    URL.revokeObjectURL(link.href)
  } catch {
    ElMessage.error('下载失败')
  }
}

async function fetchTemplates() {
  tmplLoading.value = true
  try {
    const res = await apiClient.get('/barcode/templates')
    templates.value = res.data?.data ?? res.data ?? []
  } catch (e: any) { console.warn('[barcode] fetchTemplates failed:', e?.response?.data ?? e); templates.value = [] }
  tmplLoading.value = false
}

async function submitTemplate() {
  tmplCreating.value = true
  try {
    await apiClient.post('/barcode/templates', tmplForm)
    ElMessage.success('模板创建成功')
    showCreateTemplate.value = false
    fetchTemplates()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '创建失败') }
  tmplCreating.value = false
}

onMounted(fetchTemplates)
</script>
