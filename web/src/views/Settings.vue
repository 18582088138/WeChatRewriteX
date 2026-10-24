<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NInputNumber, NSelect, NSwitch, NTag, useMessage } from 'naive-ui'
import { api, getToken, setToken } from '../api'

const router = useRouter()
const message = useMessage()

const data = ref<any>(null)
const token = ref(getToken())

const editable = ref({
  'collect.search_window_days': 3,
  'collect.ref_count.min': 3,
  'collect.ref_count.max': 5,
  'rewrite.target_word_count': 1500,
  'pipeline.auto': false,
  'review.block_on_blocker': true,
  'review.originality.simhash_warn': 0.35,
  'review.originality.simhash_block': 0.55,
  'collect.watermark_check': 'heuristic',
})

async function load() {
  data.value = await api.get('/api/settings')
  const s = data.value.settings
  for (const k of Object.keys(editable.value)) {
    const v = k.split('.').reduce((o, p) => o?.[p], s)
    if (v !== undefined) (editable.value as any)[k] = v
  }
}
onMounted(load)

async function save(key: string, value: any) {
  try {
    await api.put('/api/settings', { key, value })
    message.success(`已保存 ${key}`)
  } catch (e: any) { message.error(e.message) }
}

function saveToken() {
  setToken(token.value.trim())
  message.success('访问令牌已保存到本机')
}
</script>

<template>
  <div class="min-h-screen">
    <header class="sticky top-0 z-10 bg-paper/80 backdrop-blur border-b border-slate-200">
      <div class="max-w-3xl mx-auto px-4 h-14 flex items-center gap-3">
        <button class="text-ink-400 hover:text-ink-900 text-sm" @click="router.push('/articles')">← 返回</button>
        <div class="font-semibold">设置</div>
      </div>
    </header>

    <main v-if="data" class="max-w-3xl mx-auto px-4 py-6 space-y-4">
      <!-- 服务状态 -->
      <section class="bg-white rounded-2xl shadow-card p-5">
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
      <section class="bg-white rounded-2xl shadow-card p-5 space-y-4">
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

      <!-- 洗稿与审稿 -->
      <section class="bg-white rounded-2xl shadow-card p-5 space-y-4">
        <div class="font-semibold">洗稿与审稿</div>
        <div class="flex items-center gap-3 text-sm">
          <span class="w-44 text-ink-500">目标词数</span>
          <NInputNumber v-model:value="editable['rewrite.target_word_count']" :min="300" :max="8000"
                        :step="100" size="small" class="!w-28" />
          <NButton size="tiny" @click="save('rewrite.target_word_count', editable['rewrite.target_word_count'])">保存</NButton>
        </div>
        <div class="flex items-center gap-3 text-sm">
          <span class="w-44 text-ink-500">自动连跑（收集→洗稿→审稿）</span>
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
      <section class="bg-white rounded-2xl shadow-card p-5 space-y-3">
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
      <section class="bg-white rounded-2xl shadow-card p-5">
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
    </main>
  </div>
</template>
