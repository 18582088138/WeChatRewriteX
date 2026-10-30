<script setup lang="ts">
import {onMounted,onUnmounted,ref,watch} from 'vue'
import {api} from '../api'
const props=defineProps<{articleId:string}>()
const clientId=globalThis.crypto?.randomUUID?.() || `browser-${Date.now()}-${Math.random()}`, lease=ref<any>(null), active=ref(false), audit=ref<any[]>([]), error=ref('')
async function load(){try{lease.value=(await api.get(`/api/articles/${props.articleId}/lease`)).lease; audit.value=(await api.get(`/api/articles/${props.articleId}/audit`)).events}catch(e:any){error.value=e.message}}
async function occupy(){try{const r=await api.post(`/api/articles/${props.articleId}/lease`,{client_id:clientId});lease.value=r.lease;active.value=r.acquired}catch(e:any){active.value=false;error.value=e.message}}
async function release(aid=props.articleId){active.value=false;try{await api.del(`/api/articles/${aid}/lease/${clientId}`)}catch{}await load()}
let timer:ReturnType<typeof setInterval>
onMounted(()=>{load();timer=setInterval(()=>{if(active.value)occupy();else load()},20000)})
onUnmounted(()=>{clearInterval(timer);if(active.value)void release()})
watch(()=>props.articleId,(_next,old)=>{if(active.value)void release(old);load()})
</script>
<template><section class="p-3 border rounded flex flex-col gap-3"><p>编辑占用提示：{{lease?`${lease.name} 正在编辑（${new Date(lease.expires*1000).toLocaleTimeString()}到期）`:'当前无人占用'}}</p><p>占用是提示，保存仍检查版本；关闭页面或断网后60秒自动释放。</p><button v-if="active" @click="release()">结束编辑提示</button><button v-else @click="occupy()">提示我正在编辑</button><p role="alert" v-if="error">{{error}}</p><details><summary>协作操作记录</summary><div v-for="e in audit" :key="e.id" class="border-b py-2"><p>{{new Date(e.created_at*1000).toLocaleString()}} · {{e.name||'系统'}} · {{e.action}}</p><p class="text-xs break-words">{{e.detail_json}}</p></div></details></section></template>
