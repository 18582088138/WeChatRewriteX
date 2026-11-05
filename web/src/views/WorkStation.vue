<script setup lang="ts">
import {onMounted,onUnmounted,ref} from 'vue'
import {api} from '../api'
const data=ref<any>(null),error=ref('')
async function load(){try{data.value=await api.get('/api/team/work');error.value=''}catch(e:any){error.value=e.message}}
let timer:ReturnType<typeof setInterval>
onMounted(()=>{load();timer=setInterval(load,15000)});onUnmounted(()=>clearInterval(timer))
</script>
<template><main class="p-5 flex flex-col gap-5"><h1 class="text-xl">我的工作</h1><button @click="load">刷新工作列表</button><p role="alert" v-if="error">{{error}}</p><template v-if="data"><section><h2>待我审核（{{data.review.length}}）</h2><p v-if="!data.review.length">暂无待审核</p><p v-for="s in data.review" :key="s.id"><a :href="`/articles/${s.article_id}`">{{s.title}} · v{{s.version}} / r{{s.edit_revision}}</a></p></section><section><h2>被退回项目</h2><p v-if="!data.returned.length">暂无退回</p><p v-for="s in data.returned" :key="s.id"><a :href="`/articles/${s.article_id}`">{{s.title}}</a> · {{s.reason}}</p></section><section><h2>授权项目失败任务</h2><p v-if="!data.failed.length">暂无失败</p><div v-for="j in data.failed" :key="j.id" class="border-b p-2"><a :href="`/articles/${j.article_id}`">{{j.type}} · {{j.initiator}}</a><p>状态 {{j.status}} · 耗时 {{j.duration_seconds ?? '尚未开始'}} 秒</p><p>{{j.error}}</p></div></section></template></main></template>
