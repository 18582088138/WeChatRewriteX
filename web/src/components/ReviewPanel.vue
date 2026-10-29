<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { NButton, NEmpty, useDialog, useMessage } from 'naive-ui'
import { api } from '../api'
import { useAppStore } from '../stores/app'
import type { DraftDoc, DraftView, ReviewItem } from '../types'

const props = defineProps<{ articleId: string }>()
const emit = defineEmits<{ (e: 'goto-publish'): void }>()
const message = useMessage()
const dialog = useDialog()
const store = useAppStore()
const reviewCurrent = ref(false)
const reviewChanged = ref(false)
const saveBusy = ref(false)

const review = ref<any>(null)
const items = ref<ReviewItem[]>([])
const doc = ref<DraftDoc | null>(null)
const draftId = ref('')
const highlightId = ref<string | null>(null)
const flashId = ref<string | null>(null)
const busyId = ref('')
const finalizing = ref(false)
const loading = ref(true)
const panelOpen = ref(true)

/* 并排布局 + 拖拽停靠（V1.10）：默认右侧并排；按住面板头部拖出为悬浮，
   松手时贴近左右边缘则吸附停靠到对应侧。 */
type Dock = 'left' | 'right' | 'float'
const dock = ref<Dock>('right')
const floatPos = ref({ x: 120, y: 118 })
const dragging = ref(false)
let dragOffset = { x: 0, y: 0 }
const panelRef = ref<HTMLElement | null>(null)

function onHeaderDown(e: MouseEvent) {
  if ((e.target as HTMLElement).closest('button')) return   // 按钮不触发拖拽
  dragging.value = true
  const rect = panelRef.value?.getBoundingClientRect()
  if (rect) dragOffset = { x: e.clientX - rect.left, y: e.clientY - rect.top }
  if (dock.value !== 'float' && rect) {
    floatPos.value = { x: rect.left, y: rect.top }
    dock.value = 'float'
  }
  e.preventDefault()
}
function onMove(e: MouseEvent) {
  if (!dragging.value) return
  floatPos.value = {
    x: Math.min(Math.max(e.clientX - dragOffset.x, 0), window.innerWidth - 120),
    y: Math.min(Math.max(e.clientY - dragOffset.y, 56), window.innerHeight - 120),
  }
}
function onUp(e: MouseEvent) {
  if (!dragging.value) return
  dragging.value = false
  // 边缘吸附：松手点距左/右边缘 90px 内则停靠
  if (e.clientX < 90) dock.value = 'left'
  else if (e.clientX > window.innerWidth - 90) dock.value = 'right'
}
onUnmounted(() => {
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
})

/* 双击编辑（对齐创作分页交互） */
const editingId = ref<string | null>(null)
const editText = ref('')

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

let generation = 0
let controller: AbortController | null = null
let pendingRefresh = false
const hasLocalEdit = () => !!(editingId.value || saveBusy.value || busyId.value || finalizing.value)
async function load(preserveEdits = false) {
  if (preserveEdits && hasLocalEdit()) { pendingRefresh = true; return }
  pendingRefresh = false
  const current = ++generation
  controller?.abort()
  controller = new AbortController()
  const signal = controller.signal
  loading.value = true
  try {
    const context = await api.get<{ draft: DraftView | null; review: any }>(`/api/articles/${props.articleId}/review-context`, signal)
    if (current !== generation) return
    if (preserveEdits && hasLocalEdit()) { pendingRefresh = true; return }
    const r = context.review, d = context.draft
    review.value = r?.review || null
    reviewCurrent.value = !!r?.current
    reviewChanged.value = !!r?.content_changed
    items.value = r?.items || []
    doc.value = d?.draft.doc || null
    draftId.value = d?.draft.id || ''
  } catch (error: any) {
    if (error.name !== 'AbortError') message.error(error.message)
  } finally { if (current === generation) loading.value = false }
}
watch(() => store.articleTicks[props.articleId] || 0, () => load(true))
watch(hasLocalEdit, blocked => { if (!blocked && pendingRefresh) void load(true) })
onUnmounted(() => controller?.abort())
onMounted(() => {
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  load()
})

const pendingBlockers = computed(
  () => items.value.filter(i => i.severity === 'blocker' && ['pending', 'accepted'].includes(i.status)))
const pendingCount = computed(
  () => items.value.filter(i => ['pending', 'accepted'].includes(i.status)).length)
const scores = computed(() => review.value ? JSON.parse(review.value.scores_json || '{}') : {})

/** 块 id → 段落序号（1 起），供排序与位置提示 */
const blockOrder = computed(() => {
  const m = new Map<string, number>()
  doc.value?.blocks.forEach((b, i) => m.set(b.id, i + 1))
  return m
})

/** 审稿意见按对应段落在原文中的先后顺序排列（无锚定段落的排最后，同级严重度优先） */
const sortedItems = computed(() => {
  const INF = Number.MAX_SAFE_INTEGER
  const sev: Record<string, number> = { blocker: 0, warn: 1, info: 2 }
  return [...items.value].sort((a, b) => {
    const ia = a.block_id ? (blockOrder.value.get(a.block_id) ?? INF) : INF
    const ib = b.block_id ? (blockOrder.value.get(b.block_id) ?? INF) : INF
    if (ia !== ib) return ia - ib
    return (sev[a.severity] ?? 3) - (sev[b.severity] ?? 3)
  })
})

function paraNo(item: ReviewItem): string {
  const n = item.block_id ? blockOrder.value.get(item.block_id) : undefined
  return n ? `¶${n}` : ''
}

function locate(item: ReviewItem) {
  if (!item.block_id || !blockOrder.value.has(item.block_id)) return
  highlightId.value = item.block_id
  document.getElementById('rv-' + item.block_id)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

/* ---- 双击编辑（与创作分页一致：双击进入、点外/Esc 退出、定稿前保存到当前工作版本） ---- */
function dblclickBlock(b: any) {
  if (busyId.value || finalizing.value || ['image', 'video', 'divider'].includes(b.type)) return
  editingId.value = b.id
  editText.value = b.text
}
async function saveEdit() {
  if (!editingId.value || !doc.value || saveBusy.value) return
  const b = doc.value.blocks.find(x => x.id === editingId.value)
  if (!b || b.text === editText.value) { editingId.value = null; return }
  saveBusy.value = true
  try {
    const r = await api.put(`/api/drafts/${draftId.value}/edit`,
      { expected_revision: doc.value?.edit_revision, ops: [{ op: 'update', block_id: b.id, text: editText.value }] })
    editingId.value = null
    message.success(`已保存为 v${r.version}`)
    await load()
  } catch (e: any) { message.error(e.message) } finally { saveBusy.value = false }
}

async function resolve(item: ReviewItem, action: 'accept' | 'dismiss' | 'fix') {
  if (busyId.value || finalizing.value || saveBusy.value || editingId.value || loading.value) return
  busyId.value = item.id
  try {
    const r = await api.post(`/api/review-items/${item.id}/resolve`, { action, expected_revision: doc.value?.edit_revision })
    store.invalidateArticle(props.articleId)
    if (action === 'fix') {
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
      if (action === 'accept') locate(item)
    }
  } catch (e: any) { message.error(e.message) } finally { busyId.value = '' }
}

async function reReview() {
  try {
    await api.post(`/api/articles/${props.articleId}/advance`, { stage: 'review' })
    message.success('复审任务已提交')
    await load(true)
  } catch (e: any) { message.error(e.message) }
}

async function finalize(force = false) {
  if (!doc.value || finalizing.value || saveBusy.value || editingId.value || loading.value || busyId.value) return
  finalizing.value = true
  try {
    const r = await api.post(`/api/articles/${props.articleId}/finalize`, { force, expected_version: doc.value?.version, expected_revision: doc.value?.edit_revision })
    message.success(r.already_finalized ? '已是定稿版本（无新改动）' : `已定稿为 v${r.version}`)
    await load()
    store.invalidateArticle(props.articleId)
    if (!r.already_finalized) emit('goto-publish')
  } catch (e: any) {
    if (e.status === 409 && /blocker|审稿/.test(String(e.message))) {
      dialog.warning({
        title: '审稿确认未完成',
        content: `${e.message}。可以双击正文修改、采纳并修复，或强制定稿（将留痕）。`,
        positiveText: '强制定稿', negativeText: '再改改',
        onPositiveClick: () => finalize(true),
      })
    } else message.error(e.message)
  } finally { finalizing.value = false }
}
</script>

<template>
  <div class="review-root" :class="{ 'is-float': dock === 'float' }">
    <!-- 中央阅读区：双击文本块编辑（对齐创作分页） -->
    <main class="reader panel p-7">
      <NEmpty v-if="!doc && !loading" description="暂无文案" class="py-16" />
      <template v-if="doc">
        <div v-for="b in doc.blocks" :key="b.id" :id="'rv-' + b.id"
             class="rounded-md px-2 py-0.5 transition-colors reader-block"
             :class="{ 'highlight-review': highlightId === b.id, 'flash-fixed': flashId === b.id }">
          <textarea v-if="editingId === b.id" v-model="editText" @blur="saveEdit"
                    @keyup.esc="editingId = null" @click.stop
                    class="w-full outline-none bg-transparent text-[15px] leading-[1.9] resize-none"
                    :rows="Math.max(3, Math.ceil(editText.length / 40))" v-focus />
          <template v-else>
            <h1 v-if="b.type === 'heading' && b.level === 1"
                @dblclick="dblclickBlock(b)">{{ b.text }}</h1>
            <h2 v-else-if="b.type === 'heading'" @dblclick="dblclickBlock(b)">{{ b.text }}</h2>
            <p v-else-if="b.type === 'paragraph'" @dblclick="dblclickBlock(b)">{{ b.text }}</p>
            <blockquote v-else-if="b.type === 'quote'" @dblclick="dblclickBlock(b)">{{ b.text }}</blockquote>
            <div v-else-if="b.type === 'image'" class="my-3">
              <img v-if="b.asset_id" :src="api.absUrl(`/api/materials/${b.asset_id}/file`)"
                   class="rounded-md max-w-full" />
            </div>
            <div v-else-if="b.type === 'video'" class="my-3">
              <video v-if="b.asset_id" :src="api.absUrl(`/api/materials/${b.asset_id}/file`)"
                     controls preload="metadata" class="rounded-md max-w-full"
                     style="max-height: 420px; background: #000;"></video>
              <div v-if="b.caption" class="text-xs text-center mt-1"
                   style="color: var(--faint);">{{ b.caption }}</div>
            </div>
          </template>
        </div>
        <div class="text-center text-xs mt-6" style="color: var(--faint);">
          双击文本块即可编辑 · 点击意见条目定位对应段落 · 按住意见面板头部可拖动（贴边吸附停靠）
        </div>
      </template>
    </main>

    <!-- 审稿意见面板：并排（左右停靠）或悬浮拖动 -->
    <button v-if="!panelOpen" class="review-fab" @click="panelOpen = true">
      审稿意见 · {{ pendingCount }}<span v-if="pendingBlockers.length" style="color: var(--pill-neg-ink);">
        ⬤ {{ pendingBlockers.length }}</span>
    </button>

    <aside v-else ref="panelRef" class="review-panel panel" :class="'dock-' + dock"
           :style="dock === 'float' ? { left: floatPos.x + 'px', top: floatPos.y + 'px' } : {}">
      <div class="flex items-center justify-between px-3 py-2 shrink-0 panel-head"
           :class="{ 'cursor-grab': true, 'cursor-grabbing': dragging }"
           style="border-bottom: 1px solid var(--rule);"
           title="按住拖动，贴近左右边缘停靠"
           @mousedown="onHeaderDown">
        <span class="text-xs font-semibold" style="color: var(--muted);">
          ⠿ 审稿意见 · 待处理 {{ pendingCount }}</span>
        <div class="flex items-center gap-1">
          <NButton size="tiny" @click="reReview">重新审稿</NButton>
          <button class="text-xs px-1 hover:underline" style="color: var(--faint);"
                  @click="panelOpen = false">收起</button>
        </div>
      </div>

      <!-- 统计条 -->
      <div class="flex divide-x shrink-0" style="border-bottom: 1px solid var(--rule);">
        <div class="flex-1 px-3 py-2" v-for="c in [
            { label: '意见', value: items.length },
            { label: '阻断', value: pendingBlockers.length, danger: pendingBlockers.length > 0 },
            { label: 'AI味', value: scores.ai_flavor ? scores.ai_flavor + '/5' : '—' },
            { label: '相似', value: scores.originality_max_jaccard != null ? (scores.originality_max_jaccard * 100).toFixed(0) + '%' : '—' },
          ]" :key="c.label">
          <div class="text-[11px]" style="color: var(--faint);">{{ c.label }}</div>
          <div class="text-base num" :style="(c as any).danger ? 'color: var(--pill-neg-ink); font-weight: 700;' : ''">
            {{ c.value }}</div>
        </div>
      </div>

      <div class="review-items">
        <p v-if="review && !reviewCurrent" class="text-sm mb-3" style="color: var(--pill-warn-ink);">当前意见属于旧版本或迟到审稿，请重新审稿。</p>
        <p v-if="reviewCurrent && reviewChanged" class="text-xs mb-3" style="color: var(--muted);">同一工作版本内可继续处理意见；正文已改变，建议定稿前复审，定稿时会复核规则。</p>
          <p v-if="scores.coverage === 'rules_only'" class="text-xs mb-3" style="color: var(--muted);">已完成规则审稿；未配置 AI 审稿模型，事实与来源需人工确认。</p>
        <p v-if="scores.coverage === 'failed'" class="text-sm mb-3" style="color: var(--pill-neg-ink);">AI 审稿失败，请重试或在人工确认后强制定稿。</p>
        <NEmpty v-if="!loading && !items.length" description="暂无审稿意见" class="py-12" />
        <div v-for="item in sortedItems" :key="item.id"
             class="px-3.5 py-3 cursor-pointer transition-colors hover:bg-[var(--raised)] review-item"
             :style="`border-left: 3px solid ${SEV_EDGE[item.severity]};` +
                     (['dismissed', 'fixed'].includes(item.status) ? 'opacity:.55;' : '')"
             @click="locate(item)">
          <div class="flex items-center gap-2 mb-1">
            <span v-if="paraNo(item)" class="text-[10px] num px-1 rounded"
                  style="background: var(--raised); color: var(--faint);">{{ paraNo(item) }}</span>
            <span class="text-xs" style="color: var(--muted);">{{ CAT_LABEL[item.category] }}</span>
            <span class="text-xs px-2 py-0.5 rounded-full" :style="SEV_STYLE[item.severity]">
              {{ SEV_LABEL[item.severity] }}</span>
            <span v-if="item.status !== 'pending'" class="text-xs" style="color: var(--faint);">
              · {{ { accepted: '待手动改', dismissed: '已忽略', fixed: '已修复' }[item.status] }}</span>
          </div>
          <div class="text-sm leading-relaxed">{{ item.message }}</div>
          <div v-if="item.suggestion" class="text-xs mt-1.5" style="color: var(--faint);">
            建议：{{ item.suggestion }}</div>
          <div class="flex gap-2 mt-2" @click.stop>
            <NButton v-if="item.auto_fixable && item.status === 'pending'"
                     size="tiny" type="primary" :loading="busyId === item.id" :disabled="!!busyId || saveBusy || !!editingId || finalizing || !reviewCurrent"
                     @click="resolve(item, 'fix')">采纳并修复</NButton>
            <NButton v-if="!item.auto_fixable && item.status === 'pending'"
                     size="tiny" :disabled="!!busyId || saveBusy || !!editingId || finalizing || !reviewCurrent" @click="resolve(item, 'accept')">标记待改</NButton>
            <NButton v-if="item.status === 'pending'" size="tiny" quaternary
                     @click="resolve(item, 'dismiss')">忽略</NButton>
          </div>
        </div>
      </div>

      <div class="p-3 shrink-0" style="border-top: 1px solid var(--rule);">
        <NButton block type="primary" :loading="finalizing"
                 :disabled="!doc || saveBusy || !!editingId || loading || !!busyId" @click="finalize(false)">
          定稿{{ pendingBlockers.length ? `（含 ${pendingBlockers.length} 个阻断项）` : '' }}
        </NButton>
        <div class="text-[11px] mt-1.5 text-center" style="color: var(--faint);">
          定稿生成可回滚的正式版本；定稿后仍可继续编辑，再次定稿生成新版本。
        </div>
      </div>
    </aside>
  </div>
</template>

<script lang="ts">
export default {
  directives: { focus: { mounted: (el: HTMLElement) => el.focus() } },
}
</script>

<style scoped>
.review-root { display: flex; gap: 20px; align-items: flex-start; }
.reader { flex: 1; min-width: 0; min-height: 62vh; }
.review-root.is-float .reader { max-width: 860px; margin: 0 auto; }
.review-root.is-float { display: block; }

.reader-block h1 { font-size: 22px; font-weight: 700; margin: 0 0 20px; line-height: 1.35; }
.reader-block h2 { font-size: 17px; font-weight: 700; margin: 26px 0 10px; }
.reader-block p { line-height: 1.9; font-size: 15px; color: #2A2926; margin-bottom: 1em; text-align: justify; }
.reader-block blockquote { border-left: 3px solid var(--accent); background: var(--raised);
  padding: 10px 16px; margin: 0 0 16px; color: #4A463D; font-size: 14px; line-height: 1.8; }

/* 审稿意见面板：并排停靠（默认右侧，可停左侧）；拖出为悬浮 */
.review-panel {
  width: min(430px, 40vw); max-height: calc(100vh - 150px);
  display: flex; flex-direction: column;
  background: var(--surface); flex-shrink: 0;
  position: sticky; top: 96px;
}
.dock-left { order: -1; }
.review-panel.dock-float {
  position: fixed; top: 118px; z-index: 30;
  box-shadow: 0 8px 30px rgba(20,20,20,.14);
  max-height: calc(100vh - 140px);
}
.panel-head { user-select: none; }
.review-items { overflow-y: auto; flex: 1; }
.review-item + .review-item { border-top: 1px solid var(--rule); }
.review-fab {
  position: fixed; right: 20px; top: 118px; z-index: 30;
  padding: 8px 14px; border-radius: 999px; font-size: 12px;
  background: var(--surface); border: 1px solid var(--border);
  color: var(--muted); box-shadow: 0 4px 16px rgba(20,20,20,.12); cursor: pointer;
}
.review-fab:hover { border-color: var(--accent); color: var(--text); }
</style>
