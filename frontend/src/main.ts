import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import { ElNotification } from 'element-plus'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(ElementPlus, { locale: undefined })
app.use(createPinia())
app.use(router)

app.config.errorHandler = (err, _instance, info) => {
  console.error('[Global Vue Error]', err, info)
  ElNotification.error({ title: '页面错误', message: (err as Error)?.message || '未知错误', duration: 5000 })
}

router.onError((err) => {
  console.error('[Router Error]', err)
  ElNotification.error({ title: '路由加载失败', message: (err as Error)?.message || '未知错误', duration: 5000 })
})

app.mount('#app')
