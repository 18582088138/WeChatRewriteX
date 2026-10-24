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
      <div class="panel p-0.5 flex" style="border-radius: 8px;">
        <button v-for="s in [['article', '本文章素材'], ['common', '公共素材库']]" :key="s[0]"
                class="px-4 h-8 rounded-md text-sm transition-colors"
                :style="scope === s[0]
                  ? 'background: var(--active); color: var(--text); font-weight: 600;'
                  : 'color: var(--muted);'"
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

    <div v-if="!materials.length" class="panel py-16 text-center">
      <p class="text-[15px]" style="color: var(--muted);">暂无素材。</p>
      <p class="text-sm mt-2" style="color: var(--faint);">
        收集完成后素材会出现在这里；也可粘贴网址、上传文件，或拷入 inbox 文件夹后点「扫描 inbox」。
      </p>
    </div>

    <div v-for="g in groups" :key="g.kind" class="mb-6">
      <div class="text-sm font-semibold mb-2" style="color: var(--muted);">
        {{ KIND_LABEL[g.kind] }} · <span class="num">{{ g.items.length }}</span>
      </div>

      <!-- 图片网格 -->
      <div v-if="g.kind === 'image'" class="grid grid-cols-3 md:grid-cols-5 gap-3">
        <div v-for="m in g.items" :key="m.id" class="relative group">
          <div class="aspect-square rounded-md overflow-hidden panel" style="background: var(--raised);">
            <img v-if="m.url" :src="api.absUrl(m.url)"
                 class="w-full h-full object-cover" loading="lazy" />
          </div>
          <div class="absolute top-1.5 left-1.5 flex gap-1">
            <span v-if="m.watermark === 1" class="px-1.5 py-0.5 rounded text-[11px]"
                  style="background: var(--pill-warn-bg); color: var(--pill-warn-ink);">水印</span>
            <span v-if="m.fetch_status === 'too_small'"
                  class="px-1.5 py-0.5 rounded text-[11px]"
                  style="background: var(--pill-info-bg); color: var(--pill-info-ink);">过小</span>
          </div>
          <button class="absolute top-1.5 right-1.5 w-6 h-6 rounded-full text-xs
                         opacity-0 group-hover:opacity-100 transition-opacity"
                  style="background: rgba(20,20,20,.6); color: #fff;"
                  @click="remove(m)">×</button>
          <div class="text-xs mt-1 truncate" style="color: var(--faint);">{{ m.title || m.id }}</div>
        </div>
      </div>

      <!-- 其他类型列表 -->
      <div v-else class="panel divide-y" style="--tw-divide-opacity: 1; border-color: var(--rule);">
        <div v-for="m in g.items" :key="m.id"
             class="px-4 py-3 flex items-center gap-3"
             style="border-color: var(--rule);">
          <NCheckbox v-if="m.kind === 'text'" :checked="selected.has(m.id)"
                     @update:checked="toggleSelect(m.id)" />
          <div class="flex-1 min-w-0">
            <div class="text-sm font-medium truncate">{{ m.title || m.id }}</div>
            <div class="text-xs flex items-center gap-2 mt-0.5 flex-wrap" style="color: var(--faint);">
              <span v-if="m.ref_type" class="px-1.5 py-0.5 rounded"
                    style="background: var(--pill-info-bg); color: var(--pill-info-ink);">
                {{ REF_LABEL[m.ref_type] || m.ref_type }}</span>
              <span v-if="m.source_url" class="truncate max-w-md">{{ m.source_url }}</span>
              <span v-if="m.note" class="truncate">{{ m.note }}</span>
              <span v-if="m.fetch_status !== 'ok'" style="color: var(--pill-neg-ink);">{{ m.fetch_status }}</span>
            </div>
          </div>
          <button class="text-lg px-2 hover:opacity-70" style="color: var(--faint);"
                  @click="remove(m)">×</button>
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
