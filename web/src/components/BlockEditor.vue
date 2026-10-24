<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NEmpty, NInput, NModal, NSelect, NSpin, useMessage } from 'naive-ui'
import { api } from '../api'
import { useAppStore } from '../stores/app'
import type { Block, DraftDoc, Material, VersionRow } from '../types'

const props = defineProps<{ articleId: string }>()
const emit = defineEmits<{ (e: 'goto-review'): void }>()
const message = useMessage()
const store = useAppStore()

const draftId = ref('')
const doc = ref<DraftDoc | null>(null)
const versions = ref<VersionRow[]>([])
const viewingVersion = ref<number | null>(null)
const loading = ref(false)

const selectedId = ref<string | null>(null)
const editingId = ref<string | null>(null)
const editText = ref('')

const aiModal = ref(false)
const aiInstruction = ref('')
const aiBusy = ref(false)
const aiTargets = ref<string[]>([])

const imgModal = ref(false)
const imgBlockId = ref('')
const imageMaterials = ref<Material[]>([])

const insertModal = ref(false)
const insertIds = ref<string[]>([])
const insertInstruction = ref('')

/* —— 元信息三个独立编辑框 —— */
const metaTitle = ref('')            // 主标题（候选首位）
const metaTitleAlts = ref('')        // 其余候选，每行一个
const metaOneLiner = ref('')
const metaKeywords = ref('')
const metaSaving = ref('')

const isLatest = computed(() =>
  !versions.value.length || viewingVersion.value === versions.value[0]?.version)
const finalized = computed(() => versions.value[0]?.status === 'finalized')

function assetUrl(assetId: string): string {
  return api.absUrl(`/api/materials/${assetId}/file`)
}
function originLabel(origin: string): string {
  return ({ agent: 'AI', human: '人工', auto_fix: 'AI修复', insert_refs: '资料插入' } as
    Record<string, string>)[origin] || origin
}

function syncMetaForm() {
  const d = doc.value
  if (!d) return
  const [first, ...rest] = d.meta.title_candidates || []
  metaTitle.value = first || ''
  metaTitleAlts.value = rest.join('\n')
  metaOneLiner.value = d.meta.one_liner || ''
  metaKeywords.value = (d.meta.keywords || []).join(' ')
}

async function load(version?: number) {
  loading.value = true
  try {
    const r = await api.get(`/api/articles/${props.articleId}/draft` +
                            (version ? `?version=${version}` : ''))
    doc.value = r.draft.doc
    draftId.value = r.draft.id
    versions.value = r.versions
    viewingVersion.value = r.draft.version
    syncMetaForm()
  } catch (e) {
    console.error('draft load failed', e)
    if (!doc.value) doc.value = null
  } finally {
    loading.value = false
  }
}
onMounted(() => load())
watch(() => store.workbenchTick, () => load(viewingVersion.value ?? undefined))

/* ---------- 元信息保存 ---------- */

async function saveMeta(field: 'title' | 'one_liner' | 'keywords') {
  if (!doc.value || !draftId.value) return
  metaSaving.value = field
  const ops: any[] = []
  if (field === 'title') {
    if (metaTitle.value.trim())
      ops.push({ op: 'update_meta', field: 'title_selected', value: metaTitle.value.trim() })
    const alts = [metaTitle.value.trim(),
                  ...metaTitleAlts.value.split('\n').map(s => s.trim()).filter(Boolean)]
    ops.push({ op: 'update_meta', field: 'title_candidates', value: alts })
  } else if (field === 'one_liner') {
    ops.push({ op: 'update_meta', field: 'one_liner', value: metaOneLiner.value })
  } else {
    ops.push({ op: 'update_meta', field: 'keywords',
               value: metaKeywords.value.split(/[\s,，、;；]+/).filter(Boolean) })
  }
  try {
    const r = await api.put(`/api/drafts/${draftId.value}/edit`, { ops })
    message.success(`已保存（v${r.version}）`)
    await load()
  } catch (e: any) { message.error(e.message) } finally { metaSaving.value = '' }
}

/* ---------- 块编辑 ---------- */

function clickBlock(b: Block) {
  selectedId.value = b.id
  store.anchorBlockId = b.id
}

function dblclickBlock(b: Block) {
  if (!isLatest.value || finalized.value) return
  if (b.type === 'image' || b.type === 'video') { openImagePicker(b.id); return }
  if (b.type === 'divider') return
  editingId.value = b.id
  editText.value = b.text
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

function openAi(mode: 'rewrite' | 'shorten' | 'expand' | 'custom') {
  if (!selectedId.value) return
  const presets = {
    rewrite: '换一种表达，保持事实不变，更自然流畅',
    shorten: '压缩到一半字数，保留事实',
    expand: '展开补充背景解释，不编造数字',
    custom: '',
  }
  aiTargets.value = [selectedId.value]
  aiInstruction.value = presets[mode]
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

/* ---------- 图片 ---------- */

async function openImagePicker(blockId: string) {
  imgBlockId.value = blockId
  const r = await api.get(`/api/articles/${props.articleId}/materials?scope=article&kind=image`)
  const common = await api.get('/api/materials/common?kind=image')
  imageMaterials.value = [...r.materials, ...common.materials]
    .filter((m: Material) => m.fetch_status === 'ok')   // 水印图可用，仅打标
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

async function removeBlock(blockId: string) {
  const r = await api.put(`/api/drafts/${draftId.value}/edit`,
    { ops: [{ op: 'remove', block_id: blockId }] })
  message.success(`已移除（v${r.version}）`)
  selectedId.value = null
  await load()
}

/* ---------- 融合插入（素材面板触发） ---------- */

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
  <div class="flex gap-5 items-start">
    <!-- 文档区 -->
    <div class="flex-1 min-w-0 panel p-7 reader" @click.self="selectedId = null">
      <NSpin :show="loading">
        <div v-if="!doc && !loading" class="py-20 text-center">
          <p class="text-[15px]" style="color: var(--muted);">还没有文案。</p>
          <p class="text-sm mt-2" style="color: var(--faint);">收集完成后，点顶部「开始洗稿」。</p>
        </div>

        <template v-if="doc">
          <div v-for="b in doc.blocks" :key="b.id"
               class="block-item px-2 py-1"
               :class="{ selected: selectedId === b.id, editing: editingId === b.id }"
               @click="clickBlock(b)" @dblclick="dblclickBlock(b)">
            <template v-if="editingId !== b.id">
              <h1 v-if="b.type === 'heading' && b.level === 1">{{ b.text }}</h1>
              <h2 v-else-if="b.type === 'heading'">{{ b.text }}</h2>
              <p v-else-if="b.type === 'paragraph'">{{ b.text }}</p>
              <blockquote v-else-if="b.type === 'quote'">{{ b.text }}</blockquote>
              <div v-else-if="b.type === 'image'" class="my-4">
                <img v-if="b.asset_id" :src="assetUrl(b.asset_id)" :alt="b.caption || ''" />
                <div v-else class="rounded-md h-40 grid place-items-center text-sm"
                     style="background: var(--raised); color: var(--faint);">
                  图片已移除（双击重新选择）</div>
                <div class="caption">{{ b.caption }}<span v-if="b.source"> · {{ b.source }}</span></div>
              </div>
              <div v-else-if="b.type === 'video'"
                   class="my-4 rounded-md h-48 grid place-items-center text-sm"
                   style="background: var(--raised); color: var(--muted);">
                视频素材（在发布包中获取）</div>
              <hr v-else-if="b.type === 'divider'" />
            </template>
            <textarea v-else v-model="editText" @blur="saveEdit" @keyup.esc="editingId = null"
                      class="w-full outline-none bg-transparent text-[15px] leading-[1.9] resize-none"
                      :rows="Math.max(3, Math.ceil(editText.length / 40))" v-focus></textarea>
          </div>

          <div class="text-center text-xs mt-8" style="color: var(--faint);">
            双击段落进入编辑 · 单击选中后可 AI 改写 · 双击图片可替换
          </div>
        </template>
      </NSpin>
    </div>

    <!-- 侧栏 -->
    <div class="w-72 shrink-0 space-y-4 sticky top-16">
      <!-- 版本 -->
      <div class="panel p-4">
        <div class="text-xs font-semibold mb-2" style="color: var(--muted);">版本</div>
        <NSelect size="small" :value="viewingVersion" @update:value="(v: number) => load(v)"
                 :options="versions.map(v => ({ label: `v${v.version} · ${originLabel(v.origin)}${v.status === 'finalized' ? ' · 定稿' : ''}`, value: v.version }))" />
        <div class="text-xs mt-2" style="color: var(--faint);">
          历史版本只读；编辑始终作用于最新版。
          <span v-if="doc" class="num">当前 {{ doc.meta.word_count }} 字。</span>
        </div>
      </div>

      <!-- 标题候选（独立框） -->
      <div class="panel p-4">
        <div class="text-xs font-semibold mb-2" style="color: var(--muted);">标题候选</div>
        <NInput size="small" v-model:value="metaTitle" placeholder="主标题"
                :disabled="!doc || !isLatest || finalized" />
        <NInput size="small" v-model:value="metaTitleAlts" type="textarea"
                :autosize="{ minRows: 2, maxRows: 4 }" class="mt-2"
                placeholder="备选标题，每行一个"
                :disabled="!doc || !isLatest || finalized" />
        <NButton size="tiny" class="mt-2" :loading="metaSaving === 'title'"
                 :disabled="!doc || !isLatest || finalized"
                 @click="saveMeta('title')">保存标题</NButton>
      </div>

      <!-- 一句话总结（独立框） -->
      <div class="panel p-4">
        <div class="text-xs font-semibold mb-2" style="color: var(--muted);">一句话总结</div>
        <NInput size="small" v-model:value="metaOneLiner" type="textarea"
                :autosize="{ minRows: 2, maxRows: 3 }" placeholder="≤40 字"
                :disabled="!doc || !isLatest || finalized" />
        <div class="flex items-center justify-between mt-2">
          <span class="text-xs num" style="color: var(--faint);">{{ metaOneLiner.length }} 字</span>
          <NButton size="tiny" :loading="metaSaving === 'one_liner'"
                   :disabled="!doc || !isLatest || finalized"
                   @click="saveMeta('one_liner')">保存总结</NButton>
        </div>
      </div>

      <!-- 关键词（独立框） -->
      <div class="panel p-4">
        <div class="text-xs font-semibold mb-2" style="color: var(--muted);">关键词</div>
        <NInput size="small" v-model:value="metaKeywords" placeholder="空格或逗号分隔"
                :disabled="!doc || !isLatest || finalized" />
        <NButton size="tiny" class="mt-2" :loading="metaSaving === 'keywords'"
                 :disabled="!doc || !isLatest || finalized"
                 @click="saveMeta('keywords')">保存关键词</NButton>
      </div>

      <!-- 块操作 -->
      <div class="panel p-4" v-if="doc && isLatest && !finalized">
        <div class="text-xs font-semibold mb-2" style="color: var(--muted);">选中块操作</div>
        <div class="grid grid-cols-2 gap-2">
          <NButton size="small" :disabled="!selectedId" @click="openAi('rewrite')">AI 重写</NButton>
          <NButton size="small" :disabled="!selectedId" @click="openAi('shorten')">缩写</NButton>
          <NButton size="small" :disabled="!selectedId" @click="openAi('expand')">扩写</NButton>
          <NButton size="small" :disabled="!selectedId" @click="openAi('custom')">自定义…</NButton>
          <NButton size="small" tertiary type="error" :disabled="!selectedId"
                   @click="selectedId && removeBlock(selectedId)">删除块</NButton>
        </div>
      </div>

      <NButton block type="primary" :disabled="!doc" @click="emit('goto-review')">去审稿 →</NButton>
    </div>

    <!-- AI 指令弹窗 -->
    <NModal v-model:show="aiModal" preset="card" title="AI 改写选中段落" class="!max-w-lg">
      <div class="space-y-3">
        <NInput v-model:value="aiInstruction" type="textarea" :autosize="{ minRows: 3 }"
                placeholder="改写指令，如：更口语一点 / 压到 100 字以内 / 补充 xx 背景" />
        <div class="flex justify-end gap-2">
          <NButton size="small" @click="aiModal = false">取消</NButton>
          <NButton size="small" type="primary" :loading="aiBusy" @click="runAi">生成新版本</NButton>
        </div>
      </div>
    </NModal>

    <!-- 图片选择弹窗 -->
    <NModal v-model:show="imgModal" preset="card" title="从素材库替换图片" class="!max-w-2xl">
      <div class="grid grid-cols-4 gap-3 max-h-96 overflow-auto">
        <div v-for="m in imageMaterials" :key="m.id" class="cursor-pointer group relative"
             @click="replaceImage(m)">
          <div class="aspect-square rounded-md overflow-hidden panel group-hover:outline-2"
               style="background: var(--raised);">
            <img :src="api.absUrl(m.url)" class="w-full h-full object-cover" loading="lazy" />
          </div>
          <span v-if="m.watermark === 1"
                class="absolute top-1.5 left-1.5 px-1.5 py-0.5 rounded text-[11px]"
                style="background: var(--pill-warn-bg); color: var(--pill-warn-ink);">水印</span>
          <div class="text-xs truncate mt-1" style="color: var(--faint);">{{ m.title }}</div>
        </div>
      </div>
      <div v-if="!imageMaterials.length" class="py-10 text-center text-sm"
           style="color: var(--faint);">素材库暂无可用图片</div>
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
  directives: {
    focus: { mounted: (el: HTMLElement) => el.focus() },
  },
}
</script>
