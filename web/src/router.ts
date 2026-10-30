import { createRouter, createWebHistory } from 'vue-router'
import { api } from './api'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/articles' },
    { path: '/articles', name: 'articles', component: () => import('./views/ArticleList.vue') },
    { path: '/articles/:id', name: 'workbench', component: () => import('./views/Workbench.vue') },
    { path: '/settings', name: 'settings', component: () => import('./views/Settings.vue') },
    { path: '/team', name: 'team', component: () => import('./views/TeamAdmin.vue') },
  ],
})

router.beforeEach(async to => {
  if (!['settings','team'].includes(String(to.name))) return true
  try {
    const status = await api.get('/api/auth/status')
    if (status.team_mode && (await api.get('/api/auth/me')).member.role !== 'admin') return '/articles'
  } catch { return '/articles' }
  return true
})
