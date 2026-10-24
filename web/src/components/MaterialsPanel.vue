<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NCheckbox, NEmpty, NInput, NModal, NTag, useMessage } from 'naive-ui'
import { api } from '../api'
import { useAppStore } from '../stores/app'
import type { Material } from '../types'

const props = defineProps<{ articleId: string }>()
const emit = defineEmits<{ (e: 'insert-refs', materialIds: string[]): void }>()
const message = useMessage()
const store = useAppStore()

const scope = ref<'article' | 'common'>('article')
const materials = ref<Material[]>([])
const selected = ref<Set<string>>(new Set())
const showAddUrl = ref(false)
const addUrl = ref('')
const busy = ref(false)

async function load() {
  const url = scope.value === 'article'
    ? `/api/articles/${props.articleId}/materials?scope=article`
    : '/api/materials/common'
  materials.value = (await api.get(url)).materials
}
onMounted(load)
watch(() => store.workbenchTick, load)
watch(scope, load)

const KIND_LABEL: Record<string, string> = {
  text: '文本', image: '图片', video: '视频', doc: '文档', link: '链接',
}
const REF_LABEL: Record<string, string> = {
  primary: '原文', reference: '参考', foundational: '基础资料',
}

const groups = computed(() => {
  const order = ['text', 'image', 'video', 'doc', 'link']
  return order
    .map(k => ({ kind: k, items: materials.value.filter(m => m.kind === k) }))
    .filter(g => g.items.length)
})

function toggleSelect(id: string) {
  selected.value.has(id) ? selected.value.delete(id) : selected.value.add(id)
  selected.value = new Set(selected.value)
}

async function addByUrl() {
  if (!addUrl.value.trim()) return
  busy.value = true
  try {
    const r = await api.post(`/api/articles/${props.articleId}/materials/url`, { url: addUrl.value.trim() })
    message.success(`已抓取: ${r.title || r.material_id}`)
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

async function remove(m: Material) {
  await api.del(`/api/materials/${m.id}`)
  await load()
}

function insertSelected() {
  if (!selected.value.size) return
  emit('insert-refs', [...selected.value])
  selected.value = new Set()
}
</script>

<template>
  <div>
    <div class="flex items-center gap-2 mb-4 flex-wrap">
      <div class="bg-white rounded-full shadow-card p-1 flex">
        <button v-for="s in [['article', '本文章素材'], ['common', '公共素材库']]" :key="s[0]"
                class="px-4 h-8 rounded-full text-sm transition-colors"
                :class="scope === s[0] ? 'bg-ink-900 text-white' : 'text-ink-500'"
                @click="scope = s[0] as any">{{ s[1] }}</button>
      </div>
      <div class="flex-1"></div>
      <NButton size="small" @click="showAddUrl = true">+ 粘贴网址</NButton>
      <label class="inline-flex">
        <input type="file" class="hidden" @change="upload" />
        <NButton size="small" tag="span">+ 上传文件</NButton>
      </label>
      <NButton size="small" quaternary @click="scanInbox">扫描 inbox</NButton>
      <NButton v-if="selected.size" size="small" type="primary" @click="insertSelected">
        融合插入 {{ selected.size }} 段到文案
      </NButton>
    </div>

    <NEmpty v-if="!materials.length" description="暂无素材。收集完成后素材会出现在这里，也可手动添加。"
            class="py-16" />

    <div v-for="g in groups" :key="g.kind" class="mb-6">
      <div class="text-sm font-semibold text-ink-500 mb-2">{{ KIND_LABEL[g.kind] }} · {{ g.items.length }}</div>

      <!-- 图片网格 -->
      <div v-if="g.kind === 'image'" class="grid grid-cols-3 md:grid-cols-5 gap-3">
        <div v-for="m in g.items" :key="m.id" class="relative group">
          <div class="aspect-square rounded-xl overflow-hidden bg-slate-100 shadow-card">
            <img v-if="m.url" :src="api.absUrl(m.url)"
                 class="w-full h-full object-cover" loading="lazy" />
          </div>
          <div class="absolute top-1.5 left-1.5 flex gap-1">
            <span v-if="m.watermark === 1" class="px-1.5 py-0.5 rounded text-[10px] bg-rose-500 text-white">水印</span>
            <span v-if="m.fetch_status === 'too_small'"
                  class="px-1.5 py-0.5 rounded text-[10px] bg-slate-500 text-white">过小</span>
          </div>
          <button class="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-black/50 text-white text-xs
                         opacity-0 group-hover:opacity-100 transition-opacity"
                  @click="remove(m)">×</button>
          <div class="text-[11px] text-ink-400 mt-1 truncate">{{ m.title || m.id }}</div>
        </div>
      </div>

      <!-- 其他类型列表 -->
      <div v-else class="space-y-2">
        <div v-for="m in g.items" :key="m.id"
             class="bg-white rounded-xl shadow-card px-4 py-3 flex items-center gap-3">
          <NCheckbox v-if="m.kind === 'text'" :checked="selected.has(m.id)"
                     @update:checked="toggleSelect(m.id)" />
          <div class="flex-1 min-w-0">
            <div class="text-sm font-medium truncate">{{ m.title || m.id }}</div>
            <div class="text-xs text-ink-400 flex items-center gap-2 mt-0.5 flex-wrap">
              <NTag v-if="m.ref_type" size="tiny" :bordered="false">{{ REF_LABEL[m.ref_type] || m.ref_type }}</NTag>
              <span v-if="m.source_url" class="truncate max-w-md">{{ m.source_url }}</span>
              <span v-if="m.fetch_status !== 'ok'" class="text-rose-500">{{ m.fetch_status }}</span>
            </div>
          </div>
          <button class="text-ink-400 hover:text-rose-500 text-lg px-2" @click="remove(m)">×</button>
        </div>
      </div>
    </div>

    <NModal v-model:show="showAddUrl" preset="card" title="按网址添加参考素材" class="!max-w-lg">
      <div class="space-y-3">
        <NInput v-model:value="addUrl" placeholder="https://…（将抓取正文与图片入库）" />
        <div class="flex justify-end gap-2">
          <NButton @click="showAddUrl = false">取消</NButton>
          <NButton type="primary" :loading="busy" @click="addByUrl">抓取并入库</NButton>
        </div>
      </div>
    </NModal>
  </div>
</template>
