<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NDialogProvider, NInput, NModal, useMessage } from 'naive-ui'
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

const STAGE_TEXT: Record<string, string> = {
  collect: '收集', rewrite: '洗稿', review: '审稿', publish: '导出',
}
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
    <!-- 顶栏 -->
    <header class="sticky top-0 z-10 bg-paper/80 backdrop-blur border-b border-slate-200">
      <div class="max-w-5xl mx-auto px-4 h-14 flex items-center gap-3">
        <div class="flex items-center gap-2 font-bold text-[17px]">
          <span class="w-7 h-7 rounded-lg bg-accent text-white grid place-items-center text-sm">稿</span>
          洗稿助手
        </div>
        <div class="flex-1"></div>
        <NButton quaternary @click="router.push('/settings')">设置</NButton>
        <NButton type="primary" @click="showCreate = true">+ 录入链接</NButton>
      </div>
    </header>

    <main class="max-w-5xl mx-auto px-4 py-6">
      <!-- 筛选与搜索 -->
      <div class="flex flex-wrap items-center gap-2 mb-5">
        <button v-for="f in ['全部', 'New', 'Process', 'Done']" :key="f"
                class="px-3.5 h-8 rounded-full text-sm transition-colors"
                :class="filter === f ? 'bg-ink-900 text-white' : 'bg-white text-ink-500 shadow-card hover:text-ink-900'"
                @click="filter = f">
          {{ f }}<span class="ml-1 opacity-60">{{ (counts as any)[f] ?? '' }}</span>
        </button>
        <div class="flex-1"></div>
        <NInput v-model:value="q" placeholder="搜索标题或链接" clearable size="small"
                class="!w-56" />
      </div>

      <!-- 列表 -->
      <div v-if="list.length === 0" class="text-center text-ink-400 py-24">
        <div class="text-5xl mb-4">📰</div>
        还没有文章。点击右上角「录入链接」，把一篇 AI 要闻交给三个 Agent。
      </div>

      <div class="space-y-3">
        <div v-for="a in list" :key="a.id"
             class="bg-white rounded-2xl shadow-card px-5 py-4 cursor-pointer hover:shadow-pop transition-shadow"
             @click="router.push(`/articles/${a.id}`)">
          <div class="flex items-center gap-3">
            <div class="flex-1 min-w-0">
              <div class="font-semibold truncate text-[15px]">
                {{ a.title || a.url }}
              </div>
              <div class="text-xs text-ink-400 mt-1 flex items-center gap-2 flex-wrap">
                <span>{{ a.source_site || '来源待识别' }}</span>
                <span>·</span><span>{{ (a.created_at || '').slice(0, 16) }}</span>
                <span v-if="a.published_at">· 发布 {{ a.published_at.slice(0, 10) }}</span>
                <span v-if="progressText(a)" class="text-amber-600">{{ progressText(a) }}</span>
                <span v-if="a.error" class="text-rose-500 truncate">· {{ a.error }}</span>
              </div>
            </div>
            <StatusChip :status="a.status" :ui-status="a.ui_status" />
          </div>
        </div>
      </div>
    </main>

    <!-- 新建弹窗 -->
    <NModal v-model:show="showCreate" preset="card" title="录入文章链接" class="!max-w-lg">
      <div class="space-y-4">
        <NInput v-model:value="newUrl" type="textarea" :autosize="{ minRows: 2 }"
                placeholder="粘贴公众号 / 新闻 / arXiv 链接，如 https://mp.weixin.qq.com/s/..." />
        <NInput v-model:value="newNotes" placeholder="备注（可选）：写作角度、强调重点等" />
        <div class="text-xs text-ink-400">
          录入后自动启动「资料收集」：抓原文 → 提炼主题 → 关联搜索 → 素材入库。
        </div>
        <div class="flex justify-end gap-2">
          <NButton @click="showCreate = false">取消</NButton>
          <NButton type="primary" :loading="creating" @click="create">开始处理</NButton>
        </div>
      </div>
    </NModal>
  </div>
</template>
