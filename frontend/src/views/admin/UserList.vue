<template>
  <div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="用户管理" name="users">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>用户列表</span>
              <el-button type="primary" size="small" @click="showCreateUser = true">新建用户</el-button>
            </div>
          </template>
          <el-table :data="users" stripe v-loading="loading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="username" label="用户名" width="140" />
            <el-table-column prop="email" label="邮箱" width="200" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
                  {{ row.is_active ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="175" />
            <el-table-column label="操作" width="280">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="assignRole(row)">分配角色</el-button>
                <el-button size="small" type="danger" link @click="removeRole(row)">移除角色</el-button>
                <el-button size="small" :type="row.is_active ? 'warning' : 'success'" link @click="toggleUser(row)">
                  {{ row.is_active ? '停用' : '启用' }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="角色管理" name="roles">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>角色列表</span>
              <el-button type="primary" size="small" @click="showCreateRole = true">新建角色</el-button>
            </div>
          </template>
          <el-table :data="roles" stripe v-loading="roleLoading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="name" label="名称" width="150" />
            <el-table-column prop="code" label="编码" width="120" />
            <el-table-column prop="description" label="描述" min-width="200" />
            <el-table-column label="系统角色" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.is_system" size="small" type="warning">系统</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220">
              <template #default="{ row }">
                <el-button size="small" type="primary" link @click="assignPerm(row)">分配权限</el-button>
                <el-button size="small" type="primary" link :disabled="row.is_system" @click="editRole(row)">编辑</el-button>
                <el-button size="small" type="danger" link :disabled="row.is_system" @click="deleteRole(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="权限管理" name="perms">
        <el-card>
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>权限列表</span>
              <el-button type="primary" size="small" @click="showCreatePerm = true">新建权限</el-button>
            </div>
          </template>
          <el-table :data="permissions" stripe v-loading="permLoading">
            <template #empty><el-empty description="暂无数据" /></template>
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="name" label="名称" width="150" />
            <el-table-column prop="code" label="编码" width="150" />
            <el-table-column prop="resource" label="资源" width="120" />
            <el-table-column prop="action" label="操作" width="100" />
            <el-table-column prop="description" label="描述" min-width="200" />
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="showCreateUser" title="新建用户" width="500px" destroy-on-close>
      <el-form :model="userForm" label-width="100px" :rules="userRules" ref="userFormRef">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="userForm.username" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="userForm.email" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="userForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateUser = false">取消</el-button>
        <el-button type="primary" :loading="userCreating" @click="submitUser">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCreateRole" title="新建角色" width="500px" destroy-on-close>
      <el-form :model="roleForm" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="roleForm.name" />
        </el-form-item>
        <el-form-item label="编码">
          <el-input v-model="roleForm.code" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="roleForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateRole = false">取消</el-button>
        <el-button type="primary" :loading="roleCreating" @click="submitRole">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showEditRole" title="编辑角色" width="500px" destroy-on-close>
      <el-form :model="editRoleForm" label-width="100px">
        <el-form-item label="名称"><el-input v-model="editRoleForm.name" /></el-form-item>
        <el-form-item label="编码"><el-input v-model="editRoleForm.code" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="editRoleForm.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditRole = false">取消</el-button>
        <el-button type="primary" :loading="roleUpdating" @click="submitEditRole">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showRemoveRole" title="移除用户角色" width="450px" destroy-on-close>
      <p style="margin-bottom:12px">用户：<strong>{{ removeRoleTarget?.username }}</strong></p>
      <el-checkbox-group v-model="removeRoleIds">
        <el-checkbox v-for="r in roles" :key="r.id" :label="r.id" :value="r.id">{{ r.name }}</el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="showRemoveRole = false">取消</el-button>
        <el-button type="danger" :loading="removingRole" @click="submitRemoveRole">移除</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showCreatePerm" title="新建权限" width="500px" destroy-on-close>
      <el-form :model="permForm" label-width="100px">
        <el-form-item label="名称">
          <el-input v-model="permForm.name" />
        </el-form-item>
        <el-form-item label="编码">
          <el-input v-model="permForm.code" />
        </el-form-item>
        <el-form-item label="资源">
          <el-input v-model="permForm.resource" placeholder="如: orders" />
        </el-form-item>
        <el-form-item label="操作">
          <el-select v-model="permForm.action" style="width:100%">
            <el-option label="创建" value="create" />
            <el-option label="读取" value="read" />
            <el-option label="更新" value="update" />
            <el-option label="删除" value="delete" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="permForm.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreatePerm = false">取消</el-button>
        <el-button type="primary" :loading="permCreating" @click="submitPerm">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showAssignRole" title="分配角色" width="450px" destroy-on-close>
      <p style="margin-bottom:12px">用户：<strong>{{ assignTarget?.username }}</strong></p>
      <el-checkbox-group v-model="selectedRoles">
        <el-checkbox v-for="r in roles" :key="r.id" :label="r.id" :value="r.id">{{ r.name }}</el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="showAssignRole = false">取消</el-button>
        <el-button type="primary" :loading="assigningRole" @click="submitAssignRole">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showAssignPerm" title="分配权限" width="450px" destroy-on-close>
      <p style="margin-bottom:12px">角色：<strong>{{ assignPermTarget?.name }}</strong></p>
      <el-checkbox-group v-model="selectedPerms">
        <el-checkbox v-for="p in permissions" :key="p.id" :label="p.id" :value="p.id">{{ p.name }} ({{ p.resource }}:{{ p.action }})</el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="showAssignPerm = false">取消</el-button>
        <el-button type="primary" :loading="assigningPerm" @click="submitAssignPerm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import apiClient from '../../api'
import type { FormInstance, FormRules } from 'element-plus'

const activeTab = ref('users')

const loading = ref(false)
const roleLoading = ref(false)
const permLoading = ref(false)
const userCreating = ref(false)
const roleCreating = ref(false)
const permCreating = ref(false)

const users = ref<any[]>([])
const roles = ref<any[]>([])
const permissions = ref<any[]>([])

const showCreateUser = ref(false)
const showCreateRole = ref(false)
const showEditRole = ref(false)
const showCreatePerm = ref(false)
const showAssignRole = ref(false)
const showAssignPerm = ref(false)
const showRemoveRole = ref(false)
const assignTarget = ref<any>(null)
const assignPermTarget = ref<any>(null)
const removeRoleTarget = ref<any>(null)
const selectedRoles = ref<string[]>([])
const selectedPerms = ref<string[]>([])
const removeRoleIds = ref<string[]>([])
const roleUpdating = ref(false)
const assigningRole = ref(false)
const assigningPerm = ref(false)
const removingRole = ref(false)
const editRoleId = ref<number|null>(null)
const userFormRef = ref<FormInstance>()

const userForm = reactive({ username: '', email: '', password: '' })
const userRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }, { type: 'email', message: '邮箱格式不正确', trigger: 'blur' }],
  password: [{ required: true, min: 6, message: '密码至少6位', trigger: 'blur' }],
}

const roleForm = reactive({ name: '', code: '', description: '' })
const editRoleForm = reactive({ name: '', code: '', description: '' })
const permForm = reactive({ name: '', code: '', resource: '', action: 'read', description: '' })

async function fetchUsers() {
  loading.value = true
  try {
    const res = await apiClient.get('/auth/users')
    users.value = res.data?.data ?? res.data ?? []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
    users.value = []
  }
  loading.value = false
}

async function fetchRoles() {
  roleLoading.value = true
  try {
    const res = await apiClient.get('/auth/roles')
    roles.value = res.data?.data ?? res.data ?? []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
    roles.value = []
  }
  roleLoading.value = false
}

async function fetchPerms() {
  permLoading.value = true
  try {
    const res = await apiClient.get('/auth/permissions')
    permissions.value = res.data?.data ?? res.data ?? []
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
    permissions.value = []
  }
  permLoading.value = false
}

async function submitUser() {
  const valid = await userFormRef.value?.validate().catch(() => false)
  if (!valid) return
  userCreating.value = true
  try {
    await apiClient.post('/auth/register', userForm)
    ElMessage.success('创建成功')
    showCreateUser.value = false
    fetchUsers()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
  userCreating.value = false
}

async function toggleUser(row: any) {
  const action = row.is_active ? '停用' : '启用'
  try {
    await ElMessageBox.confirm(`确定${action}用户 ${row.username}？`, '确认', { type: 'warning' })
    await apiClient.post(`/auth/users/${row.id}/toggle`)
    ElMessage.success('操作成功')
    row.is_active = !row.is_active
  } catch { /* ignore */ }
}

function assignRole(row: any) {
  assignTarget.value = row
  selectedRoles.value = []
  showAssignRole.value = true
}

async function submitAssignRole() {
  assigningRole.value = true
  try {
    const results = await Promise.allSettled(
      selectedRoles.value.map(roleId =>
        apiClient.post(`/auth/users/${assignTarget.value!.id}/roles`, { role_id: roleId })
      )
    )
    const failed = results.filter(r => r.status === 'rejected')
    if (failed.length === 0) ElMessage.success('角色分配成功')
    else ElMessage.warning(`角色分配部分失败: ${failed.length}/${results.length}`)
    showAssignRole.value = false
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
  assigningRole.value = false
}

function assignPerm(row: any) {
  assignPermTarget.value = row
  selectedPerms.value = []
  showAssignPerm.value = true
}

async function submitAssignPerm() {
  assigningPerm.value = true
  try {
    const results = await Promise.allSettled(
      selectedPerms.value.map(permId =>
        apiClient.post(`/auth/roles/${assignPermTarget.value!.id}/permissions`, { permission_id: permId })
      )
    )
    const failed = results.filter(r => r.status === 'rejected')
    if (failed.length === 0) ElMessage.success('权限分配成功')
    else ElMessage.warning(`权限分配部分失败: ${failed.length}/${results.length}`)
    showAssignPerm.value = false
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
  assigningPerm.value = false
}

async function deleteRole(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除角色 ${row.name}？`, '提示')
    await apiClient.delete(`/auth/roles/${row.id}`)
    ElMessage.success('删除成功')
    fetchRoles()
  } catch { /* ignore */ }
}

async function submitRole() {
  roleCreating.value = true
  try {
    await apiClient.post('/auth/roles', roleForm)
    ElMessage.success('角色创建成功')
    showCreateRole.value = false
    fetchRoles()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
  roleCreating.value = false
}

function editRole(row: any) {
  editRoleId.value = row.id
  editRoleForm.name = row.name || ''
  editRoleForm.code = row.code || ''
  editRoleForm.description = row.description || ''
  showEditRole.value = true
}

async function submitEditRole() {
  roleUpdating.value = true
  try {
    await apiClient.put(`/auth/roles/${editRoleId.value}`, editRoleForm)
    ElMessage.success('角色已更新')
    showEditRole.value = false
    fetchRoles()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
  roleUpdating.value = false
}

function removeRole(row: any) {
  removeRoleTarget.value = row
  removeRoleIds.value = []
  showRemoveRole.value = true
}

async function submitRemoveRole() {
  removingRole.value = true
  try {
    await ElMessageBox.confirm('确定移除所选角色？', '确认', { type: 'warning' })
    const results = await Promise.allSettled(
      removeRoleIds.value.map(roleId =>
        apiClient.delete(`/auth/users/${removeRoleTarget.value!.id}/roles/${roleId}`)
      )
    )
    const failed = results.filter(r => r.status === 'rejected')
    if (failed.length === 0) ElMessage.success('角色移除成功')
    else ElMessage.warning(`部分移除失败: ${failed.length}/${results.length}`)
    showRemoveRole.value = false
  } catch { /* ignore */ }
  removingRole.value = false
}

async function submitPerm() {
  permCreating.value = true
  try {
    await apiClient.post('/auth/permissions', permForm)
    ElMessage.success('权限创建成功')
    showCreatePerm.value = false
    fetchPerms()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? e.message)
  }
  permCreating.value = false
}

onMounted(() => {
  fetchUsers()
  fetchRoles()
  fetchPerms()
})
</script>
