<template>
  <div class="label-templates">
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>电子面单标签模板</span>
          <el-button type="primary" size="small" @click="openCreate">新建模板</el-button>
        </div>
      </template>
      <el-table :data="templates" stripe v-loading="loading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="carrier" label="快递公司" width="120">
          <template #default="{ row }"><el-tag>{{ row.carrier }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="format" label="格式" width="90">
          <template #default="{ row }"><el-tag :type="row.format === 'PDF' ? '' : 'warning'">{{ row.format }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="175" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="display:flex;justify-content:flex-end;margin-top:16px">
        <el-pagination
          v-model:page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEditing ? '编辑模板' : '新建模板'" width="550px" destroy-on-close @closed="resetForm">
      <el-form :model="form" label-width="100px">
        <el-form-item label="模板名称">
          <el-input v-model="form.name" placeholder="请输入模板名称" />
        </el-form-item>
        <el-form-item label="快递公司">
          <el-select v-model="form.carrier" style="width:100%" placeholder="请选择快递公司">
            <el-option label="顺丰速运" value="顺丰速运" />
            <el-option label="圆通速递" value="圆通速递" />
            <el-option label="中通快递" value="中通快递" />
            <el-option label="韵达快递" value="韵达快递" />
            <el-option label="京东物流" value="京东物流" />
            <el-option label="极兔速递" value="极兔速递" />
            <el-option label="其他" value="其他" />
          </el-select>
        </el-form-item>
        <el-form-item label="格式">
          <el-select v-model="form.format" style="width:100%" placeholder="请选择格式">
            <el-option label="PDF" value="PDF" />
            <el-option label="TIFF" value="TIFF" />
          </el-select>
        </el-form-item>
        <el-form-item label="模板文件">
          <el-upload
            :auto-upload="false"
            :limit="1"
            :on-exceed="() => ElMessage.warning('每次只能上传一个文件')"
            :on-change="onFileChange"
            accept=".pdf,.tif,.tiff"
          >
            <template #trigger>
              <el-button type="primary">选择文件</el-button>
            </template>
            <el-tag v-if="selectedFileName" type="info" style="margin-left:8px">{{ selectedFileName }}</el-tag>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import apiClient from '../../api'
import { usePagination } from '../../composables/usePagination'

const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()

const loading = ref(false)
const submitting = ref(false)
const templates = ref<any[]>([])
const dialogVisible = ref(false)
const isEditing = ref(false)
const editingId = ref<number | null>(null)
const selectedFile = ref<File | null>(null)
const selectedFileName = ref('')

const form = reactive({ name: '', carrier: '', format: 'PDF' })

function resetForm() {
  form.name = ''
  form.carrier = ''
  form.format = 'PDF'
  isEditing.value = false
  editingId.value = null
  selectedFile.value = null
  selectedFileName.value = ''
}

function openCreate() {
  resetForm()
  dialogVisible.value = true
}

function openEdit(row: any) {
  isEditing.value = true
  editingId.value = row.id
  form.name = row.name
  form.carrier = row.carrier
  form.format = row.format
  dialogVisible.value = true
}

function onFileChange(uploadFile: any) {
  selectedFile.value = uploadFile.raw
  selectedFileName.value = uploadFile.name
}

async function fetchTemplates() {
  loading.value = true
  try {
    const res = await apiClient.get('/label-templates', { params: { page: page.value, page_size: pageSize.value } })
    const data = res.data?.data ?? res.data
    templates.value = data?.items ?? data ?? []
    total.value = data?.total ?? 0
  } catch { templates.value = []; total.value = 0 }
  loading.value = false
}

async function handleSubmit() {
  submitting.value = true
  try {
    const payload = new FormData()
    payload.append('name', form.name)
    payload.append('carrier', form.carrier)
    payload.append('format', form.format)
    if (selectedFile.value) payload.append('file', selectedFile.value)

    if (isEditing.value && editingId.value) {
      await apiClient.put(`/label-templates/${editingId.value}`, payload, { headers: { 'Content-Type': 'multipart/form-data' } })
      ElMessage.success('模板更新成功')
    } else {
      await apiClient.post('/label-templates', payload, { headers: { 'Content-Type': 'multipart/form-data' } })
      ElMessage.success('模板创建成功')
    }
    dialogVisible.value = false
    fetchTemplates()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '操作失败') }
  submitting.value = false
}

function handleDelete(row: any) {
  ElMessageBox.confirm('确定删除该模板吗？此操作不可恢复。', '删除确认', { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }).then(async () => {
    try {
      await apiClient.delete(`/label-templates/${row.id}`)
      ElMessage.success('模板已删除')
      fetchTemplates()
    } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '删除失败') }
  }).catch(() => {})
}

onMounted(fetchTemplates)
</script>

<style scoped lang="scss">
.label-templates {
  padding: 16px;
}
</style>
