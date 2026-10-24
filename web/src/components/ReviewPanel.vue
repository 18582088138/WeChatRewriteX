<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NEmpty, useDialog, useMessage } from 'naive-ui'
import { api } from '../api'
import { useAppStore } from '../stores/app'
import type { DraftDoc, ReviewItem } from '../types'

const props = defineProps<{ articleId: string }>()
const emit = defineEmits<{ (e: 'goto-publish'): void }>()
const message = useMessage()
const dialog = useDialog()
const store = useAppStore()

const review = ref<any>(null)
const items = ref<ReviewItem[]>([])
const doc = ref<DraftDoc | null>(null)
const highlightId = ref<string | null>(null)
const flashId = ref<string | null>(null)
const busyId = ref('')
const finalizing = ref(false)
const loading = ref(true)

const CAT_LABEL: Record<string, string> = {
  layout: '排版', fact: '事实', attribution: '来源',
  compliance: '合规', originality: '撞稿', ai_flavor: 'AI味',
}
const SEV_STYLE: Record<string, string> = {
  blocker: 'background: var(--pill-neg-bg); color: var(--pill-neg-ink);',
  warn: 'background: var(--pill-warn-bg); color: var(--pill-warn-ink);',
  info: 'background: var(--pill-info-bg); color: var(--pill-info-ink);',
}
const SEV_LABEL: Record<string, string> = { blocker: '阻断', warn: '警告', info: '提示' }
const SEV_EDGE: Record<string, string> = {
  blocker: 'var(--pill-neg-ink)', warn: '#E3B23C', info: 'var(--control)',
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

const pendingBlockers = computed(
  () => items.value.filter(i => i.severity === 'blocker' && ['pending', 'accepted'].includes(i.status)))
const pendingCount = computed(
  () => items.value.filter(i => ['pending', 'accepted'].includes(i.status)).length)
const scores = computed(() => review.value ? JSON.parse(review.value.scores_json || '{}') : {})

function locate(item: ReviewItem) {
  if (!item.block_id) return
  highlightId.value = item.block_id
  document.getElementById('rv-' + item.block_id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

async function resolve(item: ReviewItem, action: 'accept' | 'dismiss' | 'fix') {
  busyId.value = item.id
  try {
    const r = await api.post(`/api/review-items/${item.id}/resolve`, { action })
    if (action === 'fix') {
      // 采纳即生效：刷新文案并在对应块上高亮闪示（反馈 #6）
      await load()
      flashId.value = item.block_id || null
      if (item.block_id) {
        setTimeout(() => {
          document.getElementById('rv-' + item.block_id)
            ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }, 80)
        setTimeout(() => (flashId.value = null), 2600)
      }
      message.success(`已采纳并修复，生效于 v${r.new_version}`)
    } else {
      await load()
      if (action === 'accept') locate(item)   // 无法自动修复：定位到对应段落便于手动修改
    }
  } catch (e: any) { message.error(e.message) } finally { busyId.value = '' }
}

async function reReview() {
  try {
    await api.post(`/api/articles/${props.articleId}/advance`, { stage: 'review' })
    message.success('复审任务已提交')
    setTimeout(load, 1500)
  } catch (e: any) { message.error(e.message) }
}

async function finalize(force = false) {
  finalizing.value = true
  try {
    await api.post(`/api/articles/${props.articleId}/finalize`, { force })
    message.success('已定稿')
    emit('goto-publish')
  } catch (e: any) {
    if (String(e.message).includes('blocker')) {
      dialog.warning({
        title: '存在未处理 blocker',
        content: `${e.message}。可以回创作页修改、采纳并修复，或强制定稿（将留痕）。`,
        positiveText: '强制定稿', negativeText: '再改改',
        onPositiveClick: () => finalize(true),
      })
    } else message.error(e.message)
  } finally { finalizing.value = false }
}
</script>

<template>
  <div class="flex gap-5 items-start">
    <!-- checklist -->
    <div class="w-[430px] shrink-0 space-y-4">
      <!-- 统计条：一个容器 + 1px 分隔，等宽数字 -->
      <div class="panel flex divide-x" style="border-color: var(--border);">
        <div class="flex-1 px-4 py-3" v-for="c in [
            { label: '意见', value: items.length },
            { label: '阻断', value: pendingBlockers.length, danger: pendingBlockers.length > 0 },
            { label: '待处理', value: pendingCount },
            { label: 'AI味', value: scores.ai_flavor ? scores.ai_flavor + '/5' : '—' },
            { label: '最高相似', value: scores.originality_max_jaccard != null ? (scores.originality_max_jaccard * 100).toFixed(0) + '%' : '—' },
          ]" :key="c.label">
          <div class="text-xs" style="color: var(--faint);">{{ c.label }}</div>
          <div class="text-xl mt-0.5 num"
               :style="(c as any).danger ? 'color: var(--pill-neg-ink); font-weight: 700;' : 'color: var(--text);'">
            {{ c.value }}</div>
        </div>
      </div>

      <div class="flex items-center justify-between">
        <span class="text-xs" style="color: var(--faint);">点击条目在右侧定位对应段落</span>
        <NButton size="small" @click="reReview">重新审稿</NButton>
      </div>

      <NEmpty v-if="!loading && !items.length" description="暂无审稿意见" class="py-16" />

      <!-- 条目：面板行，左缘 severity 色条 -->
      <div class="panel divide-y">
        <div v-for="item in items" :key="item.id"
             class="px-4 py-3.5 cursor-pointer transition-colors hover:bg-[var(--raised)]"
             :style="`border-left: 3px solid ${SEV_EDGE[item.severity]};` +
                     (['dismissed', 'fixed'].includes(item.status) ? 'opacity:.55;' : '')"
             @click="locate(item)">
          <div class="flex items-center gap-2 mb-1">
            <span class="text-xs" style="color: var(--muted);">{{ CAT_LABEL[item.category] }}</span>
            <span class="text-xs px-2 py-0.5 rounded-full" :style="SEV_STYLE[item.severity]">
              {{ SEV_LABEL[item.severity] }}</span>
            <span v-if="item.status !== 'pending'" class="text-xs" style="color: var(--faint);">
              · {{ { accepted: '待手动改', dismissed: '已忽略', fixed: '已修复' }[item.status] }}</span>
          </div>
          <div class="text-sm leading-relaxed">{{ item.message }}</div>
          <div v-if="item.suggestion" class="text-xs mt-1.5" style="color: var(--faint);">
            建议：{{ item.suggestion }}</div>
          <div class="flex gap-2 mt-2.5" @click.stop>
            <NButton v-if="item.auto_fixable && item.status === 'pending'"
                     size="tiny" type="primary" :loading="busyId === item.id"
                     @click="resolve(item, 'fix')">采纳并修复</NButton>
            <NButton v-if="!item.auto_fixable && item.status === 'pending'"
                     size="tiny" @click="resolve(item, 'accept')">标记待改</NButton>
            <NButton v-if="item.status === 'pending'" size="tiny" quaternary
                     @click="resolve(item, 'dismiss')">忽略</NButton>
          </div>
        </div>
      </div>

      <NButton block type="primary" size="large" :loading="finalizing"
               :disabled="!doc" @click="finalize(false)">
        定稿{{ pendingBlockers.length ? `（含 ${pendingBlockers.length} 个阻断项）` : '' }}
      </NButton>
    </div>

    <!-- 文档联动预览 -->
    <div class="flex-1 min-w-0 panel p-7 reader">
      <template v-if="doc">
        <div v-for="b in doc.blocks" :key="b.id" :id="'rv-' + b.id"
             class="rounded-md px-2 py-0.5 transition-colors"
             :class="{ 'highlight-review': highlightId === b.id, 'flash-fixed': flashId === b.id }">
          <h1 v-if="b.type === 'heading' && b.level === 1">{{ b.text }}</h1>
          <h2 v-else-if="b.type === 'heading'">{{ b.text }}</h2>
          <p v-else-if="b.type === 'paragraph'">{{ b.text }}</p>
          <blockquote v-else-if="b.type === 'quote'">{{ b.text }}</blockquote>
          <div v-else-if="b.type === 'image'" class="my-3">
            <img v-if="b.asset_id" :src="api.absUrl(`/api/materials/${b.asset_id}/file`)"
                 class="rounded-md max-w-full" />
          </div>
        </div>
      </template>
      <NEmpty v-else description="暂无文案" class="py-16" />
    </div>
  </div>
</template>
