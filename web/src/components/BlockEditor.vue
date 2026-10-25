<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { NButton, NInput, NModal, NSelect, NSpin, useDialog, useMessage } from 'naive-ui'
import { api } from '../api'
import { useAppStore } from '../stores/app'
import type { Block, DraftDoc, Material } from '../types'

const props = defineProps<{ articleId: string }>()
const emit = defineEmits<{ (e: 'goto-review'): void }>()
const message = useMessage()
const dialog = useDialog()
const store = useAppStore()

/* ================= 数据 ================= */
const draftId = ref('')
const doc = ref<DraftDoc | null>(null)
const versions = ref<any[]>([])
const loading = ref(false)
const article = ref<any>(null)
const sessionMaterials = ref<Material[]>([])

/* ================= 侧窗（反馈三：交互规则重定义） =================
   宽屏：常驻 + sticky 跟随滚动；窄屏：自动收起为边缘标记条，
   悬停 0.5s 弹出、离开 2s 收回；选中文字快捷唤起右窗。 */
const wide = ref(window.innerWidth >= 1200)
const leftOpen = ref(true)
const rightOpen = ref(true)
let mq: MediaQueryList
let openTimer: ReturnType<typeof setTimeout> | null = null
let closeTimer: ReturnType<typeof setTimeout> | null = null

function onMq(e: MediaQueryListEvent) {
  wide.value = e.matches
  leftOpen.value = e.matches
  rightOpen.value = e.matches
}
function edgeHover(side: 'left' | 'right') {
  if (wide.value) return
  if (closeTimer) clearTimeout(closeTimer)
  openTimer = setTimeout(() => {               // 0.5s 防抖弹出
    if (side === 'left') leftOpen.value = true
    else rightOpen.value = true
  }, 500)
}
function edgeLeave() {
  if (openTimer) { clearTimeout(openTimer); openTimer = null }
}
function panelLeave(side: 'left' | 'right') {
  if (wide.value) return
  if (openTimer) { clearTimeout(openTimer); openTimer = null }
  closeTimer = setTimeout(() => {              // 2s 防抖收回
    if (side === 'left') leftOpen.value = false
    else rightOpen.value = false
  }, 2000)
}
function panelEnter() {
  if (closeTimer) { clearTimeout(closeTimer); closeTimer = null }
}
function onSelectText() {                       // 选中文字快捷唤起右窗（仅窄屏收起态）
  if (wide.value || rightOpen.value) return
  const sel = window.getSelection()
  if (sel && !sel.isCollapsed && centerRef.value?.contains(sel.anchorNode)) {
    rightOpen.value = true
  }
}

/* ================= 编辑器状态 ================= */
const centerRef = ref<HTMLElement | null>(null)
const selectedId = ref<string | null>(null)
const editingId = ref<string | null>(null)
const editText = ref('')
const aiModal = ref(false)
const aiInstruction = ref('')
const aiBusy = ref(false)
const aiTargets = ref<string[]>([])
const wholeArticle = ref(false)
const lightboxUrl = ref('')
const imgModal = ref(false)
const imgBlockId = ref('')
const insertModal = ref(false)
const insertIds = ref<string[]>([])
const insertInstruction = ref('')
const dropTargetId = ref<string | null>(null)   // 拖拽插入位置指示

/* 标题&副标题（置顶块） + 底部信息窗（总结/关键词/参考链接） */
const metaTitle = ref('')
const metaSubtitle = ref('')
const metaTitleAlts = ref('')
const metaOneLiner = ref('')
const metaKeywords = ref('')
const metaRefLinks = ref('')
const metaEditing = ref<string | null>(null)

const isLatest = computed(() =>
  !versions.value.length || doc.value?.version === versions.value[0]?.version)
const finalized = computed(() => versions.value[0]?.status === 'finalized')
const textBlocks = computed(() =>
  doc.value?.blocks.filter(b => ['heading', 'paragraph', 'quote'].includes(b.type)) ?? [])

/** 渲染块：跳过第一个一级标题（与置顶标题块同源，防重复） */
const visibleBlocks = computed(() => {
  const blocks = doc.value?.blocks ?? []
  const firstH1 = blocks.findIndex(b => b.type === 'heading' && b.level === 1)
  return blocks.filter((_, i) => i !== firstH1)
})

function assetUrl(assetId: string) { return api.absUrl(`/api/materials/${assetId}/file`) }

/* ================= 加载 ================= */
async function load(version?: number) {
  loading.value = true
  try {
    const r = await api.get(`/api/articles/${props.articleId}/draft` +
                            (version ? `?version=${version}` : ''))
    doc.value = r.draft.doc
    draftId.value = r.draft.id
    versions.value = r.versions
    syncMetaForm()
  } catch (e) { console.error('draft load failed', e) } finally { loading.value = false }
}

async function loadArticle() {
  article.value = await api.get(`/api/articles/${props.articleId}`)
  const ids: string[] = article.value.selected_material_ids || []
  const all = (await api.get(`/api/articles/${props.articleId}/materials?scope=article`)).materials
  // 修复「导入素材与左侧展示不一致」：会话为空时展示本篇全部已导入素材
  sessionMaterials.value = ids.length
    ? all.filter((m: Material) => ids.includes(m.id))
    : all
}

function syncMetaForm() {
  const d = doc.value
  if (!d) return
  const [first, ...rest] = d.meta.title_candidates || []
  metaTitle.value = first || ''
  metaSubtitle.value = d.meta.subtitle || ''
  metaTitleAlts.value = rest.join('\n')
  metaOneLiner.value = d.meta.one_liner || ''
  metaKeywords.value = (d.meta.keywords || []).map(k => `#${k}`).join('，')
  metaRefLinks.value = (d.meta.ref_links || []).map(x => `${x.title} | ${x.url}`).join('\n')
}

onMounted(async () => {
  mq = window.matchMedia('(min-width: 1200px)')
  mq.addEventListener('change', onMq)
  wide.value = mq.matches
  leftOpen.value = mq.matches
  rightOpen.value = mq.matches
  document.addEventListener('selectstart', onSelectText)
  await load()
  await loadArticle()
})
onUnmounted(() => {
  mq?.removeEventListener('change', onMq)
  document.removeEventListener('selectstart', onSelectText)
})
watch(() => store.workbenchTick, () => { load(); loadArticle() })

/* ================= 会话素材（左窗「创作素材」） ================= */
async function removeFromSession(m: Material) {
  let ids: string[] = article.value?.selected_material_ids || []
  if (!ids.length) {
    // 会话为空 = 全量模式：移除 = 显式勾选其余全部
    ids = sessionMaterials.value.map(x => x.id).filter(x => x !== m.id)
  } else {
    ids = ids.filter(x => x !== m.id)
  }
  await api.put(`/api/articles/${props.articleId}/selection`, { material_ids: ids })
  message.success('已从本次创作会话移除（原始素材保留）')
  await loadArticle()
}

function onMaterialDrag(e: DragEvent, m: Material) {
  e.dataTransfer?.setData('text/material-id', m.id)
  e.dataTransfer!.effectAllowed = 'copy'
}

/** 拖拽素材到编辑区指定块位置 → 在该块后新建素材块（反馈 一.5） */
function onBlockDragOver(e: DragEvent, b: Block) {
  if (e.dataTransfer?.types.includes('text/material-id')) {
    e.preventDefault()
    dropTargetId.value = b.id
  }
}
async function onBlockDrop(e: DragEvent, b: Block) {
  e.preventDefault()
  dropTargetId.value = null
  const mid = e.dataTransfer?.getData('text/material-id')
  if (!mid || !draftId.value) return
  const m = sessionMaterials.value.find(x => x.id === mid)
  if (!m) return
  const op = m.kind === 'text'
    ? { op: 'insert_after', block_id: b.id, block_type: 'quote', text: m.title }
    : { op: 'insert_after', block_id: b.id,
        block_type: m.kind === 'video' ? 'video' : 'image', asset_id: m.id, caption: m.title }
  try {
    const r = await api.put(`/api/drafts/${draftId.value}/edit`, { ops: [op] })
    message.success(`已插入素材（v${r.version}）`)
    await load()
  } catch (err: any) { message.error(err.message) }
}

async function insertToDoc(m: Material) {
  if (!doc.value || !draftId.value) return
  const anchor = selectedId.value || (doc.value.blocks.at(-1)?.id ?? null)
  const op = m.kind === 'text'
    ? { op: 'insert_after', block_id: anchor, block_type: 'quote', text: m.title }
    : { op: 'insert_after', block_id: anchor,
        block_type: m.kind === 'video' ? 'video' : 'image', asset_id: m.id, caption: m.title }
  try {
    const r = await api.put(`/api/drafts/${draftId.value}/edit`, { ops: [op] })
    message.success(`已插入（v${r.version}）`)
    await load()
  } catch (e: any) { message.error(e.message) }
}

/* ================= 块编辑（Notebook） ================= */
function clickBlock(b: Block) {
  selectedId.value = b.id
  store.anchorBlockId = b.id
}
function dblclickBlock(b: Block) {
  if (!isLatest.value) { message.warning('历史版本只读，请先在右侧回滚或回到最新版'); return }
  if (finalized.value) { message.warning('已定稿；如需修改请先在审稿页回炉'); return }
  if (b.type === 'image' || b.type === 'video') { openImagePicker(b.id); return }
  if (b.type === 'divider') return
  editingId.value = b.id
  editText.value = b.text
}
function onClickOutside() {
  if (editingId.value) saveEdit()
}
async function saveEdit() {
  if (!editingId.value || !doc.value) return
  const b = doc.value.blocks.find(x => x.id === editingId.value)
  if (b && b.text !== editText.value) {
    try {
      const r = await api.put(`/api/drafts/${draftId.value}/edit`,
        { ops: [{ op: 'update', block_id: b.id, text: editText.value }] })
      message.success(`已保存为 v${r.version}` + (r.recheck_enqueued ? '（已触发复审）' : ''))
      await load()
    } catch (e: any) { message.error(e.message) }
  }
  editingId.value = null
}

async function addBlock(afterId: string | null) {
  if (!doc.value || !draftId.value) return
  try {
    const r = await api.put(`/api/drafts/${draftId.value}/edit`,
      { ops: [{ op: 'insert_after', block_id: afterId, block_type: 'paragraph', text: '' }] })
    await load()
    const d = doc.value!
    const idx = afterId ? d.blocks.findIndex(x => x.id === afterId) + 1 : d.blocks.length - 1
    const nb = d.blocks[idx]
    if (nb) { editingId.value = nb.id; editText.value = '' }
  } catch (e: any) { message.error(e.message) }
}

async function removeBlock(blockId: string) {
  const r = await api.put(`/api/drafts/${draftId.value}/edit`,
    { ops: [{ op: 'remove', block_id: blockId }] })
  message.success(`已删除块（v${r.version}）`)
  selectedId.value = null
  await load()
}

/* ================= AI 重写（右窗工具） ================= */
function openAi(mode: 'rewrite' | 'shorten' | 'expand' | 'custom' | 'whole') {
  const presets = {
    rewrite: '换一种表达，保持事实不变，更自然流畅',
    shorten: '压缩到一半字数，保留事实',
    expand: '展开补充背景解释，不编造数字',
    custom: '',
    whole: '',
  }
  wholeArticle.value = mode === 'whole'
  if (wholeArticle.value) {
    aiTargets.value = textBlocks.value.map(b => b.id)
    aiInstruction.value = '整篇按风格包重新润色：保持事实与结构，统一语气'
  } else {
    if (!selectedId.value) return
    aiTargets.value = [selectedId.value]
    aiInstruction.value = (presets as any)[mode]
  }
  aiModal.value = true
}

async function runAi() {
  aiBusy.value = true
  try {
    const r = await api.post(`/api/drafts/${draftId.value}/regenerate`,
      { block_ids: aiTargets.value, instruction: aiInstruction.value })
    message.success(`已生成 v${r.version}` + (r.recheck_enqueued ? '（改动较大，已触发复审）' : ''))
    aiModal.value = false
    await load()
  } catch (e: any) { message.error(e.message) } finally { aiBusy.value = false }
}

/* ================= 版本管理（右窗） ================= */
function doRollback(v: number) {
  dialog.warning({
    title: `回滚到 v${v}？`,
    content: '将按块级变更日志重建该版本状态，并保存为新版本（当前状态不丢失，可再回滚回来）。',
    positiveText: '回滚', negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const r = await api.post(`/api/articles/${props.articleId}/rollback`, { version: v })
        message.success(`已回滚到 v${r.rolled_back_to}（存为 v${r.version}）`)
        await load()
      } catch (e: any) { message.error(e.message) }
    },
  })
}

/* ================= 标题/副标题/信息窗保存 ================= */
async function saveTitle() {
  if (!draftId.value || !metaTitle.value.trim()) return
  const ops: any[] = [
    { op: 'update_meta', field: 'title_selected', value: metaTitle.value.trim() },
    { op: 'update_meta', field: 'title_candidates',
      value: [metaTitle.value.trim(),
              ...metaTitleAlts.value.split('\n').map(s => s.trim()).filter(Boolean)] },
  ]
  try {
    const r = await api.put(`/api/drafts/${draftId.value}/edit`, { ops })
    message.success(`标题已保存（v${r.version}）` + (r.folder_renamed ? '；项目文件夹已同步改名' : ''))
    metaEditing.value = null
    await load(); await loadArticle()
  } catch (e: any) { message.error(e.message) }
}

async function saveSubtitle() {
  if (!draftId.value) return
  try {
    const r = await api.put(`/api/drafts/${draftId.value}/edit`,
      { ops: [{ op: 'update_meta', field: 'subtitle', value: metaSubtitle.value }] })
    message.success(`副标题已保存（v${r.version}）`)
    metaEditing.value = null
    await load()
  } catch (e: any) { message.error(e.message) }
}

async function saveMeta(field: 'one_liner' | 'keywords' | 'ref_links') {
  if (!draftId.value) return
  let op: any
  if (field === 'one_liner') {
    op = { op: 'update_meta', field: 'one_liner', value: metaOneLiner.value }
  } else if (field === 'keywords') {
    const kws = metaKeywords.value.split(/[，,]/).map(s => s.trim().replace(/^#/, '')).filter(Boolean)
    op = { op: 'update_meta', field: 'keywords', value: kws }
  } else {
    const links = metaRefLinks.value.split('\n').map(line => {
      const [t, u] = line.split('|').map(s => s.trim())
      return t || u ? { title: t || u, url: u || '' } : null
    }).filter(Boolean)
    op = { op: 'update_meta', field: 'ref_links', value: links }
  }
  try {
    const r = await api.put(`/api/drafts/${draftId.value}/edit`, { ops: [op] })
    message.success(`已保存（v${r.version}）`)
    metaEditing.value = null
    await load()
  } catch (e: any) { message.error(e.message) }
}

/* ================= 图片 ================= */
const imageMaterials = ref<Material[]>([])
async function openImagePicker(blockId: string) {
  imgBlockId.value = blockId
  const r = await api.get(`/api/articles/${props.articleId}/materials?scope=article&kind=image`)
  imageMaterials.value = r.materials.filter((m: Material) => m.fetch_status === 'ok')
  imgModal.value = true
}
async function replaceImage(m: Material) {
  try {
    const r = await api.put(`/api/drafts/${draftId.value}/edit`,
      { ops: [{ op: 'replace_image', block_id: imgBlockId.value, asset_id: m.id }] })
    message.success(`已换图（v${r.version}）`)
    imgModal.value = false
    await load()
  } catch (e: any) { message.error(e.message) }
}

/* ================= 融合插入（素材页触发） ================= */
function openInsertRefs(ids: string[]) {
  insertIds.value = ids
  insertInstruction.value = ''
  insertModal.value = true
}
defineExpose({ openInsertRefs })

async function runInsert() {
  aiBusy.value = true
  try {
    const r = await api.post(`/api/drafts/${draftId.value}/insert-refs`, {
      material_ids: insertIds.value,
      after_block_id: store.anchorBlockId,
      instruction: insertInstruction.value,
    })
    message.success(`已融合插入（v${r.version}）`)
    insertModal.value = false
    await load()
  } catch (e: any) { message.error(e.message) } finally { aiBusy.value = false }
}
</script>

<template>
  <div class="create-wb" :class="{ narrow: !wide }" @click="onClickOutside">
    <!-- 左边缘标记（窄屏收起态的视觉提示） -->
    <div v-if="!leftOpen" class="edge-marker left" @mouseenter="edgeHover('left')" @mouseleave="edgeLeave">
      <span>创<br>作<br>素<br>材</span>
    </div>
    <div v-if="!rightOpen" class="edge-marker right" @mouseenter="edgeHover('right')" @mouseleave="edgeLeave">
      <span>工<br>具</span>
    </div>

    <!-- ============ 左侧【创作素材】窗口 ============ -->
    <aside class="side-panel left-panel panel" :class="{ hidden: !leftOpen }"
           @mouseenter="panelEnter" @mouseleave="panelLeave('left')">
      <div class="flex items-center justify-between px-3 py-2" style="border-bottom: 1px solid var(--rule);">
        <span class="text-xs font-semibold" style="color: var(--muted);">创作素材</span>
        <button class="text-xs hover:underline" style="color: var(--faint);" @click="leftOpen = false">收起</button>
      </div>
      <div class="p-2 space-y-2 overflow-auto panel-body">
        <div v-if="!sessionMaterials.length" class="text-xs p-2" style="color: var(--faint);">
          本篇暂无已导入素材。到素材库勾选后点「导入」。
        </div>
        <div v-for="m in sessionMaterials" :key="m.id" class="session-item rounded-md"
             draggable="true" @dragstart="onMaterialDrag($event, m)"
             style="border: 1px solid var(--rule);" title="可拖拽到右侧正文指定位置">
          <img v-if="m.kind === 'image' && m.url" :src="api.absUrl(m.url)"
               class="w-full aspect-video object-cover rounded-t-md cursor-zoom-in"
               @click.stop="lightboxUrl = api.absUrl(m.url)" />
          <div v-else class="px-2 py-3 text-xs" style="color: var(--muted);">
            {{ { text: '文章', video: '视频', audio: '音频', doc: '文档', link: '链接' }[m.kind] || m.kind }} ·
            {{ m.title || m.id }}
          </div>
          <div class="flex items-center justify-between px-1.5 py-1">
            <button class="text-[11px] hover:underline" style="color: var(--accent-ink);"
                    @click.stop="insertToDoc(m)">插入正文</button>
            <button class="text-[11px] hover:underline" style="color: var(--faint);"
                    @click.stop="removeFromSession(m)">移除</button>
          </div>
        </div>
      </div>
    </aside>

    <!-- ============ 中央 Notebook 主编辑区 ============ -->
    <main ref="centerRef" class="nb-center panel">
      <NSpin :show="loading">
        <div v-if="!doc && !loading" class="py-20 text-center">
          <p class="text-[15px]" style="color: var(--muted);">还没有文案。</p>
          <p class="text-sm mt-2" style="color: var(--faint);">收集完成后，点顶部「开始创作」。</p>
        </div>

        <template v-if="doc">
          <!-- 标题 & 副标题（置顶块，反馈 一.2；大号加粗 / 常规斜体） -->
          <div class="mb-7">
            <h1 v-if="metaEditing !== 'title'" class="doc-title" @dblclick.stop="metaEditing = 'title'">
              {{ metaTitle || '（双击输入标题）' }}</h1>
            <div v-else class="space-y-1" @click.stop>
              <input v-model="metaTitle" class="info-input text-lg font-bold" v-focus />
              <textarea v-model="metaTitleAlts" class="info-input" rows="2"
                        placeholder="备选标题，每行一个" />
              <div class="flex gap-2">
                <button class="text-xs hover:underline" style="color: var(--accent-ink);"
                        @click="saveTitle">保存</button>
                <button class="text-xs hover:underline" style="color: var(--faint);"
                        @click="metaEditing = null">取消</button>
              </div>
            </div>
            <p v-if="metaEditing !== 'subtitle'" class="doc-subtitle" @dblclick.stop="metaEditing = 'subtitle'">
              {{ metaSubtitle || '（双击输入副标题）' }}</p>
            <div v-else class="mt-1" @click.stop>
              <input v-model="metaSubtitle" class="info-input italic" v-focus
                     placeholder="副标题：一句话补充视角/看点，≤30字" />
              <div class="flex gap-2 mt-1">
                <button class="text-xs hover:underline" style="color: var(--accent-ink);"
                        @click="saveSubtitle">保存</button>
                <button class="text-xs hover:underline" style="color: var(--faint);"
                        @click="metaEditing = null">取消</button>
              </div>
            </div>
          </div>

          <div v-for="b in visibleBlocks" :key="b.id"
               class="block-item" :class="{ selected: selectedId === b.id, editing: editingId === b.id,
                                            'drop-target': dropTargetId === b.id }"
               @click.stop="clickBlock(b)" @dblclick.stop="dblclickBlock(b)"
               @dragover="onBlockDragOver($event, b)" @dragleave="dropTargetId = null"
               @drop="onBlockDrop($event, b)">
            <template v-if="editingId !== b.id">
              <h1 v-if="b.type === 'heading' && b.level === 1">{{ b.text }}</h1>
              <h2 v-else-if="b.type === 'heading' && b.level === 2">{{ b.text }}</h2>
              <h3 v-else-if="b.type === 'heading'">{{ b.text }}</h3>
              <p v-else-if="b.type === 'paragraph'" :class="{ 'text-faint italic': !b.text }">
                {{ b.text || '（空段，双击输入）' }}</p>
              <blockquote v-else-if="b.type === 'quote'">{{ b.text }}</blockquote>
              <div v-else-if="b.type === 'image'" class="my-3">
                <img v-if="b.asset_id" :src="assetUrl(b.asset_id)" class="rounded-md max-w-full" />
                <div class="caption">{{ b.caption }}</div>
              </div>
              <div v-else-if="b.type === 'video'" class="my-3 rounded-md h-40 grid place-items-center text-sm"
                   style="background: var(--raised); color: var(--muted);">视频素材（发布包获取）</div>
              <hr v-else-if="b.type === 'divider'" />
            </template>
            <textarea v-else v-model="editText" @blur="saveEdit" @keyup.esc="editingId = null"
                      @click.stop
                      class="w-full outline-none bg-transparent text-[15px] leading-[1.9] resize-none"
                      :rows="Math.max(3, Math.ceil(editText.length / 40))" v-focus></textarea>
            <button class="add-block" @click.stop="addBlock(b.id)" title="在此插入文本块">+</button>
          </div>
          <div class="text-center text-xs mt-6" style="color: var(--faint);">
            双击编辑 · 点外部自动保存 · 块间 + 新增 · 双击图片替换 · 左侧素材可拖入指定位置
          </div>
        </template>
      </NSpin>
    </main>

    <!-- ============ 右侧工具窗口 ============ -->
    <aside class="side-panel right-panel panel" :class="{ hidden: !rightOpen }"
           @mouseenter="panelEnter" @mouseleave="panelLeave('right')">
      <div class="flex items-center justify-between px-3 py-2" style="border-bottom: 1px solid var(--rule);">
        <span class="text-xs font-semibold" style="color: var(--muted);">工具</span>
        <button class="text-xs hover:underline" style="color: var(--faint);" @click="rightOpen = false">收起</button>
      </div>
      <div class="p-3 space-y-4 overflow-auto panel-body">
        <div>
          <div class="text-xs font-semibold mb-2" style="color: var(--muted);">AI 重写</div>
          <div class="grid grid-cols-2 gap-1.5">
            <NButton size="tiny" :disabled="!selectedId || !isLatest || finalized" @click="openAi('rewrite')">选段重写</NButton>
            <NButton size="tiny" :disabled="!selectedId || !isLatest || finalized" @click="openAi('shorten')">缩写</NButton>
            <NButton size="tiny" :disabled="!selectedId || !isLatest || finalized" @click="openAi('expand')">扩写</NButton>
            <NButton size="tiny" :disabled="!selectedId || !isLatest || finalized" @click="openAi('custom')">自定义…</NButton>
          </div>
          <NButton size="tiny" block class="mt-1.5" :disabled="!doc || !isLatest || finalized"
                   @click="openAi('whole')">整篇重写</NButton>
        </div>
        <div>
          <div class="text-xs font-semibold mb-2" style="color: var(--muted);">版本管理</div>
          <NSelect size="small" :value="doc?.version" @update:value="(v: number) => load(v)"
                   :options="versions.map(v => ({
                     label: `v${v.version} · ${({ agent: 'AI', human: '人工', auto_fix: 'AI修复', insert_refs: '资料插入', rollback: '回滚' } as any)[v.origin] || v.origin}${v.checkpoint ? ' · 快照' : ''}${v.status === 'finalized' ? ' · 定稿' : ''}${v.changes ? ` · ${v.changes}块改动` : ''}`,
                     value: v.version }))" />
          <div class="text-[11px] mt-1.5" style="color: var(--faint);">块级增量版本：只记变更块，历史可重建。</div>
          <NButton size="tiny" block tertiary class="mt-2" :disabled="!doc || isLatest || finalized"
                   @click="doc && doRollback(doc.version)">回滚到当前查看的版本</NButton>
        </div>
        <NButton block type="primary" size="small" :disabled="!doc" @click="emit('goto-review')">去审稿 →</NButton>
      </div>
    </aside>

    <!-- ============ 底部信息窗口（总结/关键词/参考文字链接） ============ -->
    <div class="bottom-info panel">
      <div class="info-cell" @dblclick="metaEditing = 'one_liner'">
        <div class="info-label">文章总结</div>
        <template v-if="metaEditing === 'one_liner'">
          <textarea v-model="metaOneLiner" class="info-input" rows="2" @click.stop v-focus
                    @blur="saveMeta('one_liner')" />
        </template>
        <div v-else class="info-value">{{ metaOneLiner || '（无）' }}</div>
      </div>
      <div class="info-cell" @dblclick="metaEditing = 'keywords'">
        <div class="info-label">关键词</div>
        <template v-if="metaEditing === 'keywords'">
          <input v-model="metaKeywords" class="info-input" placeholder="#关键词1，#关键词2"
                 @click.stop v-focus @blur="saveMeta('keywords')" />
        </template>
        <div v-else class="info-value" style="color: var(--accent-ink);">{{ metaKeywords || '（无）' }}</div>
      </div>
      <div class="info-cell" @dblclick="metaEditing = 'reflinks'">
        <div class="info-label">参考文字链接</div>
        <template v-if="metaEditing === 'reflinks'">
          <textarea v-model="metaRefLinks" class="info-input" rows="3"
                    placeholder="每行一条：标题 | https://…" @click.stop v-focus
                    @blur="saveMeta('ref_links')" />
        </template>
        <div v-else class="info-value info-links">
          <template v-if="doc?.meta.ref_links?.length">
            <div v-for="(r, i) in doc.meta.ref_links.slice(0, 4)" :key="i" class="truncate">
              <a v-if="r.url" :href="r.url" target="_blank" class="hover:underline"
                 style="color: var(--accent-ink);" @click.stop>{{ r.title || r.url }}</a>
              <span v-else>{{ r.title }}</span>
            </div>
          </template>
          <span v-else>（创作后自动记录参考文章）</span>
        </div>
      </div>
    </div>

    <!-- AI 重写弹窗 -->
    <NModal v-model:show="aiModal" preset="card"
            :title="wholeArticle ? 'AI 整篇重写' : 'AI 改写选中段落'" class="!max-w-lg">
      <div class="space-y-3">
        <NInput v-model:value="aiInstruction" type="textarea" :autosize="{ minRows: 3 }"
                placeholder="重写指令，如：更口语一点 / 压到 100 字以内 / 补充 xx 背景" />
        <div class="flex justify-end gap-2">
          <NButton size="small" @click="aiModal = false">取消</NButton>
          <NButton size="small" type="primary" :loading="aiBusy" @click="runAi">生成新版本</NButton>
        </div>
      </div>
    </NModal>

    <!-- 图片替换弹窗 -->
    <NModal v-model:show="imgModal" preset="card" title="从素材库替换图片" class="!max-w-2xl">
      <div class="grid grid-cols-4 gap-3 max-h-96 overflow-auto">
        <div v-for="m in imageMaterials" :key="m.id" class="cursor-pointer group relative"
             @click="replaceImage(m)">
          <div class="aspect-square rounded-md overflow-hidden panel" style="background: var(--raised);">
            <img :src="api.absUrl(m.url)" class="w-full h-full object-cover" loading="lazy" />
          </div>
          <span v-if="m.watermark === 1" class="absolute top-1.5 left-1.5 px-1.5 py-0.5 rounded text-[11px]"
                style="background: var(--pill-warn-bg); color: var(--pill-warn-ink);">水印</span>
          <div class="text-xs truncate mt-1" style="color: var(--faint);">{{ m.title }}</div>
        </div>
      </div>
    </NModal>

    <!-- 图片灯箱 -->
    <NModal :show="!!lightboxUrl" preset="card" class="!max-w-4xl"
            @update:show="(v: boolean) => { if (!v) lightboxUrl = '' }">
      <img :src="lightboxUrl" class="max-w-full max-h-[78vh] mx-auto rounded-md" />
    </NModal>

    <!-- 融合插入弹窗 -->
    <NModal v-model:show="insertModal" preset="card" title="融合插入参考资料" class="!max-w-lg">
      <div class="space-y-3">
        <div class="text-sm" style="color: var(--muted);">
          将把 {{ insertIds.length }} 段参考素材融合改写，插入到当前选中段落之后。
        </div>
        <NInput v-model:value="insertInstruction" type="textarea" :autosize="{ minRows: 2 }"
                placeholder="插入指令（可选），如：作为背景补充 / 用来支撑第二段观点" />
        <div class="flex justify-end gap-2">
          <NButton size="small" @click="insertModal = false">取消</NButton>
          <NButton size="small" type="primary" :loading="aiBusy" @click="runInsert">融合插入</NButton>
        </div>
      </div>
    </NModal>
  </div>
</template>

<script lang="ts">
export default {
  directives: { focus: { mounted: (el: HTMLElement) => el.focus() } },
}
</script>

<style scoped>
/* 布局（反馈三）：宽屏三栏 sticky 跟随滚动；窄屏收起为边缘标记条，防抖弹出 */
.create-wb {
  display: grid;
  grid-template-columns: clamp(200px, 16vw, 300px) minmax(0, 1fr) clamp(220px, 17vw, 320px);
  gap: 16px;
  align-items: start;
  min-height: 62vh;
}
.create-wb.narrow { grid-template-columns: 0 minmax(0, 1fr) 0; }
.nb-center { padding: 28px 32px; min-height: 62vh; grid-column: 2; grid-row: 1; }
.left-panel { grid-column: 1; grid-row: 1; }
.right-panel { grid-column: 3; grid-row: 1; }
.bottom-info { grid-column: 1 / -1; grid-row: 2; }

.side-panel { position: sticky; top: 96px; background: var(--surface); z-index: 5; }
.panel-body { max-height: calc(100vh - 320px); }
.left-panel.hidden, .right-panel.hidden { display: none; }

/* 窄屏：面板转为固定悬浮层，边缘留标记条 */
.create-wb.narrow .side-panel {
  position: fixed; top: 50%; transform: translateY(-50%);
  display: block; max-height: 76vh; box-shadow: var(--tw-shadow, 0 8px 30px rgba(20,20,20,.14));
  width: clamp(220px, 26vw, 300px);
}
.create-wb.narrow .left-panel { left: 8px; }
.create-wb.narrow .right-panel { right: 8px; }
.create-wb.narrow .side-panel.hidden { display: none; }

.edge-marker {
  position: fixed; top: 30%; bottom: 30%; width: 16px; z-index: 20;
  border: 1px solid var(--control); background: var(--surface);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
}
.edge-marker.left { left: 0; border-left: none; border-radius: 0 8px 8px 0; }
.edge-marker.right { right: 0; border-right: none; border-radius: 8px 0 0 8px; }
.edge-marker span {
  writing-mode: vertical-rl; font-size: 10px; color: var(--faint); letter-spacing: 2px;
}
.edge-marker:hover { border-color: var(--accent); }

/* 标题 & 副标题（置顶块样式规范） */
.doc-title { font-size: 24px; font-weight: 800; line-height: 1.3; letter-spacing: -0.01em; }
.doc-subtitle { font-size: 15px; font-style: italic; color: var(--muted); margin-top: 6px; }

/* 块 */
.block-item { position: relative; padding: 2px 6px; border-radius: 6px; }
.block-item:hover { background: var(--raised); }
.block-item.selected { background: #FDF0EC; outline: 1px solid #F0C4B8; }
.block-item.editing { background: var(--surface); outline: 1px solid var(--control); }
.block-item.drop-target { outline: 2px dashed var(--accent); background: var(--accent-soft); }
.block-item h1 { font-size: 22px; font-weight: 700; margin: 0 0 20px; line-height: 1.35; }
.block-item h2 { font-size: 17px; font-weight: 700; margin: 26px 0 10px; }
.block-item h3 { font-size: 15px; font-weight: 700; margin: 20px 0 8px; }
.block-item p { line-height: 1.9; font-size: 15px; color: #2A2926; margin-bottom: 1em; text-align: justify; }
.block-item blockquote { border-left: 3px solid var(--accent); background: var(--raised);
  padding: 10px 16px; margin: 0 0 16px; color: #4A463D; font-size: 14px; line-height: 1.8; }
.block-item .caption { text-align: center; font-size: 12px; color: var(--faint); margin-top: 4px; }
.add-block {
  position: absolute; left: 50%; bottom: -9px; transform: translateX(-50%);
  width: 18px; height: 18px; border-radius: 999px; font-size: 12px; line-height: 1;
  background: var(--surface); border: 1px solid var(--border); color: var(--faint);
  opacity: 0; transition: opacity .12s; z-index: 3;
}
.block-item:hover .add-block { opacity: 1; }

/* 底部信息窗口 */
.bottom-info {
  grid-column: 1 / -1; display: grid;
  grid-template-columns: 1.2fr 1fr 1.4fr; gap: 0; margin-top: 12px;
}
.info-cell { padding: 12px 16px; }
.info-cell + .info-cell { border-left: 1px solid var(--rule); }
.info-cell:hover { background: var(--raised); }
.info-label { font-size: 11px; color: var(--faint); margin-bottom: 4px; }
.info-value { font-size: 13px; line-height: 1.5; }
.info-links a { display: block; }
.info-input { width: 100%; font-size: 13px; border: 1px solid var(--control);
  border-radius: 6px; padding: 6px 8px; outline: none; background: var(--surface); }
.info-input:focus { border-color: var(--ink-900); }
.text-faint { color: var(--faint); }
</style>
