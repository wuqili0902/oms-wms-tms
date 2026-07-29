<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, type UploadProps } from 'element-plus'

const props = defineProps<{ endpoint: string; title: string }>()

const loading = ref(false)
const message = ref('')
const files = ref<File[]>([])

function parseResult(r: any): PromiseLike<{ success?: number; errors?: Array<any> }> {
  let d = r.data?.data ?? r.data ?? {}
  if (typeof d === 'string' && JSON.stringify(d).startsWith('{')) { d = JSON.parse(d) }
  return Promise.resolve({ success: d.success, errors: d.errors })
}

async function handleResult(r: any): Promise<void> {
  const res = await parseResult(r)
  message.value = `导入完成：${res.success ?? 0}条成功`
  if (Array.isArray(res.errors)) {
    for (const e of res.errors) { ElMessage.error(e.message || e) }
  } else if (res.errors && typeof res.errors === 'string') {
    ElMessage.warning(res.errors)
  }
}

function getEndpoint(file: File): string {
  return props.endpoint.replace('/orders', '/import/orders').replace('/inventory', '/import/inventory')
}

async function onChange({ file }: { file?: File }): Promise<void> {
  if (!file || !files.value.length) return
  const url = getEndpoint(file)
  loading.value = true
  try {
    await handleResult(await apiClient.post(url, {}, { headers: {'Content-Type': 'multipart/form-data'} }, { body: file }))
  } finally { loading.value = false }
}

// Stub upload handler for the "重新上传" button.
async function upload() {}

onMounted(() => {})
</script>

<template>
  <div>
    <el-card class="import-card">
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>{{ title }}</span>
          <el-button type="primary" @click="upload">重新上传</el-button>
        </div>
      </template>

      <!-- 拖拽上传区域 -->
      <el-upload drag :auto-upload="true" :on-change="onChange" :file-list="files">
        <el-icon class="upload-icon"><Upload /></el-icon>
        <template #tip>
          <div style="text-align:center">
            拖拽 CSV 文件到此处，或<br/>点击选择文件<br/><br/>
            <span v-if="message">{{ message }}</span>
          </div>
        </template>
      </el-upload>

    </el-card>
  </div>
</template>

<style scoped lang="scss">
.upload-icon { font-size: 64px; color: var(--el-color-primary); }
.import-card :deep(.el-upload-dragger) { padding: 48px; border: 2px dashed var(--el-border-color); }
.import-card :deep(.isDragging & .el-upload-dragger) { border-color: var(--el-color-warning); background:#fffbe6; }
</style>