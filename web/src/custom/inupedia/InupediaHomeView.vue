<template>
  <div ref="homeContainer" class="home-container">
    <div v-if="isLoading" class="state-container">
      <a-spin size="large" />
      <p>正在连接智能知识平台...</p>
    </div>

    <div v-else-if="error" class="state-container">
      <a-result status="error" :title="error.title" :sub-title="error.message">
        <template #extra>
          <a-button type="primary" @click="loadData">重新连接</a-button>
        </template>
      </a-result>
    </div>

    <template v-else>
      <div class="ambient" aria-hidden="true">
        <div class="ambient-glow ambient-glow--blue"></div>
        <div class="ambient-glow ambient-glow--green"></div>
        <HydraulicHeroScene />
      </div>

      <header class="site-header">
        <div class="site-header-inner">
          <router-link to="/" class="brand" aria-label="返回平台首页">
            <img :src="organization.logo" :alt="organization.name" class="brand-logo" />
            <span class="brand-copy">
              <strong>{{ brandName }}</strong>
              <small>{{ organization.name }}</small>
            </span>
          </router-link>
          <div class="header-actions">
            <UserInfoComponent :show-button="true" />
          </div>
        </div>
      </header>

      <main>
        <section ref="heroSection" class="hero-section">
          <div ref="heroCopy" class="hero-copy">
            <p class="eyebrow">
              <span class="eyebrow-mark"></span>
              四川省引大济岷水资源开发有限公司
            </p>
            <h1>{{ branding.title }}</h1>
            <p class="hero-subtitle">{{ branding.subtitle }}</p>
            <div class="hero-actions">
              <a-button type="primary" size="large" class="primary-action" @click="goToWorkspace">
                进入工作台
              </a-button>
              <a
                class="secondary-action"
                href="#capabilities"
                @click.prevent="scrollToCapabilities"
              >
                查看平台能力
              </a>
            </div>
            <div class="hero-notes" aria-label="平台特点">
              <span><Check :size="15" /> 工程知识沉淀</span>
              <span><Check :size="15" /> 智能协同检索</span>
              <span><Check :size="15" /> 权限可信可控</span>
            </div>
          </div>
        </section>

        <section id="capabilities" class="capabilities-section">
          <div class="section-heading">
            <p>平台能力</p>
            <h2>让工程知识真正进入工作流</h2>
            <span
              >围绕引调水工程建设中的知识获取、智能分析、资料协同与经验复用，形成统一工作入口。</span
            >
          </div>

          <div class="capability-grid">
            <article v-for="item in capabilities" :key="item.title" class="capability-card">
              <span class="capability-index">{{ item.index }}</span>
              <span class="capability-icon"><component :is="item.icon" :size="22" /></span>
              <h3>{{ item.title }}</h3>
              <p>{{ item.description }}</p>
            </article>
          </div>
        </section>
      </main>

      <footer class="site-footer">
        <div>
          <img :src="organization.logo" alt="" />
          <span>{{ footerCopyright }}</span>
        </div>
        <div class="footer-meta">
          <span>智能知识与工程协同平台</span>
          <span class="scene-credit">泸定取水口 · 引大济岷总干线起点</span>
        </div>
      </footer>
    </template>
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { gsap } from 'gsap'
import { Bot, Check, FolderKanban, LibraryBig, SearchCheck } from 'lucide-vue-next'

import { healthApi } from '@/apis/system_api'
import UserInfoComponent from '@/components/UserInfoComponent.vue'
import { useInfoStore } from '@/stores/info'
import { useUserStore } from '@/stores/user'

const HydraulicHeroScene = defineAsyncComponent(() => import('./HydraulicHeroScene.vue'))

const router = useRouter()
const infoStore = useInfoStore()
const userStore = useUserStore()
const isLoading = ref(true)
const error = ref(null)
const homeContainer = ref(null)
const heroSection = ref(null)
const heroCopy = ref(null)

let motionContext = null

const organization = computed(() => infoStore.organization)
const branding = computed(() => infoStore.branding)
const brandName = computed(() => branding.value.name || '引大济岷')
const footerCopyright = computed(
  () => infoStore.footer?.copyright || '© 四川省引大济岷水资源开发有限公司'
)

const capabilities = [
  {
    index: '01',
    title: '智能问答与任务协作',
    description: '让智能体理解建设上下文，辅助资料查询、内容分析与工程任务执行。',
    icon: Bot
  },
  {
    index: '02',
    title: '工程知识统一沉淀',
    description: '汇聚总干线、北干线与南干线资料，形成可持续更新、可授权访问的知识底座。',
    icon: LibraryBig
  },
  {
    index: '03',
    title: '知识关联与精准检索',
    description: '融合向量检索与知识图谱，从文件、实体和关系中定位可信依据。',
    icon: SearchCheck
  },
  {
    index: '04',
    title: '项目资料协同管理',
    description: '围绕工作区组织输入资料、过程文件与智能成果，让经验顺畅流转。',
    icon: FolderKanban
  }
]

async function loadData() {
  isLoading.value = true
  error.value = null
  try {
    const response = await healthApi.checkHealth()
    if (response.status !== 'ok') throw new Error('服务不可用')
    await infoStore.loadInfoConfig(true)
  } catch (loadError) {
    console.error('平台首页加载失败:', loadError)
    error.value = {
      title: '服务连接失败',
      message: '平台服务暂时无法响应，请检查服务状态后重新连接。'
    }
  } finally {
    isLoading.value = false
  }
}

function goToWorkspace() {
  if (!userStore.isLoggedIn) {
    sessionStorage.setItem('redirect', '/agent')
    router.push('/login')
    return
  }
  router.push('/agent')
}

function scrollToCapabilities() {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  document.querySelector('#capabilities')?.scrollIntoView({
    behavior: reduceMotion ? 'auto' : 'smooth',
    block: 'start'
  })
}

/** 初始化首屏内容与环境光的克制入场动画。 */
function setupMotion() {
  if (!homeContainer.value || !heroSection.value) return

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  motionContext = gsap.context(() => {
    if (reduceMotion) return

    gsap.from(heroCopy.value, {
      y: 22,
      opacity: 0,
      duration: 0.9,
      clearProps: 'transform,opacity',
      ease: 'power3.out'
    })

    gsap.to('.ambient-glow--blue', {
      x: -34,
      y: 22,
      duration: 12,
      repeat: -1,
      yoyo: true,
      ease: 'sine.inOut'
    })
  }, homeContainer.value)
}

onMounted(async () => {
  await loadData()
  await nextTick()
  setupMotion()
})

onBeforeUnmount(() => {
  motionContext?.revert()
  motionContext = null
})
</script>

<style lang="less" scoped>
.home-container {
  --hero-text-primary: #122a34;
  --hero-text-secondary: #304a56;
  --hero-text-accent: #245f7c;

  position: relative;
  min-height: 100vh;
  overflow: hidden;
  color: var(--gray-1000);
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--gray-0) 72%, transparent), transparent 34%),
    var(--gray-25);
}

.state-container {
  display: flex;
  min-height: 100vh;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--gray-600);
}

.ambient {
  position: absolute;
  inset: 0 0 auto;
  height: clamp(820px, 92svh, 980px);
  z-index: 0;
  pointer-events: none;
  overflow: hidden;
  mask-image: linear-gradient(180deg, #000 0%, #000 78%, transparent 100%);
}

.ambient-glow {
  position: absolute;
  width: 520px;
  height: 520px;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.36;
}

.ambient-glow--blue {
  top: -260px;
  right: -120px;
  background: var(--main-200);
}

.ambient-glow--green {
  bottom: -320px;
  left: -180px;
  background: var(--brand-green-soft);
}

.hero-section,
.capabilities-section,
.site-footer {
  position: relative;
  z-index: 1;
  width: calc(100% - 64px);
  max-width: 1360px;
  margin: 0 auto;
}

.site-header {
  position: relative;
  z-index: 1;
  width: 100%;
  border-bottom: 1px solid rgba(199, 217, 226, 0.72);
  background: rgba(247, 250, 251, 0.78);
  box-shadow: 0 8px 28px rgba(23, 47, 61, 0.07);
  -webkit-backdrop-filter: blur(14px) saturate(0.86);
  backdrop-filter: blur(14px) saturate(0.86);
}

.site-header-inner {
  display: flex;
  width: calc(100% - 64px);
  max-width: 1360px;
  min-height: 76px;
  align-items: center;
  justify-content: space-between;
  margin: 0 auto;
}

.brand {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 12px;
  color: inherit;
  text-decoration: none;
}

.brand-logo {
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  object-fit: contain;
}

.brand-copy {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.brand-copy strong {
  color: var(--hero-text-primary);
  font-size: 16px;
  font-weight: 650;
  letter-spacing: 0.01em;
}

.brand-copy small {
  overflow: hidden;
  color: var(--hero-text-secondary);
  font-size: 11px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 20px;
}

.hero-section {
  display: flex;
  min-height: clamp(620px, calc(100svh - 76px), 760px);
  align-items: center;
  padding: clamp(44px, 7svh, 72px) 0;
}

.hero-copy {
  width: min(720px, 100%);
  min-width: 0;
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  margin: 0 0 20px;
  color: var(--hero-text-accent);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.08em;
}

.eyebrow-mark {
  width: 24px;
  height: 2px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--main-700), var(--brand-green));
}

.hero-copy h1 {
  margin: 0;
  color: var(--hero-text-primary);
  font-size: clamp(42px, 4.25vw, 64px);
  font-weight: 680;
  letter-spacing: -0.055em;
  line-height: 1.06;
  white-space: nowrap;
}

.hero-subtitle {
  max-width: 580px;
  margin: 26px 0 0;
  color: var(--hero-text-secondary);
  font-size: 18px;
  font-weight: 500;
  line-height: 1.8;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 36px;
}

.primary-action,
.secondary-action {
  min-width: 144px;
  height: 48px;
  border-radius: 12px;
  font-weight: 600;
}

.secondary-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 16px;
  border: 1px solid rgba(167, 194, 207, 0.72);
  color: var(--hero-text-secondary);
  background: rgba(247, 250, 251, 0.74);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  text-decoration: none;
  transition:
    border-color 0.2s ease,
    color 0.2s ease,
    background-color 0.2s ease;
}

.secondary-action:hover {
  border-color: rgba(91, 139, 163, 0.72);
  color: var(--hero-text-accent);
  background: rgba(247, 250, 251, 0.9);
}

.primary-action :deep(.ant-btn-icon) {
  display: inline-flex;
}

.hero-notes {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 24px;
  color: var(--hero-text-secondary);
  font-size: 13px;
  font-weight: 550;
}

.hero-notes span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 1px solid rgba(199, 217, 226, 0.7);
  border-radius: 999px;
  background: rgba(247, 250, 251, 0.74);
  font-weight: 550;
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
}

.hero-notes svg {
  color: var(--brand-green);
}

.capability-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--main-700);
  background: var(--main-50);
}

.capabilities-section {
  padding: 88px 0 104px;
}

.section-heading {
  max-width: 640px;
  margin-bottom: 36px;
}

.section-heading p {
  margin: 0 0 8px;
  color: var(--main-700);
  font-size: 13px;
  font-weight: 650;
  letter-spacing: 0.08em;
}

.section-heading h2 {
  margin: 0;
  color: var(--gray-1000);
  font-size: clamp(28px, 3vw, 40px);
  font-weight: 650;
  letter-spacing: -0.03em;
}

.section-heading > span {
  display: block;
  margin-top: 14px;
  color: var(--gray-700);
  font-size: 15px;
  line-height: 1.75;
}

.capability-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.capability-card {
  position: relative;
  min-height: 240px;
  padding: 24px;
  border: 1px solid var(--gray-150);
  border-radius: 16px;
  background: color-mix(in srgb, var(--gray-0) 92%, transparent);
  transition:
    border-color 0.2s ease,
    box-shadow 0.2s ease;
}

.capability-card:hover {
  border-color: var(--main-200);
  box-shadow: 0 14px 38px rgba(23, 36, 44, 0.07);
}

.capability-index {
  position: absolute;
  top: 22px;
  right: 22px;
  color: var(--gray-300);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  font-weight: 650;
}

.capability-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
}

.capability-card h3 {
  margin: 46px 0 10px;
  color: var(--gray-900);
  font-size: 17px;
  font-weight: 620;
}

.capability-card p {
  margin: 0;
  color: var(--gray-700);
  font-size: 13px;
  line-height: 1.75;
}

.site-footer {
  display: flex;
  min-height: 80px;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  border-top: 1px solid var(--gray-150);
  color: var(--gray-700);
  font-size: 12px;
}

.site-footer > div {
  display: flex;
  align-items: center;
  gap: 10px;
}

.site-footer img {
  width: 24px;
  height: 24px;
  object-fit: contain;
}

.footer-meta {
  display: grid;
  justify-items: end;
  gap: 3px;
}

.scene-credit {
  color: var(--gray-600);
  font-size: 10px;
}

@media (max-width: 1279px) {
  .site-header-inner,
  .hero-section,
  .capabilities-section,
  .site-footer {
    width: calc(100% - 48px);
  }

  .hero-copy h1 {
    font-size: clamp(40px, 4.15vw, 53px);
  }
}

@media (max-width: 1023px) {
  .ambient {
    height: 1120px;
  }

  .hero-section {
    min-height: auto;
    padding: 64px 0 72px;
  }

  .capability-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 767px) {
  .ambient {
    height: 640px;
  }

  .site-header-inner,
  .hero-section,
  .capabilities-section,
  .site-footer {
    width: calc(100% - 32px);
  }

  .site-header-inner {
    min-height: 68px;
  }

  .brand-copy small {
    display: none;
  }

  .hero-section {
    min-height: auto;
    gap: 32px;
    padding: 56px 0 48px;
  }

  .eyebrow {
    align-items: flex-start;
    font-size: 11px;
    line-height: 1.6;
  }

  .hero-copy h1 {
    font-size: clamp(22px, 6.9vw, 34px);
    letter-spacing: -0.05em;
  }

  .hero-subtitle {
    color: var(--hero-text-secondary);
    font-size: 16px;
  }

  .hero-actions {
    align-items: stretch;
  }

  .primary-action,
  .secondary-action {
    flex: 1 1 150px;
  }

  .secondary-action,
  .hero-notes {
    color: var(--hero-text-secondary);
  }

  .capability-grid {
    grid-template-columns: 1fr;
  }

  .capabilities-section {
    padding: 64px 0 72px;
  }

  .capability-card {
    min-height: 210px;
  }

  .site-footer {
    align-items: flex-start;
    flex-direction: column;
    justify-content: center;
    padding: 22px 0;
  }

  .footer-meta {
    justify-items: start;
  }
}
</style>
