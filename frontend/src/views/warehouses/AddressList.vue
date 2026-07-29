<template>
  <div>
    <el-card>
      <template #header>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span>地址管理</span>
          <el-button type="primary" @click="showCreate = true">新建地址</el-button>
        </div>
      </template>
      <el-table :data="addresses" stripe v-loading="loading" style="width:100%">
        <template #empty><el-empty description="暂无数据" /></template>
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="code" label="编码" width="120" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="type" label="类型" width="80">
          <template #default="{ row }"><StatusTag :type="row.type" /></template>
        </el-table-column>
        <el-table-column prop="province" label="省份" width="100" />
        <el-table-column prop="city" label="城市" width="100" />
        <el-table-column prop="full_address" label="详细地址" min-width="200" show-overflow-tooltip />
        <el-table-column prop="contact" label="联系人" width="100" />
        <el-table-column prop="phone" label="电话" width="130" />
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button link type="primary" @click="edit(row)">编辑</el-button>
            <el-button link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div style="display:flex;justify-content:flex-end;margin-top:12px">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[10,20,50,100]" layout="total, sizes, prev, pager, next" @current-change="onPageChange" @size-change="onSizeChange" />
      </div>
    </el-card>

    <el-dialog v-model="showCreate" title="新建地址" width="500px" destroy-on-close @closed="resetForm">
      <el-form :model="form" label-width="90px">
        <el-form-item label="编码">
          <el-input v-model.trim="form.code" placeholder="唯一编码（留空自动生成）" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width:100%">
            <el-option label="供应商地址" value="supplier" />
            <el-option label="仓库地址" value="warehouse" />
            <el-option label="发货地址" value="ship_from" />
            <el-option label="收货地址" value="ship_to" />
          </el-select>
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="地址名称" />
        </el-form-item>
        <el-row :gutter="10">
          <el-col :span="12"><el-form-item label="省份"><el-input v-model="form.province" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="城市"><el-input v-model="form.city" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="详细地址">
          <el-input v-model="form.full_address" type="textarea" rows="3" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="form.contact" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" placeholder="手机号/固话" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 编辑对话框：复用创建表单，仅改变标题 -->
    <el-dialog v-model="showEdit" title="编辑地址" width="500px" destroy-on-close @closed="resetForm">
      <el-form :model="form" label-width="90px">
        <el-form-item label="编码">
          <el-input v-model.trim="form.code" placeholder="唯一编码" disabled />
        </el-form-item>
        <el-row :gutter="10">
          <el-col :span="12"><el-form-item label="省份"><el-input v-model="form.province" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="城市"><el-input v-model="form.city" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="showEdit = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { usePagination } from '../../composables/usePagination'
import apiClient from '../../api'
import { StatusTag } from '@/components/StatusTag.vue'

const loading = ref(false)
const saving = ref(false)
const addresses = ref<any[]>([])
const showCreate = ref(false)
const showEdit = ref(false)
const { page, pageSize, total, onPageChange, onSizeChange } = usePagination()
const form = reactive({ code: '', type: 'supplier' as string, name: '', province: '', city: '', full_address: '', contact: '', phone: '' })

async function fetchAddresses() {
  loading.value = true
  try {
    const res = await apiClient.get(`/warehouses/addresses?page=${page.value}&page_size=${pageSize.value}`)
    const d = res.data?.data ?? res.data ?? []
    let items
    if (Array.isArray(d)) { items = d; total.value = d.length }
    else { items = d.items ?? []; total.value = d.total ?? d.items?.length ?? 0 }
    addresses.value = items
  } catch { addresses.value = [] }
  loading.value = false
}

function resetForm() { Object.assign(form, { code: '', type: 'supplier', name: '', province: '', city: '', full_address: '', contact: '', phone: '' }) }

async function submit() {
  saving.value = true
  try {
    await apiClient.post('/warehouses/addresses', form)
    ElMessage.success('保存成功')
    showCreate.value ? (showCreate.value = false, fetchAddresses()) : ((showEdit.value = false), fetchAddresses())
  } catch { /* ignore */ }
  saving.value = false
}

function edit(row: any) { showEdit.value = true; Object.assign(form, row) }

async function handleDelete(row: any) {
  const ok = await confirmDelete(row)
  if (!ok) return
  try {
    await apiClient.delete(`/warehouses/addresses/${row.id}`)
    ElMessage.success('删除成功')
    fetchAddresses()
  } catch { /* ignore */ }
}

async function confirmDelete(row: any) {
  const ok = await confirm(`确认删除地址"${row.name}"？`)
  if (ok === false) return false
  return true
}

onMounted(fetchAddresses)
</script>