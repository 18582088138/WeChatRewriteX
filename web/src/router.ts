import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/articles' },
    { path: '/articles', name: 'articles', component: () => import('./views/ArticleList.vue') },
    { path: '/articles/:id', name: 'workbench', component: () => import('./views/Workbench.vue') },
    { path: '/settings', name: 'settings', component: () => import('./views/Settings.vue') },
  ],
})
