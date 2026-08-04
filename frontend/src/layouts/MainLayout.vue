<template>
  <el-container class="app-container">
    <el-aside :width="isCollapsed ? '64px' : '220px'" class="app-aside">
      <div class="logo-area">
        <span v-if="!isCollapsed" class="logo-text">OMS · WMS · TMS</span>
        <span v-else class="logo-short">OWT</span>
      </div>
      <el-menu
        :default-active="route.path"
        :collapse="isCollapsed"
        background-color="#001529"
        text-color="#ffffffa6"
        active-text-color="#fff"
        router
      >
        <el-menu-item index="/dashboard">
          <el-icon><Odometer /></el-icon>
          <template #title>仪表盘</template>
        </el-menu-item>
        <el-menu-item index="/orders">
          <el-icon><List /></el-icon>
          <template #title>订单管理</template>
        </el-menu-item>
        <el-sub-menu index="wh-section">
          <template #title>
            <el-icon><HomeFilled /></el-icon>
            <span>仓库管理</span>
          </template>
          <el-menu-item index="/warehouses">仓库列表</el-menu-item>
          <el-menu-item index="/warehouses/vendors">供应商管理</el-menu-item>
          <el-menu-item index="/warehouses/purchase-orders">采购单管理</el-menu-item>
          <el-menu-item index="/warehouses/shipments">发货管理</el-menu-item>
          <el-menu-item index="/warehouses/invoices">发票管理</el-menu-item>
          <el-menu-item index="/stock/in">入库管理</el-menu-item>
          <el-menu-item index="/stock/out">出库管理</el-menu-item>
          <el-menu-item index="/stock/adjust">库存调整</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="transport-section">
          <template #title>
            <el-icon><Van /></el-icon>
            <span>运输管理</span>
          </template>
          <el-menu-item index="/transport">运单列表</el-menu-item>
          <el-menu-item index="/transport/waybills">面单管理</el-menu-item>
          <el-menu-item index="/transport/batch-print">批量打单</el-menu-item>
          <el-menu-item index="/transport/freight-quote">运费试算</el-menu-item>
          <el-menu-item index="/transport/returns">退货管理</el-menu-item>
          <el-menu-item index="/transport/exceptions">运输异常</el-menu-item>
          <el-menu-item index="/transport/routes">路线规划</el-menu-item>
          <el-menu-item index="/transport/freight">运费管理</el-menu-item>
          <el-menu-item index="/transport/infrastructure">基础设施</el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="barcode-section">
          <template #title>
            <el-icon><PriceTag /></el-icon>
            <span>条码管理</span>
          </template>
          <el-menu-item index="/barcode">条码记录</el-menu-item>
          <el-menu-item index="/barcode/templates">面单模板</el-menu-item>
        </el-sub-menu>
        <el-menu-item index="/devices">
          <el-icon><Monitor /></el-icon>
          <template #title>设备管理</template>
        </el-menu-item>
        <el-menu-item index="/pda">
          <el-icon><Iphone /></el-icon>
          <template #title>PDA 作业</template>
        </el-menu-item>
        <el-menu-item index="/notifications">
          <el-icon><Bell /></el-icon>
          <template #title>
            <el-badge :value="unreadCount" :hidden="unreadCount===0" :max="99">
              <span>通知中心</span>
            </el-badge>
          </template>
        </el-menu-item>
        <el-menu-item index="/analytics">
          <el-icon><DataAnalysis /></el-icon>
          <template #title>数据分析</template>
        </el-menu-item>
        <el-menu-item index="/connectors">
          <el-icon><Connection /></el-icon>
          <template #title>集成连接器</template>
        </el-menu-item>
        <el-menu-item index="/webhooks">
          <el-icon><Link /></el-icon>
          <template #title>Webhooks</template>
        </el-menu-item>
        <el-sub-menu index="admin">
          <template #title>
            <el-icon><Setting /></el-icon>
            <span>系统管理</span>
          </template>
          <el-menu-item index="/admin/users">
            <el-icon><User /></el-icon>
            <template #title>用户管理</template>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="app-header">
        <div class="header-left">
          <el-button :icon="isCollapsed ? Expand : Fold" text @click="toggleCollapse" />
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="route.meta?.title">{{ route.meta.title }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <el-dropdown trigger="click">
            <span class="user-info">
              <el-icon><User /></el-icon>
              {{ authStore.username || '用户' }}
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="handleLogout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-alert
        v-if="!online"
        title="网络已断开，部分功能可能不可用"
        type="warning"
        :closable="false"
        show-icon
      />
      <el-main class="app-main">
        <router-view />
        <el-backtop target=".app-main" :visibility-height="400" />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useNetworkStatus } from '../composables/useNetworkStatus'
import { ElBadge, ElMessage } from 'element-plus'
import apiClient from '../api'
import { Odometer, List, HomeFilled, Van, PriceTag, Setting, User, ArrowDown, Expand, Fold, Monitor, Iphone, Bell, Connection, Link, DataAnalysis } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { online } = useNetworkStatus()
const isCollapsed = ref(localStorage.getItem('sidebar_collapsed') === 'true')
const unreadCount = ref(0)

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
  localStorage.setItem('sidebar_collapsed', String(isCollapsed.value))
}

function handleLogout() {
  authStore.logout()
  router.push('/login')
}

async function fetchUnreadCount() {
  if (!authStore.isAuthenticated) return
  try {
    const res = await apiClient.get('/notifications?page=1&page_size=1')
    const d = res.data?.data ?? res.data ?? {}
    const items = Array.isArray(d) ? d : (d.items ?? [])
    unreadCount.value = d.total ?? items.length ?? 0
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail ?? e.message) }
}

onMounted(() => {
  if (authStore.isAuthenticated) {
    authStore.fetchMe()
    fetchUnreadCount()
  }
})
</script>

<style scoped>
.app-container {
  height: 100vh;
}
.app-aside {
  background-color: #001529;
  transition: width 0.3s;
  overflow: hidden;
}
.logo-area {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  border-bottom: 1px solid #ffffff1a;
}
.logo-short {
  font-size: 13px;
}
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 16px;
  height: 60px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-right {
  display: flex;
  align-items: center;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}
.app-main {
  background-color: #f0f2f5;
  padding: 16px;
  overflow-y: auto;
}
</style>
