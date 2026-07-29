<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>供应商管理</span>
          <el-button type="primary" @click="showCreate = true">新建供应商</el-button>
        </div>
      </template>
      <el-table :data="vendors" stripe v-loading="loading" style="width:100%">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="code" label="编码" width="120" />
        <el-table-column prop="name" label="名称" width="180" />
        <el-table-column prop="contact" label="联系人" width="120" />
        <el-table-column prop="phone" label="电话" width="140" />
        <el-table-column prop="email" label="邮箱" min-width="180" />
        <el-table-column prop="created_at" label="创建时间" width="175" />
      </el-table>
      <div style="display:flex;justify-content:flex-end;margin-top:12px">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="onPageChange" @size-change="onSizeChange" />
      </div>
    </el-card>

    <el-dialog v-model="showCreate" title="新建供应商" width="500px" destroy-on-close @closed="resetCreateForm">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="编码">
          <el-input v-model="createForm.code" placeholder="唯一编码" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="createForm.name" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="createForm.contact" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="createForm.phone" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="createForm.email" />
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
import { ElMessage } from 'element-plus'
import { usePagination } from '../../composables/usePagination'
import apiClient from '../../api'

const loading = ref(false)
const creating = ref(false)
const vendors = ref<any[]>([])
const showCreate = ref(false)
const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()
const createForm = reactive({ code: '', name: '', contact: '', phone: '', email: '' })

async function fetchVendors() {
  loading.value = true
  try {
    const res = await apiClient.get(`/warehouses/vendors?page=${page.value}&page_size=${pageSize.value}`)
    const d = res.data?.data ?? res.data ?? []
    let items
    if (Array.isArray(d)) { items = d; total.value = d.length }
    else { items = d.items ?? []; total.value = d.total ?? d.items?.length ?? 0 }
    vendors.value = items
  } catch { vendors.value = [] }
  loading.value = false
}

function resetCreateForm() { Object.assign(createForm, { code: '', name: '', contact: '', phone: '', email: '' }) }

async function submitCreate() {
  creating.value = true
  try {
    await apiClient.post('/warehouses/vendors', createForm)
    ElMessage.success('创建成功')
    showCreate.value = false
    fetchVendors()
  } catch { /* ignore */ }
  creating.value = false
}

onMounted(fetchVendors)
</script>
