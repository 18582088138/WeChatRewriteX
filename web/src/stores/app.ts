import { defineStore } from 'pinia'
import { api, subscribeSse, type SseEvent } from '../api'
import type { Article, ArticlePage } from '../types'

let stopSse: (() => void) | null = null
let refreshTimer: ReturnType<typeof setTimeout> | null = null
let refreshId = 0
let refreshController: AbortController | null = null

/** 全局：文章列表 + SSE 事件驱动刷新 + 编辑器共享状态（选中块锚点）。 */
export const useAppStore = defineStore('app', {
  state: () => ({
    articles: [] as Article[],
    articleTotal: 0,
    articlePage: 1,
    articlePageSize: 30,
    articleFilter: '',
    articleSearch: '',
    articleCounts: { '全部': 0, New: 0, Process: 0, Done: 0, Failed: 0 } as Record<string, number>,
    articleTicks: {} as Record<string, number>,
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
    invalidateArticle(aid: string) {
      this.articleTicks[aid] = (this.articleTicks[aid] || 0) + 1
      this.workbenchTick++
    },
    async refreshArticles() {
      const id = ++refreshId
      refreshController?.abort()
      refreshController = new AbortController()
      this.loading = true
      try {
        const query = new URLSearchParams({ limit: String(this.articlePageSize),
          offset: String((this.articlePage - 1) * this.articlePageSize),
          q: this.articleSearch, status: this.articleFilter })
        const result = await api.get<ArticlePage>('/api/articles?' + query, refreshController.signal)
        if (id === refreshId) {
          this.articles = result.articles
          this.articleTotal = result.total
          this.articleCounts = result.counts
        }
      } catch (error: any) {
        if (error.name !== 'AbortError') console.error(error)
      } finally {
        if (id === refreshId) this.loading = false
      }
    },
    async loadDevMode() {
      try {
        const s = (await api.get('/api/settings')).settings
        this.devMode = !!s?.dev?.mode
      } catch { /* 保持默认关 */ }
    },
    startSse() {
      stopSse?.()
      stopSse = subscribeSse((e) => {
        this.lastEvent = e
        if (e.type === 'connection.ready') {
          this.refreshArticles()
          for (const aid of new Set([...Object.keys(this.articleTicks), ...this.articles.map(a => a.id)])) {
            this.invalidateArticle(aid)
          }
          return
        }
        if (e.type === 'stage.progress') {
          this.progressLog.push({ ts: e.ts, article_id: e.article_id, message: String(e.message || '') })
          if (this.progressLog.length > 40) this.progressLog.splice(0, this.progressLog.length - 40)
          return
        }
        if (e.type === 'status.changed' || e.type.startsWith('job.') || e.type === 'article.added' || e.type === 'publish.finished') {
          if (refreshTimer) clearTimeout(refreshTimer)
          refreshTimer = setTimeout(() => this.refreshArticles(), 250)
        }
        if (e.article_id) {
          // Completion is actionable immediately; Vue batches same-turn events.
          this.invalidateArticle(e.article_id)
        }
      })
    },
    stopSse() {
      stopSse?.()
      stopSse = null
      if (refreshTimer) clearTimeout(refreshTimer)
      refreshController?.abort()
    },
    clearProgress() {
      this.progressLog = []
    },
  },
})
