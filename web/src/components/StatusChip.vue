<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string; uiStatus?: string }>()

const ui = computed(() => props.uiStatus || props.status)
// taste: 状态用「浅色底 + 同色深字」的 pill，不用饱和色
const style = computed(() => {
  switch (ui.value) {
    case 'New': return 'background: var(--pill-new-bg); color: var(--pill-new-ink);'
    case 'Process': return 'background: var(--pill-warn-bg); color: var(--pill-warn-ink);'
    case 'Done': return 'background: var(--pill-pos-bg); color: var(--pill-pos-ink);'
    default: return 'background: var(--pill-neg-bg); color: var(--pill-neg-ink);'
  }
})
const dot = computed(() => {
  switch (ui.value) {
    case 'New': return 'background:#3B6699;'
    case 'Process': return 'background:#C99014;'
    case 'Done': return 'background:#247B50;'
    default: return 'background:#C4242A;'
  }
})

const STAGE_LABEL: Record<string, string> = {
  NEW: '待处理', COLLECTING: '收集资料中', COLLECTED: '资料就绪', WRITING: '洗稿中',
  DRAFTED: '草稿已生成', REVIEWING: '审稿中', REVIEWED: '审稿完成', EDITING: '人工编辑中',
  FINALIZED: '已定稿', PUBLISHING: '导出发布包中', DONE: '已完成', FAILED: '失败',
}
const label = computed(() => STAGE_LABEL[props.status] || ui.value)
</script>

<template>
  <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs"
        :style="style">
    <span class="w-1.5 h-1.5 rounded-full inline-block" :style="dot"></span>
    {{ label }}
  </span>
</template>
