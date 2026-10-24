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
const highlightBlockId = ref<string | null>(null)

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

function assetUrl(assetId: string): string {
  return api.absUrl(`/api/materials/${assetId}/file`)
}

function originLabel(origin: string): string {
  return ({ agent: 'AI', human: '人工', auto_fix: 'AI修复', insert_refs: '资料插入' } as
    Record<string, string>)[origin] || origin
}

const isLatest = computed(() =>
  !versions.value.length || viewingVersion.value === versions.value[0]?.version)
const finalized = computed(() => versions.value[0]?.status === 'finalized')

async function load(version?: number) {
  loading.value = true
  try {
    const r = await api.get(`/api/articles/${props.articleId}/draft` +
                            (version ? `?version=${version}` : ''))
    doc.value = r.draft.doc
    draftId.value = r.draft.id
    versions.value = r.versions
    viewingVersion.value = r.draft.version
  } catch {
    doc.value = null
  } finally {
    loading.value = false
  }
}
onMounted(() => load())
watch(() => store.workbenchTick, () => load(viewingVersion.value ?? undefined))

/* ---------- 选择 / 编辑 ---------- */

function clickBlock(b: Block) {
  selectedId.value = b.id
  store.anchorBlockId = b.id
}

function dblclickBlock(b: Block) {
  if (!isLatest.value || finalized.value) return
  if (b.type === 'image' || b.type === 'video') {
    openImagePicker(b.id)
    return
  }
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

/* ---------- AI 操作 ---------- */

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

/* ---------- 图片操作 ---------- */

async function openImagePicker(blockId: string) {
  imgBlockId.value = blockId
  const r = await api.get(`/api/articles/${props.articleId}/materials?scope=article&kind=image`)
  const common = await api.get('/api/materials/common?kind=image')
  imageMaterials.value = [...r.materials, ...common.materials]
    .filter((m: Material) => m.fetch_status === 'ok' && m.watermark !== 1)
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

/* ---------- 资料融合插入（素材面板触发） ---------- */

function openInsertRefs(ids: string[]) {
  insertIds.value = ids
  insertInstruction.value = ''
  insertModal.value = true
}

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

function scrollToBlock(blockId: string) {
  highlightBlockId.value = blockId
  document.getElementById('blk-' + blockId)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  setTimeout(() => (highlightBlockId.value = null), 2500)
}
defineExpose({ scrollToBlock, openInsertRefs })
</script>

<template>
  <div class="flex gap-5 items-start">
    <!-- 文档区 -->
    <div class="flex-1 min-w-0 bg-white rounded-2xl shadow-card p-7 reader"
         @click.self="selectedId = null">
      <NSpin :show="loading">
        <NEmpty v-if="!doc && !loading" description="还没有文案。收集完成后点顶部「开始洗稿」。" class="py-20" />

        <template v-if="doc">
          <!-- 元信息 -->
          <div class="mb-6 pb-4 border-b border-slate-100 text-sm text-ink-400 space-y-1">
            <div>一句话：{{ doc.meta.one_liner || '—' }}</div>
            <div>关键词：{{ doc.meta.keywords.join(' · ') || '—' }}　词数：{{ doc.meta.word_count }}</div>
            <div v-if="doc.meta.title_candidates.length">
              标题候选：{{ doc.meta.title_candidates.join(' / ') }}
            </div>
          </div>

          <!-- 块 -->
          <div v-for="b in doc.blocks" :key="b.id" :id="'blk-' + b.id"
               class="block-item px-2 py-1"
               :class="{ selected: selectedId === b.id, editing: editingId === b.id,
                         'highlight-review': highlightBlockId === b.id }"
               @click="clickBlock(b)" @dblclick="dblclickBlock(b)">

            <!-- 预览态 -->
            <template v-if="editingId !== b.id">
              <h1 v-if="b.type === 'heading' && b.level === 1">{{ b.text }}</h1>
              <h2 v-else-if="b.type === 'heading'">{{ b.text }}</h2>
              <p v-else-if="b.type === 'paragraph'">{{ b.text }}</p>
              <blockquote v-else-if="b.type === 'quote'">{{ b.text }}</blockquote>
              <div v-else-if="b.type === 'image'" class="my-4">
                <img v-if="b.asset_id" :src="assetUrl(b.asset_id)" :alt="b.caption || ''" />
                <div v-else class="bg-slate-100 rounded-xl h-40 grid place-items-center text-ink-400 text-sm">
                  图片已移除（双击重新选择）</div>
                <div class="caption">{{ b.caption }}<span v-if="b.source" class="ml-1">· {{ b.source }}</span></div>
              </div>
              <div v-else-if="b.type === 'video'" class="my-4 bg-slate-900 rounded-xl h-48 grid place-items-center text-white/70 text-sm">
                ▶ 视频素材（导出包中获取）</div>
              <hr v-else-if="b.type === 'divider'" />
            </template>

            <!-- 编辑态 -->
            <textarea v-else v-model="editText" @blur="saveEdit" @keyup.esc="editingId = null"
                      class="w-full outline-none bg-transparent text-[15px] leading-[1.9] resize-none"
                      :rows="Math.max(3, Math.ceil(editText.length / 40))" v-focus></textarea>
          </div>

          <div class="text-center text-xs text-ink-400 mt-8">
            双击段落进入编辑 · 单击选中后可 AI 重写 · 双击图片可替换
          </div>
        </template>
      </NSpin>
    </div>

    <!-- 侧栏 -->
    <div class="w-64 shrink-0 space-y-4 sticky top-20">
      <div class="bg-white rounded-2xl shadow-card p-4">
        <div class="text-xs font-semibold text-ink-400 mb-2">版本</div>
        <NSelect size="small" :value="viewingVersion" @update:value="(v: number) => load(v)"
                 :options="versions.map(v => ({ label: `v${v.version} · ${originLabel(v.origin)}${v.status === 'finalized' ? ' · 定稿' : ''}`, value: v.version }))" />
        <div class="text-[11px] text-ink-400 mt-2">历史版本只读；编辑始终作用于最新版。</div>
      </div>

      <div class="bg-white rounded-2xl shadow-card p-4" v-if="doc && isLatest && !finalized">
        <div class="text-xs font-semibold text-ink-400 mb-2">选中块操作</div>
        <div class="grid grid-cols-2 gap-2">
          <NButton size="small" :disabled="!selectedId" @click="openAi('rewrite')">AI 重写</NButton>
          <NButton size="small" :disabled="!selectedId" @click="openAi('shorten')">缩写</NButton>
          <NButton size="small" :disabled="!selectedId" @click="openAi('expand')">扩写</NButton>
          <NButton size="small" :disabled="!selectedId" @click="openAi('custom')">自定义…</NButton>
          <NButton size="small" tertiary type="error" :disabled="!selectedId"
                   @click="selectedId && removeBlock(selectedId)">删除块</NButton>
        </div>
      </div>

      <div class="bg-white rounded-2xl shadow-card p-4">
        <NButton block type="primary" :disabled="!doc" @click="emit('goto-review')">
          去审稿 →
        </NButton>
      </div>
    </div>

    <!-- AI 指令弹窗 -->
    <NModal v-model:show="aiModal" preset="card" title="AI 改写选中段落" class="!max-w-lg">
      <div class="space-y-3">
        <NInput v-model:value="aiInstruction" type="textarea" :autosize="{ minRows: 3 }"
                placeholder="改写指令，如：更口语一点 / 压到 100 字以内 / 补充 xx 背景" />
        <div class="flex justify-end gap-2">
          <NButton @click="aiModal = false">取消</NButton>
          <NButton type="primary" :loading="aiBusy" @click="runAi">生成新版本</NButton>
        </div>
      </div>
    </NModal>

    <!-- 图片选择弹窗 -->
    <NModal v-model:show="imgModal" preset="card" title="从素材库替换图片" class="!max-w-2xl">
      <div class="grid grid-cols-4 gap-3 max-h-96 overflow-auto">
        <div v-for="m in imageMaterials" :key="m.id" class="cursor-pointer group"
             @click="replaceImage(m)">
          <div class="aspect-square rounded-lg overflow-hidden bg-slate-100 group-hover:ring-2 ring-accent">
            <img :src="api.absUrl(m.url)" class="w-full h-full object-cover" loading="lazy" />
          </div>
          <div class="text-[11px] text-ink-400 truncate mt-1">{{ m.title }}</div>
        </div>
      </div>
      <NEmpty v-if="!imageMaterials.length" description="素材库暂无可用图片" class="py-10" />
    </NModal>

    <!-- 融合插入弹窗 -->
    <NModal v-model:show="insertModal" preset="card" title="融合插入参考资料" class="!max-w-lg">
      <div class="space-y-3">
        <div class="text-sm text-ink-500">
          将把 {{ insertIds.length }} 段参考素材融合改写，插入到当前选中段落之后。
        </div>
        <NInput v-model:value="insertInstruction" type="textarea" :autosize="{ minRows: 2 }"
                placeholder="插入指令（可选），如：作为背景补充 / 用来支撑第二段观点" />
        <div class="flex justify-end gap-2">
          <NButton @click="insertModal = false">取消</NButton>
          <NButton type="primary" :loading="aiBusy" @click="runInsert">融合插入</NButton>
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
