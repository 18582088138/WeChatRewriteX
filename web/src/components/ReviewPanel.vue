<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NEmpty, NTag, useDialog, useMessage } from 'naive-ui'
import { api } from '../api'
import { useAppStore } from '../stores/app'
import type { Block, DraftDoc, ReviewItem } from '../types'

const props = defineProps<{ articleId: string }>()
const emit = defineEmits<{ (e: 'goto-publish'): void }>()
const message = useMessage()
const dialog = useDialog()
const store = useAppStore()

const review = ref<any>(null)
const items = ref<ReviewItem[]>([])
const doc = ref<DraftDoc | null>(null)
const highlightId = ref<string | null>(null)
const busyId = ref('')
const finalizing = ref(false)
const loading = ref(true)

const CAT_LABEL: Record<string, string> = {
  layout: '排版', fact: '事实', attribution: '来源',
  compliance: '合规', originality: '撞稿', ai_flavor: 'AI味',
}
const SEV = {
  blocker: { label: '阻断', cls: 'bg-rose-100 text-rose-700 border-rose-200' },
  warn: { label: '警告', cls: 'bg-amber-100 text-amber-700 border-amber-200' },
  info: { label: '提示', cls: 'bg-slate-100 text-ink-500 border-slate-200' },
}

async function load() {
  loading.value = true
  try {
    const r = await api.get(`/api/articles/${props.articleId}/reviews/latest`)
    review.value = r.review
    items.value = r.items
  } catch { review.value = null; items.value = [] }
  try {
    doc.value = (await api.get(`/api/articles/${props.articleId}/draft`)).draft.doc
  } catch { doc.value = null }
  loading.value = false
}
onMounted(load)
watch(() => store.workbenchTick, load)

const pendingBlockers = computed(
  () => items.value.filter(i => i.severity === 'blocker' && ['pending', 'accepted'].includes(i.status)))
const pendingCount = computed(
  () => items.value.filter(i => ['pending', 'accepted'].includes(i.status)).length)

function locate(item: ReviewItem) {
  if (!item.block_id) return
  highlightId.value = item.block_id
  document.getElementById('rv-' + item.block_id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

async function resolve(item: ReviewItem, action: 'accept' | 'dismiss' | 'fix') {
  busyId.value = item.id
  try {
    const r = await api.post(`/api/review-items/${item.id}/resolve`, { action })
    if (action === 'fix') message.success(`已修复，生成 v${r.new_version}`)
    await load()
  } catch (e: any) { message.error(e.message) } finally { busyId.value = '' }
}

async function reReview() {
  try {
    await api.post(`/api/articles/${props.articleId}/advance`, { stage: 'review' })
    message.success('复审任务已提交')
  } catch (e: any) { message.error(e.message) }
}

async function finalize(force = false) {
  finalizing.value = true
  try {
    await api.post(`/api/articles/${props.articleId}/finalize`, { force })
    message.success('已定稿 🎉')
    emit('goto-publish')
  } catch (e: any) {
    if (String(e.message).includes('blocker')) {
      dialog.warning({
        title: '存在未处理 blocker',
        content: `${e.message}。可以回创作页修改、AI 修复，或强制定稿（将留痕）。`,
        positiveText: '强制定稿', negativeText: '再改改',
        onPositiveClick: () => finalize(true),
      })
    } else message.error(e.message)
  } finally { finalizing.value = false }
}

const scores = computed(() => review.value ? JSON.parse(review.value.scores_json || '{}') : {})
</script>

<template>
  <div class="flex gap-5 items-start">
    <!-- checklist -->
    <div class="w-[420px] shrink-0 space-y-3">
      <div class="bg-white rounded-2xl shadow-card p-4 flex items-center gap-3">
        <div class="text-sm">
          <span class="font-semibold">{{ items.length }}</span> 条意见 ·
          <span class="text-rose-600 font-semibold">{{ pendingBlockers.length }}</span> 阻断 ·
          <span class="text-ink-400">{{ pendingCount }} 待处理</span>
          <span v-if="scores.ai_flavor" class="ml-2 text-ink-400">AI味 {{ scores.ai_flavor }}/5</span>
          <span v-if="scores.originality_max_jaccard != null" class="ml-2 text-ink-400">
            最高相似 {{ (scores.originality_max_jaccard * 100).toFixed(0) }}%</span>
        </div>
        <div class="flex-1"></div>
        <NButton size="small" @click="reReview">重新审稿</NButton>
      </div>

      <NEmpty v-if="!loading && !items.length" description="暂无审稿意见" class="py-16" />

      <div v-for="item in items" :key="item.id"
           class="bg-white rounded-2xl shadow-card p-4 border-l-4 cursor-pointer"
           :class="[SEV[item.severity].cls.split(' ')[2],
                    ['dismissed', 'fixed'].includes(item.status) ? 'opacity-50' : '']"
           @click="locate(item)">
        <div class="flex items-center gap-2 mb-1.5">
          <NTag size="tiny" :bordered="false">{{ CAT_LABEL[item.category] }}</NTag>
          <span class="text-xs px-2 py-0.5 rounded-full" :class="SEV[item.severity].cls">
            {{ SEV[item.severity].label }}</span>
          <span v-if="item.status !== 'pending'" class="text-xs text-ink-400">
            · {{ { accepted: '已采纳', dismissed: '已忽略', fixed: '已修复' }[item.status] }}</span>
        </div>
        <div class="text-sm leading-relaxed">{{ item.message }}</div>
        <div v-if="item.suggestion" class="text-xs text-ink-400 mt-1.5">建议：{{ item.suggestion }}</div>
        <div class="flex gap-2 mt-2.5" @click.stop>
          <NButton v-if="item.auto_fixable && item.status === 'pending'"
                   size="tiny" type="primary" :loading="busyId === item.id"
                   @click="resolve(item, 'fix')">AI 修复</NButton>
          <NButton v-if="item.status === 'pending'" size="tiny"
                   @click="resolve(item, 'accept')">采纳标记</NButton>
          <NButton v-if="item.status === 'pending'" size="tiny" quaternary
                   @click="resolve(item, 'dismiss')">忽略</NButton>
        </div>
      </div>

      <div class="bg-white rounded-2xl shadow-card p-4">
        <NButton block type="primary" size="large" :loading="finalizing"
                 :disabled="!doc" @click="finalize(false)">
          定稿（{{ pendingBlockers.length ? `含 ${pendingBlockers.length} 个阻断项` : '检查通过' }}）
        </NButton>
      </div>
    </div>

    <!-- 文档联动预览 -->
    <div class="flex-1 min-w-0 bg-white rounded-2xl shadow-card p-7 reader">
      <template v-if="doc">
        <div v-for="b in doc.blocks" :key="b.id" :id="'rv-' + b.id"
             class="rounded-lg px-2 py-0.5 transition-colors"
             :class="{ 'bg-amber-50 ring-1 ring-amber-300': highlightId === b.id }">
          <h1 v-if="b.type === 'heading' && b.level === 1">{{ b.text }}</h1>
          <h2 v-else-if="b.type === 'heading'">{{ b.text }}</h2>
          <p v-else-if="b.type === 'paragraph'">{{ b.text }}</p>
          <blockquote v-else-if="b.type === 'quote'">{{ b.text }}</blockquote>
          <div v-else-if="b.type === 'image'" class="my-3">
            <img v-if="b.asset_id" :src="api.absUrl(`/api/materials/${b.asset_id}/file`)"
                 class="rounded-xl max-w-full" />
          </div>
        </div>
      </template>
      <NEmpty v-else description="暂无文案" class="py-16" />
    </div>
  </div>
</template>
