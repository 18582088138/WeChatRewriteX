<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NTabPane, NTabs, useMessage } from 'naive-ui'
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
const store = useAppStore()

const aid = route.params.id as string
const article = ref<Article | null>(null)
const tab = ref('create')
const busy = ref(false)
const editorRef = ref<InstanceType<typeof BlockEditor> | null>(null)

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
  const s = article.value?.status
  if (['EDITING', 'REVIEWED'].includes(s || '')) tab.value = 'review'
  else if (['FINALIZED', 'DONE', 'PUBLISHING'].includes(s || '')) tab.value = 'publish'
  else if (['DRAFTED'].includes(s || '')) tab.value = 'create'
  else tab.value = 'materials'
})
watch(() => store.workbenchTick, load)

const status = computed(() => article.value?.status || '')

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

// 阶段指示：当前步用 accent，其余中性（taste: 色彩只给数据与当前态）
const STAGES = ['收集资料', '创作与审稿', '定稿发布']
const stageIndex = computed(() => {
  const u = article.value?.ui_status
  return u === 'New' ? 0 : u === 'Process' ? 1 : 2
})
</script>

<template>
  <div class="min-h-screen">
    <header style="background: var(--surface); border-bottom: 1px solid var(--border);">
      <div class="max-w-[1200px] mx-auto px-6 h-12 flex items-center gap-3">
        <button class="text-sm h-8 px-2 rounded-md hover:bg-[var(--raised)]"
                style="color: var(--muted);" @click="router.push('/articles')">← 文章</button>
        <span class="text-xs" style="color: var(--faint);">/</span>
        <div class="font-medium truncate flex-1 text-[14px]">
          {{ article?.title || article?.url || '…' }}
        </div>
        <StatusChip v-if="article" :status="article.status" :ui-status="article.ui_status" />
      </div>
    </header>

    <main class="max-w-[1200px] mx-auto px-6 py-5">
      <!-- 阶段与动作 -->
      <div class="flex items-center gap-5 mb-5 flex-wrap">
        <div class="flex items-center gap-2 text-sm">
          <template v-for="(s, i) in STAGES" :key="s">
            <span :style="i === stageIndex
                    ? 'color: var(--accent); font-weight: 600;'
                    : i < stageIndex ? 'color: var(--text);' : 'color: var(--faint);'">{{ s }}</span>
            <span v-if="i < STAGES.length - 1" style="color: var(--control);">→</span>
          </template>
        </div>
        <div class="flex-1"></div>
        <NButton v-for="act in actions" :key="act.key" size="small"
                 :type="act.primary ? 'primary' : 'default'" :loading="busy"
                 @click="runStage(act.stage!)">{{ act.label }}</NButton>
      </div>

      <div v-if="article?.error" class="mb-4 px-4 py-3 text-sm rounded-md"
           style="background: var(--pill-neg-bg); color: var(--pill-neg-ink);">
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
