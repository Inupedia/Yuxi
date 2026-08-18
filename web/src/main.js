import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'

import App from './App.vue'
import router from './router'
import { useInfoStore } from '@/stores/info'

import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import '@/assets/css/main.css'
import '@/custom/inupedia/theme.css'
import { installInupediaBrand } from '@/custom/inupedia'

const app = createApp(App)
const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

app.use(pinia)

// 在 Router 首次匹配前安装品牌路由并预加载信息配置
const infoStore = useInfoStore()
installInupediaBrand({ router, infoStore })

app.use(router)
app.use(Antd)

app.mount('#app')
