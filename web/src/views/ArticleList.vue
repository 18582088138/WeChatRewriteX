<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NInput, NModal, NPagination, NUpload, NUploadDragger,
         useMessage, type UploadFileInfo } from 'naive-ui'
import { api } from '../api'
import { useAppStore } from '../stores/app'
import StatusChip from '../components/StatusChip.vue'

const store = useAppStore()
const router = useRouter()
const message = useMessage()

const filter = ref<string>('全部')
const q = ref('')
const showCreate = ref(false)
const createMode = ref<'url' | 'file'>('url')
const newUrl = ref('')
const newNotes = ref('')
const newTitle = ref('')
const fileList = ref<UploadFileInfo[]>([])
const creating = ref(false)
const scanning = ref(false)

/** 手动扫描 resource/ 下新增的项目文件夹并导入（也可后台每 30s 自动扫描） */
async function scanImports() {
  scanning.value = true
  try {
    const r = await api.post('/api/articles/imports/scan')
    const n = r.imported?.length || 0
    if (n) {
      message.success(`已导入 ${n} 个项目文件夹：${r.imported.map((x: any) => x.folder).join('、').slice(0, 80)}`)
    } else {
      message.info('没有发现新的项目文件夹（resource/ 下未入库的文件夹才会被导入）')
    }
    await store.refreshArticles()
  } catch (e: any) {
    message.error(e.message)
  } finally {
    scanning.value = false
  }
}

const list = computed(() => store.articles)
const counts = computed(() => store.articleCounts)
let searchTimer: ReturnType<typeof setTimeout> | null = null
watch([filter, q], () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    store.articleFilter = filter.value === '全部' ? '' : filter.value
    store.articleSearch = q.value.trim()
    store.articlePage = 1
    store.refreshArticles()
  }, 250)
})
watch(() => store.articlePage, () => store.refreshArticles())
onUnmounted(() => { if (searchTimer) clearTimeout(searchTimer) })

/** 从上传文件里推断主题名：优先公共父目录名（文件夹上传时 webkitRelativePath 带目录） */
function guessTitle(files: UploadFileInfo[]): string {
  const rel = (files[0]?.file as any)?.webkitRelativePath as string | undefined
  if (rel && rel.includes('/')) return rel.split('/')[0]
  return (files[0]?.name || '本地收集').replace(/\.[^.]+$/, '').slice(0, 40)
}

async function create() {
  if (createMode.value === 'url') {
    if (!newUrl.value.trim()) { message.warning('请粘贴文章链接'); return }
    creating.value = true
    try {
      const r = await api.post('/api/articles', { url: newUrl.value.trim(), user_notes: newNotes.value })
      showCreate.value = false
      newUrl.value = ''; newNotes.value = ''
      message.success('已录入，开始收集资料')
      await store.refreshArticles()
      router.push(`/articles/${r.article.id}`)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      creating.value = false
    }
    return
  }
  // 本地文件模式：先立档（不自动收集），再批量上传（自动识别类型分流）
  const files = fileList.value.filter(f => f.file).map(f => f.file as File)
  if (!files.length) { message.warning('请先选择文件或文件夹'); return }
  creating.value = true
  try {
    const title = newTitle.value.trim() || guessTitle(fileList.value)
    const r = await api.post('/api/articles',
      { title, user_notes: newNotes.value, auto_collect: false })
    const aid = r.article.id
    const up = await api.uploadBatch(`/api/articles/${aid}/materials/upload-batch`, files)
    if (up.failed?.length) {
      message.warning(`已上传 ${up.ok.length}/${up.total}，失败 ${up.failed.length} 个（素材库可重试）`)
    } else {
      message.success(`已收集 ${up.ok.length} 个文件，自动分流到素材库对应目录`)
    }
    showCreate.value = false
    fileList.value = []; newTitle.value = ''; newNotes.value = ''
    await store.refreshArticles()
    router.push(`/articles/${aid}`)
  } catch (e: any) {
    message.error(e.message)
  } finally {
    creating.value = false
  }
}

const STAGE_TEXT: Record<string, string> = { collect: '收集', create: '创作', review: '审稿', publish: '导出' }
function progressText(a: any): string {
  const p = a.progress
  if (!p) return ''
  const cur = [...(p.running || []), ...(p.pending || [])].map(s => STAGE_TEXT[s] || s)
  return cur.length ? `进行中: ${cur.join(' → ')}` : ''
}

onMounted(store.refreshArticles)
</script>

<template>
  <div class="min-h-screen">
    <!-- 顶栏：朴素一条，品牌标记 + 名称 + 链接 + 一个主操作 -->
    <header class="bg-surface border-b" style="border-color: var(--border); background: var(--surface);">
      <div class="max-w-[1200px] mx-auto px-6 h-12 flex items-center gap-3">
        <div class="flex items-center gap-2.5">
          <span class="inline-block w-4 h-4" style="background: var(--accent);"></span>
          <span class="font-semibold text-[15px] tracking-tight">文枢</span>
          <span class="text-xs hidden md:inline" style="color: var(--faint);">文枢 - 自媒体 Studio · AI 要闻再创作工作台</span>
          <span class="text-xs md:hidden" style="color: var(--faint);">AI 要闻再创作工作台</span>
        </div>
        <div class="flex-1"></div>
        <button class="text-sm h-8 px-3 rounded-md hover:bg-[var(--raised)]"
                style="color: var(--muted);" @click="router.push('/settings')">设置</button>
        <NButton type="primary" size="small" class="!h-8" @click="showCreate = true">资料收集</NButton>
      </div>
    </header>

    <main class="max-w-[1200px] mx-auto px-6 py-6">
      <!-- 标题行 -->
      <div class="flex items-end justify-between mb-5 flex-wrap gap-3">
        <div>
          <h1 class="text-2xl font-semibold tracking-tight">文章</h1>
          <p class="text-sm mt-1" style="color: var(--muted);">
            共 {{ store.articleTotal }} 篇 · 处理中 {{ counts.Process }} 篇
          </p>
        </div>
        <!-- 筛选（下划线 tabs 风格）+ 搜索 -->
        <div class="flex items-center gap-1 border-b" style="border-color: var(--border);">
          <button v-for="f in ['全部', 'New', 'Process', 'Done']" :key="f"
                  class="px-3 h-9 text-sm transition-colors border-b-2 -mb-px"
                  :style="filter === f
                    ? 'border-color: var(--accent); color: var(--text); font-weight: 600;'
                    : 'border-color: transparent; color: var(--muted);'"
                  @click="filter = f">
            {{ f }}<span class="ml-1 num" style="color: var(--faint);">{{ (counts as any)[f] }}</span>
          </button>
        </div>
        <NInput v-model:value="q" placeholder="搜索标题或链接" clearable size="small" class="!w-56" />
      </div>

      <!-- 列表：1px 分隔行，无卡片阴影 -->
      <div class="panel overflow-hidden">
        <div v-if="list.length === 0" class="py-20 text-center">
          <p class="text-[15px]" style="color: var(--muted);">还没有文章。</p>
          <p class="text-sm mt-2" style="color: var(--faint);">
            点右上角「资料收集」，把一篇 AI 要闻交给收集、创作、审稿三个 Agent。
          </p>
          <NButton type="primary" size="small" class="mt-5" @click="showCreate = true">收集第一份资料</NButton>
        </div>

        <div v-for="(a, i) in list" :key="a.id"
             class="flex items-center gap-4 px-5 h-[68px] cursor-pointer hover:bg-[var(--raised)] transition-colors"
             :style="i > 0 ? 'border-top: 1px solid var(--rule);' : ''"
             @click="router.push(`/articles/${a.id}`)">
          <div class="flex-1 min-w-0">
            <div class="font-medium text-[15px] truncate">{{ a.title || a.url }}</div>
            <div class="text-xs mt-1 flex items-center gap-2 flex-wrap" style="color: var(--faint);">
              <span>{{ a.source_site || '来源待识别' }}</span>
              <span aria-hidden="true">·</span>
              <span class="num">{{ (a.created_at || '').slice(0, 16) }}</span>
              <span v-if="a.published_at" class="num">· 发布 {{ a.published_at.slice(0, 10) }}</span>
              <span v-if="progressText(a)" style="color: var(--pill-warn-ink);">{{ progressText(a) }}</span>
              <span v-if="a.error" style="color: var(--pill-neg-ink);" class="truncate">· {{ a.error }}</span>
            </div>
          </div>
          <StatusChip :status="a.status" :ui-status="a.ui_status" />
        </div>
      </div>
      <NPagination v-if="store.articleTotal > store.articlePageSize" class="mt-5"
                   v-model:page="store.articlePage" :page-size="store.articlePageSize"
                   :item-count="store.articleTotal" />
    </main>

    <!-- 资料收集弹窗：网页链接 / 本地文件 双模式 -->
    <NModal v-model:show="showCreate" preset="card" title="资料收集" class="!max-w-lg">
      <div class="flex gap-1 p-1 rounded-lg mb-4" style="background: var(--raised);">
        <button v-for="m in [{ k: 'url', t: '网页链接' }, { k: 'file', t: '本地文件 / 文件夹' }]"
                :key="m.k" class="flex-1 h-8 text-sm rounded-md transition-colors"
                :style="createMode === m.k
                  ? 'background: var(--surface); color: var(--text); font-weight: 600; box-shadow: 0 0 0 1px var(--border);'
                  : 'color: var(--muted);'"
                @click="createMode = (m.k as any)">{{ m.t }}</button>
      </div>
      <div class="space-y-4">
        <template v-if="createMode === 'url'">
          <NInput v-model:value="newUrl" type="textarea" :autosize="{ minRows: 2 }"
                  placeholder="粘贴公众号 / 新闻 / arXiv 链接，如 https://mp.weixin.qq.com/s/..." />
          <p class="text-xs" style="color: var(--faint);">
            录入后自动开始收集：抓原文与图片 → 提炼主题 → 关联搜索 3~5 篇参考（含 arXiv 论文）→
            素材不足时用可商用图库补齐配图。
          </p>
        </template>
        <template v-else>
          <NInput v-model:value="newTitle" placeholder="主题名（可选，默认取文件夹名/首个文件名）" />
          <div class="grid grid-cols-2 gap-3">
            <NUpload v-model:file-list="fileList" multiple :default-upload="false">
              <NUploadDragger>
                <div class="py-4 text-sm" style="color: var(--muted);">点选 / 拖入文件（可多选）</div>
              </NUploadDragger>
            </NUpload>
            <NUpload v-model:file-list="fileList" directory :default-upload="false">
              <NUploadDragger>
                <div class="py-4 text-sm" style="color: var(--muted);">选择整个文件夹</div>
              </NUploadDragger>
            </NUpload>
          </div>
          <p class="text-xs" style="color: var(--faint);">
            已选 {{ fileList.length }} 个文件。自动识别类型并分流到素材目录：
            文章（md/txt/html/pdf 抽取正文）· 图片 · 视频 · 音频 · 其他。
          </p>
        </template>
        <NInput v-model:value="newNotes" placeholder="备注（可选）：写作角度、强调重点等" />
        <div class="flex justify-end gap-2">
          <NButton size="small" @click="showCreate = false">取消</NButton>
          <NButton type="primary" size="small" :loading="creating" @click="create">
            {{ createMode === 'url' ? '开始处理' : '收集入库' }}</NButton>
        </div>
      </div>
    </NModal>
  </div>
</template>
