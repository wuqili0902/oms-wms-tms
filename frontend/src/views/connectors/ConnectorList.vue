<template>
  <div>
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card>
          <template #header>
            <div style="display:flex;align-items:center;gap:8px">
              <el-icon><Shop /></el-icon><span>Shopify</span>
            </div>
          </template>
          <p style="font-size:13px;color:#909399;margin-bottom:12px">接收 Shopify 订单推送通知</p>
          <el-alert type="info" :title="'Webhook 端点: POST /api/v1/connectors/shopify/webhook'" show-icon :closable="false" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header>
            <div style="display:flex;align-items:center;gap:8px">
              <el-icon><Connection /></el-icon><span>Amazon SP-API</span>
            </div>
          </template>
          <p style="font-size:13px;color:#909399;margin-bottom:12px">导入 Amazon 订单和追踪更新</p>
          <div style="display:flex;gap:8px">
            <el-button size="small" :loading="amzLoading" @click="importAmazonOrders">导入订单</el-button>
            <el-button size="small" :loading="amzTrackLoading" @click="syncAmazonTracking">同步追踪</el-button>
          </div>
          <el-alert v-if="amzResult" :title="amzResult" type="success" show-icon closable style="margin-top:12px" />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card>
          <template #header>
            <div style="display:flex;align-items:center;gap:8px">
              <el-icon><Connection /></el-icon><span>ERP 连接器</span>
            </div>
          </template>
          <p style="font-size:13px;color:#909399;margin-bottom:12px">SAP PI/PO 和 Oracle EDI 集成</p>
          <el-tag>状态: 已配置</el-tag>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Shop, Connection } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import apiClient from '../../api'

const amzLoading = ref(false)
const amzTrackLoading = ref(false)
const amzResult = ref('')

async function importAmazonOrders() {
  amzLoading.value = true
  amzResult.value = ''
  try {
    await apiClient.post('/connectors/amazon/orders')
    amzResult.value = 'Amazon 订单导入请求已发送'
    ElMessage.success('导入请求已发送')
  } catch { amzResult.value = '导入失败，请检查配置' }
  amzLoading.value = false
}

async function syncAmazonTracking() {
  amzTrackLoading.value = true
  amzResult.value = ''
  try {
    await apiClient.post('/connectors/amazon/tracking')
    amzResult.value = 'Amazon 追踪同步请求已发送'
    ElMessage.success('同步请求已发送')
  } catch { amzResult.value = '同步失败，请检查配置' }
  amzTrackLoading.value = false
}
</script>
