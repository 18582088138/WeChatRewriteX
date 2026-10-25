<script setup lang="ts">
import { onMounted } from 'vue'
import { NConfigProvider, NMessageProvider, NDialogProvider, zhCN, dateZhCN } from 'naive-ui'
import { useAppStore } from './stores/app'

const store = useAppStore()
onMounted(() => {
  store.refreshArticles()
  store.startSse()
  store.loadDevMode()
})

// taste 规范：主按钮近黑，accent 朱红只给品牌/关键数据，圆角 6-8px
const themeOverrides = {
  common: {
    primaryColor: '#1D1F20',
    primaryColorHover: '#3A3D40',
    primaryColorPressed: '#141414',
    borderRadius: '6px',
    fontSize: '14px',
  },
  Tabs: {
    tabTextColorLine: '#5F6368',
    tabTextColorActiveLine: '#141414',
    barColor: '#C63B24',
  },
}
</script>

<template>
  <NConfigProvider :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="themeOverrides">
    <NMessageProvider>
      <NDialogProvider>
        <RouterView />
      </NDialogProvider>
    </NMessageProvider>
  </NConfigProvider>
</template>
