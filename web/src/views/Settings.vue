<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NInputNumber, NSelect, NSwitch, NTag, useMessage } from 'naive-ui'
import { api, getToken, setToken } from '../api'
import { useAppStore } from '../stores/app'

const router = useRouter()
const store = useAppStore()
const message = useMessage()

const data = ref<any>(null)
const token = ref(getToken())
const devMode = ref(false)
const logLines = ref<string[]>([])
const logLoading = ref(false)

const editable = ref({
  'collect.search_window_days': 3,
  'collect.ref_count.min': 3,
  'collect.ref_count.max': 5,
  'create.target_word_count': 1500,
  'pipeline.auto': false,
  'review.block_on_blocker': true,
  'review.originality.simhash_warn': 0.35,
  'review.originality.simhash_block': 0.55,
  'collect.watermark_check': 'heuristic',
})

async function load() {
  try { data.value = await api.get('/api/settings') } catch (error: any) {
    data.value = { settings: {}, channels: [], llm_available: false, searcher: 'null', embedding_available: false }
    message.warning(error.message)
  }
  const s = data.value.settings
  for (const k of Object.keys(editable.value)) {
    const v = k.split('.').reduce((o, p) => o?.[p], s)
    if (v !== undefined) (editable.value as any)[k] = v
  }
  devMode.value = !!s?.dev?.mode
  if (devMode.value) loadLogs()
}
onMounted(load)

async function save(key: string, value: any) {
  try {
    await api.put('/api/settings', { key, value })
    message.success(`已保存 ${key}`)
  } catch (e: any) { message.error(e.message) }
}

async function toggleDevMode(v: boolean) {
  devMode.value = v
  await save('dev.mode', v)
  store.devMode = v
  message.success(v ? '开发者模式已开启：日志写入 log/、面板可见日志与开销' : '开发者模式已关闭')
  if (v) loadLogs()
}

async function loadLogs() {
  logLoading.value = true
  try {
    logLines.value = (await api.get('/api/logs/tail?lines=200')).lines
  } catch (e: any) { logLines.value = []; message.warning(e.message) }
  finally { logLoading.value = false }
}

function saveToken() {
  setToken(token.value.trim())
  message.success('访问令牌已保存到本机')
  load()
  store.startSse()
}
</script>

<template>
  <div class="min-h-screen">
    <header style="background: var(--surface); border-bottom: 1px solid var(--border);">
      <div class="max-w-3xl mx-auto px-6 h-12 flex items-center gap-3">
        <button class="text-sm h-8 px-2 rounded-md hover:bg-[var(--raised)]"
                style="color: var(--muted);" @click="router.push('/articles')">← 文章</button>
        <h1 class="font-semibold text-[15px]">设置</h1>
      </div>
    </header>

    <main v-if="data" class="max-w-3xl mx-auto px-6 py-6 space-y-4">
      <!-- 服务状态 -->
      <section class="panel p-5">
        <div class="font-semibold mb-3">服务状态</div>
        <div class="flex flex-wrap gap-2">
          <NTag :type="data.llm_available ? 'success' : 'error'" :bordered="false">
            LLM {{ data.llm_available ? '已配置' : '未配置（降级模式）' }}</NTag>
          <NTag :type="data.searcher !== 'null' ? 'success' : 'warning'" :bordered="false">
            搜索: {{ data.searcher === 'null' ? '未配置（仅原文）' : data.searcher }}</NTag>
          <NTag :type="data.embedding_available ? 'success' : 'default'" :bordered="false">
            向量检索 {{ data.embedding_available ? '可用' : 'FTS 降级' }}</NTag>
        </div>
        <div class="mt-3 text-xs text-ink-400">
          渠道：
          <span v-for="c in data.channels" :key="c.name" class="mr-3">
            {{ c.name }} <span :class="c.configured ? 'text-emerald-600' : 'text-slate-300'">●</span>
          </span>
        </div>
        <div class="text-xs text-ink-400 mt-2">
          密钥配置在项目根目录 <code class="bg-slate-100 px-1 rounded">.env</code>；
          渠道与模型档位在 <code class="bg-slate-100 px-1 rounded">config/settings.yaml</code>。
        </div>
      </section>

      <!-- 收集 -->
      <section class="panel p-5 space-y-4">
        <div class="font-semibold">收集</div>
        <div class="flex items-center gap-3 text-sm">
          <span class="w-44 text-ink-500">关联搜索窗口（天）</span>
          <NInputNumber v-model:value="editable['collect.search_window_days']" :min="0" :max="30"
                        size="small" class="!w-28" />
          <NButton size="tiny" @click="save('collect.search_window_days', editable['collect.search_window_days'])">保存</NButton>
        </div>
        <div class="flex items-center gap-3 text-sm">
          <span class="w-44 text-ink-500">参考篇数 下限/上限</span>
          <NInputNumber v-model:value="editable['collect.ref_count.min']" :min="1" :max="10" size="small" class="!w-20" />
          <NInputNumber v-model:value="editable['collect.ref_count.max']" :min="1" :max="10" size="small" class="!w-20" />
          <NButton size="tiny" @click="save('collect.ref_count.min', editable['collect.ref_count.min']); save('collect.ref_count.max', editable['collect.ref_count.max'])">保存</NButton>
        </div>
        <div class="flex items-center gap-3 text-sm">
          <span class="w-44 text-ink-500">水印检测</span>
          <NSelect v-model:value="editable['collect.watermark_check']" size="small" class="!w-40"
                   :options="[{ label: '启发式（快）', value: 'heuristic' }, { label: '视觉模型（准）', value: 'vision' }, { label: '关闭', value: 'off' }]" />
          <NButton size="tiny" @click="save('collect.watermark_check', editable['collect.watermark_check'])">保存</NButton>
        </div>
      </section>

      <!-- 创作与审稿 -->
      <section class="panel p-5 space-y-4">
        <div class="font-semibold">创作与审稿</div>
        <div class="flex items-center gap-3 text-sm">
          <span class="w-44 text-ink-500">目标词数</span>
          <NInputNumber v-model:value="editable['create.target_word_count']" :min="300" :max="8000"
                        :step="100" size="small" class="!w-28" />
          <NButton size="tiny" @click="save('create.target_word_count', editable['create.target_word_count'])">保存</NButton>
        </div>
        <div class="flex items-center gap-3 text-sm">
          <span class="w-44 text-ink-500">自动连跑（收集→创作→审稿）</span>
          <NSwitch :value="editable['pipeline.auto']"
                   @update:value="(v: boolean) => { editable['pipeline.auto'] = v; save('pipeline.auto', v) }" />
        </div>
        <div class="flex items-center gap-3 text-sm">
          <span class="w-44 text-ink-500">blocker 禁止定稿</span>
          <NSwitch :value="editable['review.block_on_blocker']"
                   @update:value="(v: boolean) => { editable['review.block_on_blocker'] = v; save('review.block_on_blocker', v) }" />
        </div>
        <div class="flex items-center gap-3 text-sm">
          <span class="w-44 text-ink-500">查重阈值 警告/阻断</span>
          <NInputNumber v-model:value="editable['review.originality.simhash_warn']" :min="0.1" :max="1" :step="0.05" size="small" class="!w-24" />
          <NInputNumber v-model:value="editable['review.originality.simhash_block']" :min="0.1" :max="1" :step="0.05" size="small" class="!w-24" />
          <NButton size="tiny" @click="save('review.originality.simhash_warn', editable['review.originality.simhash_warn']); save('review.originality.simhash_block', editable['review.originality.simhash_block'])">保存</NButton>
        </div>
      </section>

      <!-- 访问令牌 -->
      <section class="panel p-5 space-y-3">
        <div class="font-semibold">访问令牌（局域网/手机访问时）</div>
        <div class="text-xs text-ink-400">
          在 .env 设置 APP_ACCESS_TOKEN 后，前端在此填入同一令牌；本机 127.0.0.1 可不设。
        </div>
        <div class="flex gap-2">
          <input v-model="token" type="password" placeholder="访问令牌"
                 class="flex-1 h-8 px-3 rounded-lg border border-slate-200 text-sm outline-none focus:border-accent" />
          <NButton size="small" @click="saveToken">保存</NButton>
        </div>
      </section>

      <!-- 风格包 -->
      <section class="panel p-5">
        <div class="font-semibold mb-2">语言风格包</div>
        <div class="text-sm text-ink-500">
          当前：<NTag size="small" :bordered="false">tech-evangelist · 技术传火人</NTag>
        </div>
        <div class="text-xs text-ink-400 mt-2">
          风格规则与范文位于 <code class="bg-slate-100 px-1 rounded">config/styles/tech-evangelist/</code>，
          可直接编辑 system.md / rules.md / banlist.txt 微调；调优方法见
          <code class="bg-slate-100 px-1 rounded">docs/design/06-style-guide.md</code>。
        </div>
      </section>
      <!-- 开发者模式（默认关闭） -->
      <section class="panel p-5 space-y-3">
        <div class="flex items-center justify-between">
          <div class="font-semibold">开发者模式</div>
          <NSwitch :value="devMode" @update:value="toggleDevMode" />
        </div>
        <div class="text-xs" style="color: var(--faint);">
          开启后：运行日志写入 <code class="bg-slate-100 px-1 rounded">log/app.log</code>（不进 git）；
          各分页下方显示累计 API 开销（发布页汇总全流程）；此处可查看实时日志。
        </div>
        <template v-if="devMode">
          <div class="flex items-center justify-between">
            <span class="text-sm font-medium">运行日志（最近 200 行）</span>
            <NButton size="tiny" :loading="logLoading" @click="loadLogs">刷新</NButton>
          </div>
          <pre class="text-xs p-3 rounded-md overflow-auto max-h-64"
               style="background: #141414; color: #B9B4A9; font-family: Consolas, monospace;">{{ logLines.join('\n') || '（暂无日志，运行一个任务后刷新）' }}</pre>
        </template>
      </section>
    </main>
  </div>
</template>
