<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string; uiStatus?: string }>()

const ui = computed(() => props.uiStatus || props.status)
const style = computed(() => {
  switch (ui.value) {
    case 'New': return 'bg-sky-100 text-sky-700'
    case 'Process': return 'bg-amber-100 text-amber-700'
    case 'Done': return 'bg-emerald-100 text-emerald-700'
    default: return 'bg-rose-100 text-rose-700'
  }
})
const dot = computed(() => {
  switch (ui.value) {
    case 'New': return 'bg-sky-500'
    case 'Process': return 'bg-amber-500 animate-pulse'
    case 'Done': return 'bg-emerald-500'
    default: return 'bg-rose-500'
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
  <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
        :class="style">
    <span class="w-1.5 h-1.5 rounded-full" :class="dot"></span>
    {{ label }}
  </span>
</template>
