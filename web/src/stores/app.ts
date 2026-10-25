import { defineStore } from 'pinia'
import { api, subscribeSse, type SseEvent } from '../api'
import type { Article } from '../types'

/** 全局：文章列表 + SSE 事件驱动刷新 + 编辑器共享状态（选中块锚点）。 */
export const useAppStore = defineStore('app', {
  state: () => ({
    articles: [] as Article[],
    loading: false,
    lastEvent: null as SseEvent | null,
    /** 编辑器当前聚焦块（素材面板「融合插入」的锚点） */
    anchorBlockId: null as string | null,
    /** 工作台刷新信号：相关事件到达时自增，各面板监听后刷新 */
    workbenchTick: 0,
    /** 分阶段进度日志（stage.progress 事件滚动保留 40 条） */
    progressLog: [] as { ts: number; article_id?: string; message: string }[],
    /** 开发者模式（设置页开关；控制日志可视化与成本面板显示） */
    devMode: false as boolean,
  }),
  actions: {
    async refreshArticles() {
      this.loading = true
      try {
        this.articles = (await api.get('/api/articles')).articles
      } finally {
        this.loading = false
      }
    },
    async loadDevMode() {
      try {
        const s = (await api.get('/api/settings')).settings
        this.devMode = !!s?.dev?.mode
      } catch { /* 保持默认关 */ }
    },
    startSse() {
      subscribeSse((e) => {
        this.lastEvent = e
        if (e.type === 'stage.progress') {
          this.progressLog.push({ ts: e.ts, article_id: e.article_id, message: String(e.message || '') })
          if (this.progressLog.length > 40) this.progressLog.splice(0, this.progressLog.length - 40)
          this.workbenchTick++
          return
        }
        if (e.type === 'status.changed' || e.type.startsWith('job.')) {
          this.refreshArticles()
          this.workbenchTick++
        }
        if (['draft.saved', 'review.finished', 'material.ingested'].includes(e.type)) {
          this.workbenchTick++
        }
      })
    },
    clearProgress() {
      this.progressLog = []
    },
  },
})
