<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { NButton, NCheckbox, NInput, NModal, useMessage } from 'naive-ui'
import { api } from '../api'
import { useAppStore } from '../stores/app'
import type { Material } from '../types'

const props = defineProps<{ articleId: string }>()
const emit = defineEmits<{
  (e: 'insert-refs', materialIds: string[]): void
  (e: 'import-create', materialIds: string[]): void
}>()
const message = useMessage()
const store = useAppStore()

type TabKey = 'text' | 'image' | 'video' | 'other'
const TABS: { key: TabKey; label: string }[] = [
  { key: 'text', label: '文章' }, { key: 'image', label: '图片' },
  { key: 'video', label: '视频' }, { key: 'other', label: '其他' },
]
const REF_LABEL: Record<string, string> = {
  primary: '原文', reference: '参考', foundational: '基础资料',
}

const scope = ref<'article' | 'common'>('article')
const tab = ref<TabKey>('text')
const materials = ref<Material[]>([])
const selected = ref<Set<string>>(new Set())
const showAddUrl = ref(false)
const addUrl = ref('')
const batchMode = ref(false)
const busy = ref(false)

const textModal = ref(false)
const textModalTitle = ref('')
const textModalContent = ref('')
const textLoading = ref(false)
const lightboxUrl = ref('')
const playModalObj = ref<Material | null>(null)
const dragOver = ref(false)
const dragOverCommon = ref(false)

let generation = 0
let controller: AbortController | null = null
async function load() {
  const current = ++generation
  controller?.abort()
  controller = new AbortController()
  const signal = controller.signal
  const url = scope.value === 'article'
    ? `/api/articles/${props.articleId}/materials?scope=article`
    : '/api/materials/common'
  try {
    const result = await api.get(url, signal)
    if (current !== generation) return
    materials.value = result.materials
    const available = new Set(materials.value.map(m => m.id))
    selected.value = new Set([...selected.value].filter(id => available.has(id)))
  } catch (error: any) { if (!signal.aborted) message.error(error.message) }
}
onMounted(async () => { await load(); await checkDraft() })
watch(() => store.articleTicks[props.articleId] || 0, load)
watch(scope, () => { selected.value = new Set(); load() })
onUnmounted(() => { generation++; controller?.abort() })

/* ---------- 分组与过滤 ---------- */

const titleOf = computed(() => {
  const map: Record<string, string> = {}
  for (const m of materials.value) if (m.kind === 'text') map[m.id] = m.title || m.id
  return map
})

function sourceTitle(m: Material): string {
  if (m.source_material_id && titleOf.value[m.source_material_id])
    return titleOf.value[m.source_material_id]
  return m.note || '手动添加'
}

const filtered = computed(() => {
  // 文章栏含 text（全文入库）与 link（文章/资料链接形态）；其他栏只放实体文件（音频/文档/压缩包）
  if (tab.value === 'other')
    return materials.value.filter(m => ['audio', 'doc'].includes(m.kind))
  if (tab.value === 'text')
    return materials.value.filter(m => ['text', 'link'].includes(m.kind))
  return materials.value.filter(m => m.kind === tab.value)
})

const counts = computed(() => ({
  text: materials.value.filter(m => ['text', 'link'].includes(m.kind)).length,
  image: materials.value.filter(m => m.kind === 'image').length,
  video: materials.value.filter(m => m.kind === 'video').length,
  other: materials.value.filter(m => ['audio', 'doc'].includes(m.kind)).length,
}))

const grouped = computed(() => {
  if (tab.value !== 'image' && tab.value !== 'video') return []
  const map = new Map<string, Material[]>()
  for (const m of filtered.value) {
    const key = m.source_material_id || '_ungrouped'
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(m)
  }
  return [...map.entries()].map(([key, items]) => ({
    key,
    title: key === '_ungrouped' ? '未分组（手动添加/素材库补充）' : sourceTitle(items[0]),
    items,
  }))
})

/* ---------- 选择 / 操作 ---------- */

function groupAllSelected(g: { items: Material[] }): boolean {
  return g.items.every(m => selected.value.has(m.id))
}
function toggleGroup(g: { items: Material[] }) {
  const ids = g.items.map(m => m.id)
  const all = groupAllSelected(g)
  const next = new Set(selected.value)
  for (const id of ids) all ? next.delete(id) : next.add(id)
  selected.value = next
}

function toggle(id: string) {
  selected.value.has(id) ? selected.value.delete(id) : selected.value.add(id)
  selected.value = new Set(selected.value)
}

async function openText(m: Material) {
  textModalTitle.value = m.title || m.id
  textModalContent.value = ''
  textModal.value = true
  textLoading.value = true
  try {
    textModalContent.value = (await api.get(`/api/materials/${m.id}/text`)).content || '（无正文）'
  } finally { textLoading.value = false }
}

function openSource(m: Material) {
  if (m.source_url) window.open(m.source_url, '_blank')
}

async function remove(m: Material) {
  await api.del(`/api/materials/${m.id}`)
  selected.value.delete(m.id)
  await load()
}

async function recrawl(m: Material) {
  busy.value = true
  try {
    const r = await api.post(`/api/materials/${m.id}/recrawl`)
    message.success(`已重抓: ${r.title}（新增媒体 ${r.media_added}）`)
    await load()
  } catch (e: any) { message.error(e.message) } finally { busy.value = false }
}

async function reveal(m: Material) {
  try {
    const r = await api.post(`/api/materials/${m.id}/reveal`)
    if (r.external) window.open(r.external, '_blank')   // 链接型素材：浏览器打开来源
  } catch (e: any) {
    message.warning(e.message)                          // 路径失效：友好提示（反馈 3.5）
  }
}

/* ---------- 添加 ---------- */

async function addByUrl() {
  const urls = addUrl.value.split(/[\s\n]+/).filter(u => u.startsWith('http'))
  if (!urls.length) { message.warning('请粘贴有效链接'); return }
  busy.value = true
  try {
    if (batchMode.value || urls.length > 1) {
      const r = await api.post(`/api/articles/${props.articleId}/materials/batch-url`, { urls })
      message.success(`已提交批量抓取（${r.count} 个链接），后台处理中…`)
    } else {
      const r = await api.post(`/api/articles/${props.articleId}/materials/url`, { url: urls[0] })
      message.success(`已抓取: ${r.title || r.material_id}`)
    }
    showAddUrl.value = false; addUrl.value = ''
    await load()
  } catch (e: any) { message.error(e.message) } finally { busy.value = false }
}

async function upload(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  const url = scope.value === 'article'
    ? `/api/articles/${props.articleId}/materials/upload` : '/api/materials/upload'
  try {
    await api.upload(url, file)
    message.success('已入库')
    await load()
  } catch (err: any) { message.error(err.message) }
  ;(e.target as HTMLInputElement).value = ''
}

async function scanInbox() {
  const url = scope.value === 'article'
    ? `/api/articles/${props.articleId}/materials/scan-inbox` : '/api/materials/scan-inbox'
  const r = await api.post(url)
  message.success(r.ingested.length ? `摄取 ${r.ingested.length} 个新素材` : 'inbox 没有新文件')
  await load()
}

/* ---------- 视频封面与播放 ---------- */

/** 视频素材的封面图：找 source_material_id 指向该视频的子图片 */
const coverOf = computed(() => {
  const map: Record<string, string> = {}
  for (const m of materials.value) {
    if (m.kind === 'image' && m.source_material_id && m.url && !map[m.source_material_id]) {
      map[m.source_material_id] = api.absUrl(m.url)
    }
  }
  return map
})

function onVideoClick(m: Material) {
  playModalObj.value = m       // 封面上的【在线播放】按钮唤起弹窗
}

function onGroupTitleClick(g: { key: string; title: string }) {
  if (g.key === '_ungrouped') return
  const parent = materials.value.find(x => x.id === g.key)
  if (parent) openText(parent)                   // 跳到来源文章正文
}

/* ---------- 拖拽复制（公共库 → 本文库） ---------- */

function onDragStart(e: DragEvent, m: Material) {
  e.dataTransfer?.setData('text/material-id', m.id)
  e.dataTransfer!.effectAllowed = 'copy'
}

async function onDropToArticle(e: DragEvent) {
  e.preventDefault()
  dragOver.value = false
  const mid = e.dataTransfer?.getData('text/material-id')
  if (!mid) return
  try {
    const r = await api.post(`/api/materials/${mid}/copy-to-article`, { article_id: props.articleId })
    message.success(r.copied ? '已复制到本文素材库' : (r.reason || '该素材已在本文素材库'))
    scope.value = 'article'
    await load()
  } catch (err: any) { message.error(err.message) }
}

async function onDropToCommon(e: DragEvent) {
  e.preventDefault()
  dragOverCommon.value = false
  const mid = e.dataTransfer?.getData('text/material-id')
  if (!mid) return
  try {
    const r = await api.post(`/api/materials/${mid}/copy-to-common`)
    message.success(r.copied ? '已复制到公共素材库' : (r.reason || '公共库已存在，已跳过'))
    scope.value = 'common'
    await load()
  } catch (err: any) { message.error(err.message) }
}

/* ---------- 导入按钮状态分支（反馈 四） ----------
   初始（无草稿）：「导入&创作」→ 导入 + 调 LLM 生成；
   后续（已有草稿）：「导入素材」→ 仅导入会话，不自动生成。 */
const hasDraft = ref(false)

async function checkDraft() {
  try { await api.get(`/api/articles/${props.articleId}/draft`); hasDraft.value = true }
  catch { hasDraft.value = false }
}

async function importCreate() {
  if (!selected.value.size) return
  const ids = [...selected.value]
  if (hasDraft.value) {
    // 仅导入会话
    const cur = new Set(await currentSelection())
    ids.forEach(id => cur.add(id))
    await api.put(`/api/articles/${props.articleId}/selection`, { material_ids: [...cur] })
    message.success(`已导入 ${ids.length} 份素材到本次创作会话（未触发重新生成）`)
    selected.value = new Set()
    await load()
  } else {
    emit('import-create', ids)
    selected.value = new Set()
  }
}

async function currentSelection(): Promise<string[]> {
  const a = await api.get(`/api/articles/${props.articleId}`)
  return a.selected_material_ids || []
}
</script>

<template>
  <div>
    <!-- 工具行 -->
    <div class="flex items-center gap-2 mb-4 flex-wrap">
      <div class="panel p-0.5 flex" style="border-radius: 8px;">
        <button v-for="s in [['article', '本文素材库'], ['common', '公共素材库']]" :key="s[0]"
                class="px-4 h-8 rounded-md text-sm transition-colors"
                :style="[
                  scope === s[0]
                    ? 'background: var(--active); color: var(--text); font-weight: 600;'
                    : 'color: var(--muted);',
                  s[0] === 'article' && dragOver ? 'outline: 2px dashed var(--accent);' : '',
                  s[0] === 'common' && dragOverCommon ? 'outline: 2px dashed var(--accent);' : ''
                ]"
                @click="scope = s[0] as any"
                @dragover.prevent="s[0] === 'article' && scope === 'common' && (dragOver = true);
                                    s[0] === 'common' && scope === 'article' && (dragOverCommon = true)"
                @dragleave="s[0] === 'article' ? (dragOver = false) : (dragOverCommon = false)"
                @drop="s[0] === 'article' ? onDropToArticle($event) : onDropToCommon($event)">{{ s[1] }}</button>
      </div>
      <span class="text-xs" style="color: var(--faint);">
        拖拽条目到另一侧库名即可复制（公共 ⇄ 本文，sha 校验去重）
      </span>
      <div class="flex-1"></div>
      <NButton size="small" @click="showAddUrl = true">+ 粘贴网址</NButton>
      <label class="inline-flex">
        <input type="file" class="hidden" @change="upload" />
        <NButton size="small" tag="span">+ 上传文件</NButton>
      </label>
      <NButton size="small" quaternary @click="scanInbox">扫描 inbox</NButton>
      <NButton v-if="selected.size" size="small" type="primary" @click="importCreate">
        {{ hasDraft ? `导入素材（已选 ${selected.size}）` : `导入 & 创作（已选 ${selected.size}）` }}
      </NButton>
    </div>

    <!-- 4 分栏标签 -->
    <div class="flex items-center gap-1 mb-4 border-b" style="border-color: var(--border);">
      <button v-for="t in TABS" :key="t.key"
              class="px-3 h-9 text-sm border-b-2 -mb-px transition-colors"
              :style="tab === t.key
                ? 'border-color: var(--accent); color: var(--text); font-weight: 600;'
                : 'border-color: transparent; color: var(--muted);'"
              @click="tab = t.key">
        {{ t.label }}<span class="ml-1 num" style="color: var(--faint);">{{ counts[t.key] }}</span>
      </button>
    </div>

    <div v-if="!filtered.length" class="panel py-14 text-center">
      <p class="text-sm" style="color: var(--muted);">该分类下暂无素材。</p>
      <p class="text-xs mt-1.5" style="color: var(--faint);">
        收集后自动入库；也可粘贴网址、上传文件，或拷入 inbox 文件夹后点「扫描 inbox」。
      </p>
    </div>

    <!-- 【文章】分栏 -->
    <div v-if="tab === 'text' && filtered.length" class="panel divide-y">
      <div v-for="m in filtered" :key="m.id"
           class="px-4 py-3 flex items-center gap-3 hover:bg-[var(--raised)]"
           :draggable="scope === 'common'" @dragstart="onDragStart($event, m)">
        <span class="px-1.5 -ml-1.5 py-1 inline-flex" @click.stop @mousedown.stop>
          <NCheckbox :checked="selected.has(m.id)" @update:checked="toggle(m.id)" />
        </span>
        <div class="flex-1 min-w-0">
          <button class="text-sm font-medium hover:underline text-left truncate block max-w-full"
                  :title="m.kind === 'link' ? '链接形态素材：点击新窗口打开来源' : ''"
                  @click="m.kind === 'link' && m.source_url ? openSource(m) : openText(m)">
            {{ m.title || m.id }}</button>
          <div class="text-xs flex items-center gap-2 mt-0.5 flex-wrap" style="color: var(--faint);">
            <span v-if="m.kind === 'link'" class="px-1.5 py-0.5 rounded"
                  style="background: var(--raised); color: var(--muted);">链接</span>
            <span v-if="m.ref_type" class="px-1.5 py-0.5 rounded"
                  style="background: var(--pill-info-bg); color: var(--pill-info-ink);">
              {{ REF_LABEL[m.ref_type] || m.ref_type }}</span>
            <button v-if="m.source_url" class="hover:underline truncate max-w-md text-left"
                    style="color: var(--accent-ink);" @click="openSource(m)">
              {{ m.source_url }}</button>
            <span v-if="m.note" class="truncate">{{ m.note }}</span>
            <span v-if="m.fetch_status !== 'ok'" style="color: var(--pill-neg-ink);">{{ m.fetch_status }}</span>
          </div>
        </div>
        <button v-if="m.source_url" class="text-xs px-2 py-1 rounded hover:bg-[var(--active)]"
                style="color: var(--muted);" title="重新抓取该链接"
                @click="recrawl(m)">↻ 重抓</button>
        <button class="text-xs px-2 py-1 rounded hover:bg-[var(--active)]"
                style="color: var(--muted);" @click="reveal(m)">文件夹</button>
        <button class="text-lg px-2 hover:opacity-70" style="color: var(--faint);"
                @click="remove(m)">×</button>
      </div>
    </div>

    <!-- 【图片/视频】分栏：按来源文章分组 -->
    <template v-if="(tab === 'image' || tab === 'video') && filtered.length">
      <div v-for="g in grouped" :key="g.key" class="mb-6">
        <div class="text-sm font-semibold mb-2 flex items-center gap-2"
             style="color: var(--muted);">
          <span class="inline-flex items-center" @click.stop @mousedown.stop>
            <NCheckbox :checked="groupAllSelected(g)"
                       @update:checked="toggleGroup(g)" />
          </span>
          <button class="hover:underline truncate text-left font-semibold"
                 @click="onGroupTitleClick(g)">{{ g.title }}</button>
          <span class="num text-xs" style="color: var(--faint);">{{ g.items.length }}</span>
        </div>
        <div class="grid grid-cols-3 md:grid-cols-5 gap-3">
          <div v-for="m in g.items" :key="m.id" class="relative group"
               :draggable="scope === 'common'" @dragstart="onDragStart($event, m)">
            <!-- 图片卡 -->
            <template v-if="tab === 'image'">
              <div class="aspect-square rounded-md overflow-hidden panel cursor-zoom-in"
                   style="background: var(--raised);" @click="lightboxUrl = api.absUrl(m.url)">
                <img v-if="m.url" :src="api.absUrl(m.url)" class="w-full h-full object-cover" loading="lazy" />
              </div>
            </template>
            <!-- 视频卡：封面缩略图 + 中央【在线播放】按钮（反馈 3.1） -->
            <template v-else>
              <div class="aspect-video rounded-md overflow-hidden panel relative cursor-pointer group/v"
                   style="background: #1D1F20;" @click="onVideoClick(m)">
                <img :src="api.absUrl(`/api/materials/${m.id}/thumb`)"
                     class="w-full h-full object-cover opacity-90" loading="lazy" />
                <div class="absolute inset-0 grid place-items-center">
                  <span class="px-3 py-1.5 rounded-full text-xs font-medium text-white
                               bg-black/60 group-hover/v:bg-black/80 transition-colors">
                    ▶ 在线播放</span>
                </div>
                <span v-if="m.duration" class="absolute bottom-1.5 right-1.5 text-[11px] text-white/90 num bg-black/60 px-1 rounded">
                  {{ Math.round(m.duration) }}s</span>
              </div>
            </template>
            <!-- 左上复选框（扩大独立点击区，事件隔离） / 右上删除 -->
            <div class="absolute top-0 left-0 p-2 bg-white/85 rounded-br-lg z-10"
                 @click.stop @mousedown.stop>
              <NCheckbox :checked="selected.has(m.id)" @update:checked="toggle(m.id)" />
            </div>
            <button class="absolute top-1.5 right-1.5 w-6 h-6 rounded-full text-xs
                           opacity-0 group-hover:opacity-100 transition-opacity"
                    style="background: rgba(20,20,20,.6); color: #fff;"
                    @click.stop="remove(m)">×</button>
            <div class="text-xs mt-1 truncate" style="color: var(--faint);">
              {{ m.title || sourceTitle(m) }}
              <span v-if="m.watermark === 1" class="ml-1 px-1 rounded"
                    style="background: var(--pill-warn-bg); color: var(--pill-warn-ink);">水印</span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 【其他】分栏 -->
    <div v-if="tab === 'other' && filtered.length" class="panel divide-y">
      <div v-for="m in filtered" :key="m.id"
           class="px-4 py-3 flex items-center gap-3 hover:bg-[var(--raised)] cursor-pointer"
           :draggable="scope === 'common'" @dragstart="onDragStart($event, m)"
           @click="reveal(m)">
        <span class="px-1.5 -ml-1.5 py-1 inline-flex" @click.stop @mousedown.stop>
          <NCheckbox :checked="selected.has(m.id)" @update:checked="toggle(m.id)" />
        </span>
        <span class="text-xs px-1.5 py-0.5 rounded shrink-0"
              style="background: var(--pill-info-bg); color: var(--pill-info-ink);">{{
                ({ audio: '音频', doc: '文档', link: '链接' } as Record<string, string>)[m.kind] || m.kind }}</span>
        <div class="flex-1 min-w-0">
          <div class="text-sm truncate">{{ m.title || m.id }}</div>
          <div class="text-xs truncate" style="color: var(--faint);">{{ m.path || m.source_url }}</div>
        </div>
        <button class="text-lg px-2 hover:opacity-70" style="color: var(--faint);"
                @click.stop="remove(m)">×</button>
      </div>
    </div>

    <!-- 添加网址弹窗 -->
    <NModal v-model:show="showAddUrl" preset="card" title="按网址添加参考素材" class="!max-w-lg">
      <div class="space-y-3">
        <NInput v-model:value="addUrl" type="textarea" :autosize="{ minRows: batchMode ? 5 : 2 }"
                placeholder="https://…（抓取正文/图片/视频/音频入库）" />
        <label class="flex items-center gap-2 text-sm" style="color: var(--muted);">
          <NCheckbox v-model:checked="batchMode" /> 批量模式（每行一个链接，后台批量抓取）
        </label>
        <div class="flex justify-end gap-2">
          <NButton size="small" @click="showAddUrl = false">取消</NButton>
          <NButton size="small" type="primary" :loading="busy" @click="addByUrl">
            {{ batchMode ? '批量抓取' : '抓取并入库' }}</NButton>
        </div>
      </div>
    </NModal>

    <!-- 原文 markdown 查看 -->
    <NModal v-model:show="textModal" preset="card" :title="textModalTitle" class="!max-w-3xl">
      <NSpin v-if="textLoading" class="py-10" />
      <pre v-else class="whitespace-pre-wrap text-sm leading-relaxed max-h-[70vh] overflow-auto"
           style="font-family: inherit; color: var(--ink-700);">{{ textModalContent }}</pre>
    </NModal>

    <!-- 图片灯箱 -->
    <NModal :show="!!lightboxUrl" preset="card" class="!max-w-4xl"
            @update:show="(v: boolean) => { if (!v) lightboxUrl = '' }">
      <img :src="lightboxUrl" class="max-w-full max-h-[78vh] mx-auto rounded-md" />
    </NModal>

    <!-- 视频播放弹窗（遮罩点击关闭 + 关闭按钮；本地文件用 <video>，链接型用 iframe 播放器） -->
    <NModal :show="!!playModalObj" preset="card" class="!max-w-3xl"
            :title="playModalObj?.title || '视频播放'"
            @update:show="(v: boolean) => { if (!v) playModalObj = null }">
      <template v-if="playModalObj">
        <video v-if="playModalObj.path && playModalObj.url"
               :src="api.absUrl(playModalObj.url)" controls autoplay
               class="w-full max-h-[70vh] rounded-md" style="background:#000;"></video>
        <template v-else-if="playModalObj.source_url">
          <iframe :src="playModalObj.source_url" class="w-full rounded-md"
                  style="height: 60vh; border: 0; background:#000;" allowfullscreen></iframe>
          <div class="text-xs mt-2 flex items-center gap-2" style="color: var(--faint);">
            若播放器未加载，
            <a :href="playModalObj.source_url" target="_blank"
               class="hover:underline" style="color: var(--accent-ink);">点击在浏览器中打开</a>
          </div>
        </template>
        <div v-else class="py-10 text-center text-sm" style="color: var(--faint);">
          该视频没有可播放的地址</div>
      </template>
    </NModal>
  </div>
</template>

<script lang="ts">
import { NSpin } from 'naive-ui'
export default { components: { NSpin } }
</script>
