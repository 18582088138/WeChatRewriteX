<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { NButton, NCheckbox, NEmpty, useMessage } from 'naive-ui'
import { api } from '../api'
import { useAppStore } from '../stores/app'
import type { PublishJob } from '../types'

const props = defineProps<{ articleId: string }>()
const message = useMessage()
const store = useAppStore()

const PLATFORMS = [
  { key: 'wechat_mp', label: '微信公众号', desc: '排版 HTML（整页复制进编辑器）+ Markdown + 配图' },
  { key: 'xhs', label: '小红书', desc: '分页卡片组图（1080×1440 PNG）+ 标题正文话题' },
  { key: 'weibo', label: '微博', desc: '可配置摘要 + 话题签名 + 媒体清单（默认≤9图）' },
  { key: 'x', label: 'X', desc: '逐条推文 + 回复顺序 + 媒体清单（普通帖文≤280加权字符）' },
]

const selected = ref<string[]>(['wechat_mp', 'xhs'])
const jobs = ref<PublishJob[]>([])
const exportFiles = ref<string[]>([])
const cardFiles = ref<string[]>([])
const docMeta = ref<any>(null)
const busy = ref(false)
const cardsBusy = ref(false)
const retrying = ref<string[]>([])
const cardIndex = ref(-1)
const cardZoom = computed(() => cardIndex.value >= 0 && cardFiles.value[cardIndex.value]
  ? api.fileUrl(cardFiles.value[cardIndex.value]!) : '')
function turnCard(delta: number) {
  cardIndex.value = Math.max(0, Math.min(cardFiles.value.length - 1, cardIndex.value + delta))
}
function onCardKey(event: KeyboardEvent) {
  if (!cardZoom.value || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey ||
      (event.target as HTMLElement)?.closest('input,textarea,select,[contenteditable="true"]')) return
  if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
    event.preventDefault()
    turnCard(event.key === 'ArrowLeft' ? -1 : 1)
  } else if (event.key === 'Escape') cardIndex.value = -1
}
onMounted(() => window.addEventListener('keydown', onCardKey))
watch(cardFiles, () => { if (cardIndex.value >= cardFiles.value.length) cardIndex.value = -1 })

let controller: AbortController | null = null
let generation = 0
let refreshTimer: ReturnType<typeof setTimeout> | null = null
async function load() {
  const current = ++generation
  controller?.abort()
  controller = new AbortController()
  const signal = controller.signal
  const base = `/api/articles/${props.articleId}`
  try {
    const [published, ex, draft] = await Promise.all([
      api.get(`${base}/publish-jobs`, signal), api.get(`${base}/exports`, signal),
      api.get(`${base}/draft`, signal).catch(() => null),
    ])
    if (current !== generation) return
    jobs.value = published.jobs
    exportFiles.value = ex.files
    cardFiles.value = exportFiles.value.filter(f => f.includes('cards') && f.endsWith('.png'))
    docMeta.value = draft?.draft.doc.meta || null
  } catch (error: any) { if (!signal.aborted) message.error(error.message) }
}
onMounted(load)
watch(() => props.articleId, load)
watch(() => store.articleTicks[props.articleId] || 0, load)
onUnmounted(() => {
  window.removeEventListener('keydown', onCardKey)
  generation++
  controller?.abort()
  if (refreshTimer) clearTimeout(refreshTimer)
})

const latestByPlatform = computed(() => {
  const map: Record<string, PublishJob> = {}
  for (const j of jobs.value) if (!map[j.platform]) map[j.platform] = j   // 列表按时间倒序，先出现为最新
  return map
})

/** 参考链接（与创作分页同源）：去重后展示「标题 - 链接」，新窗口打开 */
const refLinks = computed(() => {
  const seen = new Set<string>()
  return (docMeta.value?.ref_links || [])
    .filter((r: any) => {
      const k = (r.url || '').trim().toLowerCase().replace(/\/+$/, '') || 't:' + (r.title || '')
      if ((!r.url && !r.title) || seen.has(k)) return false
      seen.add(k)
      return true
    })
})

async function publish() {
  if (!selected.value.length) return
  busy.value = true
  try {
    await api.post(`/api/articles/${props.articleId}/publish`, { platforms: selected.value })
    message.success('导出任务已提交')
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = setTimeout(load, 1500)
  } catch (e: any) { message.error(e.message) } finally { busy.value = false }
}

async function retryPlatform(platform: string) {
  if (retrying.value.includes(platform)) return
  retrying.value.push(platform)
  try {
    await api.post(`/api/articles/${props.articleId}/publish/retry`, { platform })
    message.success('已按原定稿快照重试失败平台')
  } catch (error: any) { message.error(error.message) }
  finally { retrying.value = retrying.value.filter(p => p !== platform) }
}

async function genCards() {
  cardsBusy.value = true
  try {
    const r = await api.post(`/api/articles/${props.articleId}/cards`)
    cardFiles.value = r.files
    message.success(`已生成 ${r.files.length} 张卡片`)
  } catch (e: any) { message.error(e.message) } finally { cardsBusy.value = false }
}

/** 点击平台条目：打开该平台发布包的本地文件夹（exports/<platform>/） */
async function openPlatformDir(platform: string) {
  try {
    await api.post(`/api/articles/${props.articleId}/exports/reveal`, { platform })
  } catch (e: any) { message.warning(e.message) }
}

function jobMessage(j: PublishJob): string {
  try { return JSON.parse(j.result_json).message || '' } catch { return '' }
}
</script>

<template>
  <div class="space-y-5">
    <!-- 行 1：平台选择 + 文案信息（与创作分页同源） -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
      <div class="panel p-5">
        <div class="font-semibold mb-1">选择平台，生成发布包</div>
        <div class="text-xs mb-4" style="color: var(--faint);">
          一阶段统一导出到本地发布包（文章素材文件夹 exports/ 各平台固定目录，成功后替换），由你在各平台手动发布；
          自动推送草稿箱为二阶段能力。
        </div>
        <div class="space-y-2">
          <div v-for="p in PLATFORMS" :key="p.key"
                 class="flex items-start gap-3 p-3 rounded-md transition-colors hover:bg-[var(--raised)]"
                 style="border: 1px solid var(--border);">
            <NCheckbox :checked="selected.includes(p.key)"
                       @update:checked="(v: boolean) => {
                         selected = v ? [...selected, p.key] : selected.filter(x => x !== p.key) }" />
            <div class="flex-1 min-w-0">
              <div class="font-medium text-sm">{{ p.label }}</div>
              <div class="text-xs mt-0.5" style="color: var(--faint);">{{ p.desc }}</div>
              <div v-if="latestByPlatform[p.key]" class="text-xs mt-1"
                   :style="latestByPlatform[p.key].status === 'done'
                     ? 'color: var(--pill-pos-ink);' : 'color: var(--pill-neg-ink);'">
                {{ latestByPlatform[p.key].status === 'done' ? '已生成' : '失败' }} ·
                {{ jobMessage(latestByPlatform[p.key]) }}
                <span class="num"> · {{ latestByPlatform[p.key].created_at.slice(5, 16) }}</span>
              </div>
            </div>
            <NButton v-if="latestByPlatform[p.key]?.status === 'failed'" size="tiny"
                     :loading="retrying.includes(p.key)"
                     @click="retryPlatform(p.key)">重试</NButton>
            <button v-if="exportFiles.some(f => f.includes(`/exports/${p.key}/`))"
                    class="text-xs shrink-0 px-2 py-1 rounded hover:bg-[var(--surface)]"
                    style="color: var(--accent-ink); border: 1px solid var(--border);"
                    title="打开该平台发布包文件夹"
                    @click.stop="openPlatformDir(p.key)">打开文件夹</button>
          </div>
        </div>
        <NButton block type="primary" class="mt-4" :loading="busy" @click="publish">
          生成发布包
        </NButton>
      </div>

      <!-- 文案信息（与创作分页底部信息窗同源） -->
      <div class="panel p-5">
        <div class="font-semibold mb-3">文案信息</div>
        <div class="space-y-3 text-sm">
          <div>
            <div class="text-[11px] mb-1" style="color: var(--faint);">文章总结</div>
            <div style="color: var(--ink-700);">{{ docMeta?.one_liner || '（无）' }}</div>
          </div>
          <div>
            <div class="text-[11px] mb-1" style="color: var(--faint);">关键词</div>
            <div style="color: var(--accent-ink);">
              {{ (docMeta?.keywords || []).map((k: string) => '#' + k).join('，') || '（无）' }}</div>
          </div>
          <div>
            <div class="text-[11px] mb-1" style="color: var(--faint);">参考链接</div>
            <div v-if="refLinks.length" class="space-y-1">
              <div v-for="(r, i) in refLinks" :key="i" class="truncate text-xs">
                <a v-if="r.url" :href="r.url" target="_blank" rel="noopener"
                   class="hover:underline" style="color: var(--accent-ink);"
                   :title="r.url">{{ r.title || r.url }} - {{ r.url }}</a>
                <span v-else style="color: var(--muted);">{{ r.title }}</span>
              </div>
            </div>
            <div v-else class="text-xs" style="color: var(--faint);">（无）</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 行 2：导出文件（左，滚动） | 小红书卡片预览（右，优先展示）—— 同高、底部对齐 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 pub-row2">
      <div class="panel p-5 flex flex-col pub-box">
        <div class="font-semibold mb-3 shrink-0">导出文件（点击查看 / 下载）</div>
        <div v-if="!exportFiles.length" class="py-12 text-center text-sm"
             style="color: var(--faint);">还没有导出内容</div>
        <div v-else class="divide-y overflow-y-auto flex-1 min-h-0" style="--tw-divide-opacity: 1;">
          <a v-for="f in exportFiles" :key="f" :href="api.fileUrl(f)" target="_blank"
             class="flex items-center gap-3 py-2 text-sm hover:bg-[var(--raised)] px-2 rounded"
             style="border-color: var(--rule);">
            <span class="text-xs px-1.5 py-0.5 rounded shrink-0"
                  style="background: var(--pill-info-bg); color: var(--pill-info-ink);">{{
                  f.endsWith('.png') ? '图片' :
                  f.endsWith('.txt') || f.endsWith('.md') ? '文本' :
                  f.endsWith('.html') ? '网页' : '文件' }}</span>
            <span class="truncate" style="color: var(--ink-700);">{{ f.split(/[\\/]/).slice(-2).join('/') }}</span>
          </a>
        </div>
      </div>

      <!-- 小红书卡片预览（点击看大图） -->
      <div class="panel p-5 flex flex-col pub-box">
        <div class="flex items-center mb-3 shrink-0">
          <div class="font-semibold">小红书卡片预览</div>
          <div class="flex-1"></div>
          <NButton size="small" :loading="cardsBusy" @click="genCards">重新生成卡片</NButton>
        </div>
        <div v-if="cardFiles.length" class="grid grid-cols-3 gap-2 overflow-y-auto flex-1 min-h-0">
          <img v-for="f in cardFiles" :key="f" :src="api.fileUrl(f)"
               class="rounded-md w-full panel cursor-zoom-in" loading="lazy"
               @click="cardIndex = cardFiles.indexOf(f)" />
        </div>
        <div v-else class="text-xs" style="color: var(--faint);">
          尚未生成卡片（生成发布包时会自动生成，也可手动生成）。
        </div>
      </div>
    </div>

    <!-- 卡片大图弹窗：点击外部关闭 -->
    <div v-if="cardZoom" class="zoom-mask" role="dialog" aria-label="小红书卡片阅览" aria-modal="true" @click="cardIndex = -1">
      <button class="card-prev" aria-label="上一张卡片" :disabled="cardIndex === 0" @click.stop="turnCard(-1)">←</button>
      <img :src="cardZoom" :alt="`小红书卡片 ${cardIndex + 1}`" class="zoom-img" @click.stop />
      <button class="card-next" aria-label="下一张卡片" :disabled="cardIndex === cardFiles.length - 1" @click.stop="turnCard(1)">→</button>
      <div class="card-counter">{{ cardIndex + 1 }} / {{ cardFiles.length }} · ← → 翻页 · Esc 关闭</div>
    </div>
  </div>
</template>

<style scoped>
.pub-row2 { align-items: stretch; }
.pub-box { height: 560px; }
.zoom-mask {
  position: fixed; inset: 0; z-index: 60; background: rgba(20, 20, 20, .62);
  display: flex; align-items: center; justify-content: center; cursor: zoom-out;
}
.zoom-img { max-width: min(92vw, 720px); max-height: 92vh; border-radius: 10px;
  cursor: default; box-shadow: 0 18px 60px rgba(0,0,0,.35); }
.card-prev, .card-next { color: white; font-size: 28px; padding: 12px; cursor: pointer; }
.card-prev:disabled, .card-next:disabled { opacity: .3; cursor: default; }
.card-counter { position: absolute; bottom: 8px; color: white; background: #222b; padding: 4px 12px; border-radius: 8px; }
</style>

