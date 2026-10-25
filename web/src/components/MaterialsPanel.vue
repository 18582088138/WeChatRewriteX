<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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
const videoUrl = ref('')
const dragOver = ref(false)

async function load() {
  const url = scope.value === 'article'
    ? `/api/articles/${props.articleId}/materials?scope=article`
    : '/api/materials/common'
  materials.value = (await api.get(url)).materials
  selected.value = new Set()
}
onMounted(load)
watch(() => store.workbenchTick, load)
watch(scope, load)

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
  if (tab.value === 'other')
    return materials.value.filter(m => ['audio', 'doc', 'link'].includes(m.kind))
  return materials.value.filter(m => m.kind === tab.value)
})

const counts = computed(() => ({
  text: materials.value.filter(m => m.kind === 'text').length,
  image: materials.value.filter(m => m.kind === 'image').length,
  video: materials.value.filter(m => m.kind === 'video').length,
  other: materials.value.filter(m => ['audio', 'doc', 'link'].includes(m.kind)).length,
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
  try { await api.post(`/api/materials/${m.id}/reveal`) }
  catch (e: any) { message.error(e.message) }
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

function onVideoClick(m: Material) {
  if (m.path && m.url) {
    videoUrl.value = api.absUrl(m.url)          // 本地视频：弹窗播放
  } else if (m.source_url) {
    window.open(m.source_url, '_blank')         // 链接型视频(视频号)：外跳播放器页
  }
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
    message.success(r.copied ? '已复制到本文素材库' : '该素材已在本文素材库')
    scope.value = 'article'
    await load()
  } catch (err: any) { message.error(err.message) }
}

/* ---------- 导入 & 创作 ---------- */

function importCreate() {
  if (!selected.value.size) return
  emit('import-create', [...selected.value])
}
</script>

<template>
  <div>
    <!-- 工具行 -->
    <div class="flex items-center gap-2 mb-4 flex-wrap">
      <div class="panel p-0.5 flex" style="border-radius: 8px;"
           @dragover.prevent="scope === 'common' && (dragOver = true)"
           @dragleave="dragOver = false"
           @drop="onDropToArticle">
        <button v-for="s in [['article', '本文素材库'], ['common', '公共素材库']]" :key="s[0]"
                class="px-4 h-8 rounded-md text-sm transition-colors"
                :style="[
                  scope === s[0]
                    ? 'background: var(--active); color: var(--text); font-weight: 600;'
                    : 'color: var(--muted);',
                  s[0] === 'article' && dragOver ? 'outline: 2px dashed var(--accent);' : ''
                ]"
                @click="scope = s[0] as any">{{ s[1] }}</button>
      </div>
      <span v-if="scope === 'common'" class="text-xs" style="color: var(--faint);">
        可拖拽素材条目到「本文素材库」完成复制
      </span>
      <div class="flex-1"></div>
      <NButton size="small" @click="showAddUrl = true">+ 粘贴网址</NButton>
      <label class="inline-flex">
        <input type="file" class="hidden" @change="upload" />
        <NButton size="small" tag="span">+ 上传文件</NButton>
      </label>
      <NButton size="small" quaternary @click="scanInbox">扫描 inbox</NButton>
      <NButton v-if="selected.size" size="small" type="primary" @click="importCreate">
        导入 & 创作（已选 {{ selected.size }}）
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
        <NCheckbox :checked="selected.has(m.id)" @update:checked="toggle(m.id)" />
        <div class="flex-1 min-w-0">
          <button class="text-sm font-medium hover:underline text-left truncate block max-w-full"
                  @click="openText(m)">{{ m.title || m.id }}</button>
          <div class="text-xs flex items-center gap-2 mt-0.5 flex-wrap" style="color: var(--faint);">
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
            <!-- 视频卡 -->
            <template v-else>
              <div class="aspect-video rounded-md panel cursor-pointer grid place-items-center"
                   style="background: #1D1F20; color: #fff;"
                   @click="onVideoClick(m)">
                <div class="text-center">
                  <div class="text-2xl">▶</div>
                  <div v-if="m.duration" class="text-xs mt-1 num">{{ Math.round(m.duration) }}s</div>
                  <div v-else-if="!m.path" class="text-xs mt-1 opacity-70">在线播放</div>
                </div>
              </div>
            </template>
            <!-- 左上复选框 / 右上删除 -->
            <div class="absolute top-1.5 left-1.5 bg-white/90 rounded px-0.5">
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
        <NCheckbox :checked="selected.has(m.id)" @update:checked="toggle(m.id)" @click.stop />
        <span class="text-xs px-1.5 py-0.5 rounded shrink-0"
              style="background: var(--pill-info-bg); color: var(--pill-info-ink);">{{
                { audio: '音频', doc: '文档', link: '链接' }[m.kind] || m.kind }}</span>
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

    <!-- 视频播放 -->
    <NModal :show="!!videoUrl" preset="card" class="!max-w-3xl"
            @update:show="(v: boolean) => { if (!v) videoUrl = '' }">
      <video v-if="videoUrl" :src="videoUrl" controls autoplay
             class="w-full max-h-[70vh] rounded-md" style="background:#000;"></video>
    </NModal>
  </div>
</template>

<script lang="ts">
import { NSpin } from 'naive-ui'
export default { components: { NSpin } }
</script>
