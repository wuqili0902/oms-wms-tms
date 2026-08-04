<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>Webhooks</span>
          <el-button type="primary" @click="showCreate = true">新建 Webhook</el-button>
        </div>
      </template>
      <el-table :data="webhooks" stripe v-loading="loading">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="name" label="名称" width="180" />
        <el-table-column prop="url" label="回调URL" min-width="250" />
        <el-table-column prop="events" label="事件" width="160" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">{{ row.is_active ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button size="small" type="primary" link @click="editWebhook(row)">编辑</el-button>
            <el-button size="small" type="danger" link @click="deleteWebhook(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showEdit" title="编辑 Webhook" width="500px" destroy-on-close>
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="名称"><el-input v-model="editForm.name" /></el-form-item>
        <el-form-item label="回调URL"><el-input v-model="editForm.url" /></el-form-item>
        <el-form-item label="事件"><el-input v-model="editForm.events" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEdit = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCreate" title="新建 Webhook" width="500px" destroy-on-close>
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="createForm.name" />
        </el-form-item>
        <el-form-item label="回调URL">
          <el-input v-model="createForm.url" placeholder="https://example.com/webhook" />
        </el-form-item>
        <el-form-item label="事件">
          <el-input v-model="createForm.events" placeholder="用逗号分隔, 如: order.created,order.updated" />
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
import apiClient from '../../api'

const loading = ref(false)
const creating = ref(false)
const webhooks = ref<any[]>([])
const showCreate = ref(false)
const showEdit = ref(false)
const editing = ref(false)
const editForm = reactive({ id: '', name: '', url: '', events: '' })
const createForm = reactive({ name: '', url: '', events: '' })

async function fetchWebhooks() {
  loading.value = true
  try {
    const res = await apiClient.get('/webhooks?page=1&page_size=50')
    const body = res.data?.data ?? res.data ?? []
    webhooks.value = Array.isArray(body) ? body : (body.items ?? [])
  } catch (e: any) { webhooks.value = []; ElMessage.error(e?.response?.data?.detail ?? e.message) }
  loading.value = false
}

async function submitCreate() {
  creating.value = true
  try {
    await apiClient.post('/webhooks', createForm)
    ElMessage.success('Webhook 创建成功')
    showCreate.value = false
    fetchWebhooks()
    } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '创建失败') }
  creating.value = false
}

function editWebhook(row: any) {
  editForm.id = row.id; editForm.name = row.name
  editForm.url = row.url; editForm.events = row.events
  showEdit.value = true
}

async function submitEdit() {
  editing.value = true
  try {
    await apiClient.put(`/webhooks/${editForm.id}`, { name: editForm.name, url: editForm.url, events: editForm.events })
    ElMessage.success('更新成功')
    showEdit.value = false; fetchWebhooks()
    } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? '更新失败') }
  editing.value = false
}

async function deleteWebhook(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除 Webhook ${row.name}？`, '提示')
    await apiClient.delete(`/webhooks/${row.id}`)
    ElMessage.success('已删除')
    fetchWebhooks()
  } catch (e: any) {
    if (e?.response?.data?.detail) ElMessage.error(e.response.data.detail)
  }
}

onMounted(fetchWebhooks)
</script>
