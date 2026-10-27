<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
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
  { key: 'weibo', label: '微博', desc: '≤140 字短文 + 话题 + 配图（≤9 张）' },
  { key: 'x', label: 'X', desc: '推文串（hook + 要点 + 来源链接）' },
]

const selected = ref<string[]>(['wechat_mp', 'xhs'])
const jobs = ref<PublishJob[]>([])
const exportFiles = ref<string[]>([])
const cardFiles = ref<string[]>([])
const docMeta = ref<any>(null)
const busy = ref(false)
const cardsBusy = ref(false)

async function load() {
  jobs.value = (await api.get(`/api/articles/${props.articleId}/publish-jobs`)).jobs
  const ex = await api.get(`/api/articles/${props.articleId}/exports`)
  exportFiles.value = ex.files
  cardFiles.value = exportFiles.value.filter(f => f.includes('cards') && f.endsWith('.png'))
  try {
    docMeta.value = (await api.get(`/api/articles/${props.articleId}/draft`)).draft.doc.meta
  } catch { docMeta.value = null }
}
onMounted(load)
watch(() => store.workbenchTick, load)

const latestByPlatform = computed(() => {
  const map: Record<string, PublishJob> = {}
  for (const j of jobs.value) map[j.platform] = j   // 列表按时间倒序，先出现为最新
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
    setTimeout(load, 1500)
  } catch (e: any) { message.error(e.message) } finally { busy.value = false }
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
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
    <div class="space-y-4">
      <div class="panel p-5">
        <div class="font-semibold mb-1">选择平台，生成发布包</div>
        <div class="text-xs mb-4" style="color: var(--faint);">
          一阶段统一导出到本地发布包（文章素材文件夹 exports/ 内），由你在各平台手动发布；
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
            <button v-if="latestByPlatform[p.key]?.status === 'done'"
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

      <!-- 创作信息同步（与创作分页底部信息窗同源） -->
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

      <div class="panel p-5">
        <div class="flex items-center mb-3">
          <div class="font-semibold">小红书卡片预览</div>
          <div class="flex-1"></div>
          <NButton size="small" :loading="cardsBusy" @click="genCards">重新生成卡片</NButton>
        </div>
        <div v-if="cardFiles.length" class="grid grid-cols-3 gap-2">
          <img v-for="f in cardFiles" :key="f" :src="api.fileUrl(f)"
               class="rounded-md w-full panel" loading="lazy" />
        </div>
        <div v-else class="text-xs" style="color: var(--faint);">
          尚未生成卡片（生成发布包时会自动生成，也可手动生成）。
        </div>
      </div>
    </div>

    <!-- 导出文件列表 -->
    <div class="panel p-5">
      <div class="font-semibold mb-3">导出文件（点击查看 / 下载）</div>
      <div v-if="!exportFiles.length" class="py-12 text-center text-sm"
           style="color: var(--faint);">还没有导出内容</div>
      <div v-else class="divide-y" style="--tw-divide-opacity: 1;">
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
  </div>
</template>
