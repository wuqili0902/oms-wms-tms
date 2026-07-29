import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/Login.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      meta: { requiresAuth: true },
      redirect: '/dashboard',
      children: [
        { path: 'dashboard', name: 'Dashboard', meta: { title: '仪表盘' }, component: () => import('../views/Dashboard.vue') },
        { path: 'orders', name: 'Orders', meta: { title: '订单管理' }, component: () => import('../views/orders/OrderList.vue') },
        { path: 'orders/:id', name: 'OrderDetail', meta: { title: '订单详情' }, component: () => import('../views/orders/OrderDetail.vue') },
        { path: 'warehouses', name: 'Warehouses', meta: { title: '仓库管理' }, component: () => import('../views/warehouses/WarehouseList.vue') },
        { path: 'warehouses/:id', name: 'WarehouseDetail', meta: { title: '仓库详情' }, component: () => import('../views/warehouses/WarehouseDetail.vue') },
        { path: 'warehouses/vendors', name: 'Vendors', meta: { title: '供应商管理' }, component: () => import('../views/warehouses/VendorList.vue') },
        { path: 'warehouses/purchase-orders', name: 'PurchaseOrders', meta: { title: '采购单管理' }, component: () => import('../views/warehouses/PurchaseOrderList.vue') },
        { path: 'warehouses/shipments', name: 'Shipments', meta: { title: '发货管理' }, component: () => import('../views/warehouses/ShipmentList.vue') },
        { path: 'warehouses/invoices', name: 'Invoices', meta: { title: '发票管理' }, component: () => import('../views/warehouses/InvoiceList.vue') },
        { path: 'transport', name: 'Transport', meta: { title: '运输管理' }, component: () => import('../views/transport/TransportOrderList.vue') },
        { path: 'transport/:id', name: 'TransportDetail', meta: { title: '运单详情' }, component: () => import('../views/transport/TransportOrderDetail.vue') },
        { path: 'transport/returns', name: 'TransportReturns', meta: { title: '退货管理' }, component: () => import('../views/transport/ReturnOrderList.vue') },
        { path: 'transport/exceptions', name: 'TransportExceptions', meta: { title: '运输异常' }, component: () => import('../views/transport/ExceptionList.vue') },
        { path: 'transport/routes', name: 'TransportRoutes', meta: { title: '路线规划' }, component: () => import('../views/tms/RoutePlanDetail.vue') },
        { path: 'transport/freight', name: 'TransportFreight', meta: { title: '运费管理' }, component: () => import('../views/tms/FreightTierList.vue') },
        { path: 'transport/infrastructure', name: 'TmsInfrastructure', meta: { title: '运输基础设施' }, component: () => import('../views/tms/TmsInfrastructure.vue') },
        { path: 'barcode', name: 'Barcode', meta: { title: '条码管理' }, component: () => import('../views/barcode/BarcodeManager.vue') },
        { path: 'devices', name: 'Devices', meta: { title: '设备管理' }, component: () => import('../views/devices/DeviceList.vue') },
        { path: 'pda', name: 'Pda', meta: { title: 'PDA 作业' }, component: () => import('../views/pda/PdaPage.vue') },
        { path: 'notifications', name: 'Notifications', meta: { title: '通知中心' }, component: () => import('../views/notifications/NotificationList.vue') },
        { path: 'connectors', name: 'Connectors', meta: { title: '集成连接器' }, component: () => import('../views/connectors/ConnectorList.vue') },
        { path: 'analytics', name: 'Analytics', meta: { title: '数据分析' }, component: () => import('../views/analytics/AnalyticsDetail.vue') },
        { path: 'webhooks', name: 'Webhooks', meta: { title: 'Webhooks' }, component: () => import('../views/webhooks/WebhookList.vue') },
        { path: 'admin/users', name: 'AdminUsers', meta: { title: '系统管理' }, component: () => import('../views/admin/UserList.vue') },
        { path: ':pathMatch(.*)*', name: 'NotFound', meta: { title: '页面不存在' }, component: () => import('../views/NotFound.vue') },
      ],
    },
  ],
})

router.beforeEach(async (to, _from) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth !== false && !auth.isAuthenticated) {
    return '/login'
  } else if (to.name === 'Login' && auth.isAuthenticated) {
    return '/'
  }
})

export default router
