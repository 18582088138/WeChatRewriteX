<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NInput, NModal, useMessage } from 'naive-ui'
import { api } from '../api'
import { useAppStore } from '../stores/app'
import StatusChip from '../components/StatusChip.vue'

const store = useAppStore()
const router = useRouter()
const message = useMessage()

const filter = ref<string>('全部')
const q = ref('')
const showCreate = ref(false)
const newUrl = ref('')
const newNotes = ref('')
const creating = ref(false)

const list = computed(() => {
  let rows = store.articles
  if (filter.value !== '全部') rows = rows.filter(a => a.ui_status === filter.value)
  const kw = q.value.trim().toLowerCase()
  if (kw) rows = rows.filter(a => (a.title + a.url).toLowerCase().includes(kw))
  return rows
})

const counts = computed(() => ({
  全部: store.articles.length,
  New: store.articles.filter(a => a.ui_status === 'New').length,
  Process: store.articles.filter(a => a.ui_status === 'Process').length,
  Done: store.articles.filter(a => a.ui_status === 'Done').length,
}))

async function create() {
  if (!newUrl.value.trim()) {
    message.warning('请粘贴文章链接')
    return
  }
  creating.value = true
  try {
    const r = await api.post('/api/articles', { url: newUrl.value.trim(), user_notes: newNotes.value })
    showCreate.value = false
    newUrl.value = ''; newNotes.value = ''
    message.success('已录入，开始收集资料')
    await store.refreshArticles()
    router.push(`/articles/${r.article.id}`)
  } catch (e: any) {
    message.error(e.message)
  } finally {
    creating.value = false
  }
}

const STAGE_TEXT: Record<string, string> = { collect: '收集', rewrite: '洗稿', review: '审稿', publish: '导出' }
function progressText(a: any): string {
  const p = a.progress
  if (!p) return ''
  const cur = [...(p.running || []), ...(p.pending || [])].map(s => STAGE_TEXT[s] || s)
  return cur.length ? `进行中: ${cur.join(' → ')}` : ''
}

onMounted(store.refreshArticles)
</script>

<template>
  <div class="min-h-screen">
    <!-- 顶栏：朴素一条，品牌标记 + 名称 + 链接 + 一个主操作 -->
    <header class="bg-surface border-b" style="border-color: var(--border); background: var(--surface);">
      <div class="max-w-[1200px] mx-auto px-6 h-12 flex items-center gap-3">
        <div class="flex items-center gap-2.5">
          <span class="inline-block w-4 h-4" style="background: var(--accent);"></span>
          <span class="font-semibold text-[15px] tracking-tight">洗稿助手</span>
          <span class="text-xs" style="color: var(--faint);">AI 要闻再创作工作台</span>
        </div>
        <div class="flex-1"></div>
        <button class="text-sm h-8 px-3 rounded-md hover:bg-[var(--raised)]"
                style="color: var(--muted);" @click="router.push('/settings')">设置</button>
        <NButton type="primary" size="small" class="!h-8" @click="showCreate = true">录入链接</NButton>
      </div>
    </header>

    <main class="max-w-[1200px] mx-auto px-6 py-6">
      <!-- 标题行 -->
      <div class="flex items-end justify-between mb-5 flex-wrap gap-3">
        <div>
          <h1 class="text-2xl font-semibold tracking-tight">文章</h1>
          <p class="text-sm mt-1" style="color: var(--muted);">
            共 {{ store.articles.length }} 篇 · 处理中 {{ counts.Process }} 篇
          </p>
        </div>
        <!-- 筛选（下划线 tabs 风格）+ 搜索 -->
        <div class="flex items-center gap-1 border-b" style="border-color: var(--border);">
          <button v-for="f in ['全部', 'New', 'Process', 'Done']" :key="f"
                  class="px-3 h-9 text-sm transition-colors border-b-2 -mb-px"
                  :style="filter === f
                    ? 'border-color: var(--accent); color: var(--text); font-weight: 600;'
                    : 'border-color: transparent; color: var(--muted);'"
                  @click="filter = f">
            {{ f }}<span class="ml-1 num" style="color: var(--faint);">{{ (counts as any)[f] }}</span>
          </button>
        </div>
        <NInput v-model:value="q" placeholder="搜索标题或链接" clearable size="small" class="!w-56" />
      </div>

      <!-- 列表：1px 分隔行，无卡片阴影 -->
      <div class="panel overflow-hidden">
        <div v-if="list.length === 0" class="py-20 text-center">
          <p class="text-[15px]" style="color: var(--muted);">还没有文章。</p>
          <p class="text-sm mt-2" style="color: var(--faint);">
            点右上角「录入链接」，把一篇 AI 要闻交给收集、洗稿、审稿三个 Agent。
          </p>
          <NButton type="primary" size="small" class="mt-5" @click="showCreate = true">录入第一篇</NButton>
        </div>

        <div v-for="(a, i) in list" :key="a.id"
             class="flex items-center gap-4 px-5 h-[68px] cursor-pointer hover:bg-[var(--raised)] transition-colors"
             :style="i > 0 ? 'border-top: 1px solid var(--rule);' : ''"
             @click="router.push(`/articles/${a.id}`)">
          <div class="flex-1 min-w-0">
            <div class="font-medium text-[15px] truncate">{{ a.title || a.url }}</div>
            <div class="text-xs mt-1 flex items-center gap-2 flex-wrap" style="color: var(--faint);">
              <span>{{ a.source_site || '来源待识别' }}</span>
              <span aria-hidden="true">·</span>
              <span class="num">{{ (a.created_at || '').slice(0, 16) }}</span>
              <span v-if="a.published_at" class="num">· 发布 {{ a.published_at.slice(0, 10) }}</span>
              <span v-if="progressText(a)" style="color: var(--pill-warn-ink);">{{ progressText(a) }}</span>
              <span v-if="a.error" style="color: var(--pill-neg-ink);" class="truncate">· {{ a.error }}</span>
            </div>
          </div>
          <StatusChip :status="a.status" :ui-status="a.ui_status" />
        </div>
      </div>
    </main>

    <!-- 新建弹窗 -->
    <NModal v-model:show="showCreate" preset="card" title="录入文章链接" class="!max-w-lg">
      <div class="space-y-4">
        <NInput v-model:value="newUrl" type="textarea" :autosize="{ minRows: 2 }"
                placeholder="粘贴公众号 / 新闻 / arXiv 链接，如 https://mp.weixin.qq.com/s/..." />
        <NInput v-model:value="newNotes" placeholder="备注（可选）：写作角度、强调重点等" />
        <p class="text-xs" style="color: var(--faint);">
          录入后自动开始收集：抓原文与图片 → 提炼主题 → 关联搜索 3~5 篇参考（含 arXiv 论文）→
          素材不足时用可商用图库补齐配图。
        </p>
        <div class="flex justify-end gap-2">
          <NButton size="small" @click="showCreate = false">取消</NButton>
          <NButton type="primary" size="small" :loading="creating" @click="create">开始处理</NButton>
        </div>
      </div>
    </NModal>
  </div>
</template>
