const brandedRoutes = [
  {
    parent: 'main',
    name: 'Home',
    route: {
      path: '',
      name: 'Home',
      component: () => import('./InupediaHomeView.vue'),
      meta: { keepAlive: true, requiresAuth: false }
    }
  },
  {
    name: 'login',
    route: {
      path: '/login',
      name: 'login',
      component: () => import('./InupediaLoginView.vue'),
      meta: { requiresAuth: false }
    }
  },
  {
    name: 'CLIAuthAuthorize',
    route: {
      path: '/auth/cli/authorize',
      name: 'CLIAuthAuthorize',
      component: () => import('./InupediaCLIAuthAuthorizeView.vue'),
      meta: { requiresAuth: true }
    }
  }
]

/** 安装引大济岷品牌路由、主题与浏览器页头。 */
export function installInupediaBrand({ router, infoStore }) {
  document.documentElement.classList.add('inupedia-theme')

  for (const { parent, name, route } of brandedRoutes) {
    if (router.hasRoute(name)) router.removeRoute(name)
    parent ? router.addRoute(parent, route) : router.addRoute(route)
  }

  infoStore.loadInfoConfig().then((config) => {
    const brandName = config?.branding?.name?.trim() || '引大济岷'
    const brandTitle = config?.branding?.title?.trim()
    document.title = brandTitle ? `${brandName} - ${brandTitle}` : brandName

    const favicon = document.querySelector('link[rel="icon"]')
    if (favicon) favicon.href = config?.organization?.logo || '/inupedia-logo.svg'
  })
}
