<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NTabPane, NTabs, useDialog, useMessage } from 'naive-ui'
import { api } from '../api'
import { useAppStore } from '../stores/app'
import type { Article } from '../types'
import StatusChip from '../components/StatusChip.vue'
import MaterialsPanel from '../components/MaterialsPanel.vue'
import BlockEditor from '../components/BlockEditor.vue'
import ReviewPanel from '../components/ReviewPanel.vue'
import PublishPanel from '../components/PublishPanel.vue'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const store = useAppStore()

const aid = route.params.id as string
const article = ref<Article | null>(null)
const tab = ref('create')
const busy = ref(false)
const editorRef = ref<InstanceType<typeof BlockEditor> | null>(null)

/** 素材面板勾选参考段落 → 跳到创作 tab 并打开融合插入弹窗 */
async function onInsertRefs(ids: string[]) {
  tab.value = 'create'
  await nextTick()
  editorRef.value?.openInsertRefs(ids)
}

async function load() {
  article.value = await api.get(`/api/articles/${aid}`)
}
onMounted(async () => {
  await load()
  // 根据状态落在合适 tab
  const s = article.value?.status
  if (['EDITING', 'REVIEWED'].includes(s || '')) tab.value = 'review'
  else if (['FINALIZED', 'DONE', 'PUBLISHING'].includes(s || '')) tab.value = 'publish'
  else if (['DRAFTED'].includes(s || '')) tab.value = 'create'
  else tab.value = 'materials'
})
watch(() => store.workbenchTick, load)

const status = computed(() => article.value?.status || '')

/** 当前可执行的阶段动作 */
const actions = computed(() => {
  const s = status.value
  const list: { key: string; label: string; stage?: string; primary?: boolean }[] = []
  if (s === 'NEW' || s === 'FAILED') list.push({ key: 'collect', label: '开始收集', stage: 'collect', primary: true })
  if (s === 'COLLECTED') {
    list.push({ key: 'rewrite', label: '开始洗稿', stage: 'rewrite', primary: true })
    list.push({ key: 'recollect', label: '补充收集', stage: 'collect' })
  }
  if (s === 'DRAFTED') list.push({ key: 'review', label: '开始审稿', stage: 'review', primary: true })
  return list
})

async function runStage(stage: string) {
  busy.value = true
  try {
    await api.post(`/api/articles/${aid}/advance`, { stage })
    message.success('任务已提交，处理中…')
    setTimeout(load, 800)
  } catch (e: any) {
    message.error(e.message)
  } finally {
    busy.value = false
  }
}

const STEPS = [
  { key: 'New', label: '收集' },
  { key: 'Process', label: '创作 · 审稿' },
  { key: 'Done', label: '定稿 · 发布' },
]
const stepIndex = computed(() => {
  const u = article.value?.ui_status
  return u === 'New' ? 0 : u === 'Process' ? 1 : 2
})
</script>

<template>
  <div class="min-h-screen">
    <header class="sticky top-0 z-10 bg-paper/80 backdrop-blur border-b border-slate-200">
      <div class="max-w-6xl mx-auto px-4 h-14 flex items-center gap-3">
        <button class="text-ink-400 hover:text-ink-900 text-sm" @click="router.push('/articles')">← 列表</button>
        <div class="font-semibold truncate flex-1 text-[15px]">
          {{ article?.title || article?.url || '…' }}
        </div>
        <StatusChip v-if="article" :status="article.status" :ui-status="article.ui_status" />
      </div>
    </header>

    <main class="max-w-6xl mx-auto px-4 py-5">
      <!-- 进度 + 阶段动作 -->
      <div class="bg-white rounded-2xl shadow-card px-5 py-4 mb-4 flex items-center gap-4 flex-wrap">
        <div class="flex items-center gap-2 text-sm">
          <template v-for="(s, i) in STEPS" :key="s.key">
            <div class="flex items-center gap-2">
              <span class="w-6 h-6 rounded-full grid place-items-center text-xs font-semibold"
                    :class="i <= stepIndex ? 'bg-accent text-white' : 'bg-slate-200 text-ink-400'">{{ i + 1 }}</span>
              <span :class="i <= stepIndex ? 'text-ink-900 font-medium' : 'text-ink-400'">{{ s.label }}</span>
            </div>
            <span v-if="i < STEPS.length - 1" class="text-slate-300 mx-1">——</span>
          </template>
        </div>
        <div class="flex-1"></div>
        <NButton v-for="act in actions" :key="act.key" size="small"
                 :type="act.primary ? 'primary' : 'default'" :loading="busy"
                 @click="runStage(act.stage!)">{{ act.label }}</NButton>
      </div>

      <div v-if="article?.error" class="bg-rose-50 text-rose-600 rounded-xl px-4 py-3 mb-4 text-sm">
        上次任务失败：{{ article.error }}
      </div>

      <NTabs v-model:value="tab" type="line" animated size="large">
        <NTabPane name="materials" tab="素材库">
          <MaterialsPanel :article-id="aid" @insert-refs="onInsertRefs" />
        </NTabPane>
        <NTabPane name="create" tab="创作">
          <BlockEditor ref="editorRef" :article-id="aid" @goto-review="tab = 'review'" />
        </NTabPane>
        <NTabPane name="review" tab="审稿">
          <ReviewPanel :article-id="aid" @goto-publish="tab = 'publish'" />
        </NTabPane>
        <NTabPane name="publish" tab="发布">
          <PublishPanel :article-id="aid" />
        </NTabPane>
      </NTabs>
    </main>
  </div>
</template>
