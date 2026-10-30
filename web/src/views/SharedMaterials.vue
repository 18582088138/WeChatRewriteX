<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {api} from '../api'
const materials=ref<any[]>([]), error=ref('')
async function load(){materials.value=(await api.get('/api/materials/common')).materials}
async function share(m:any){try{await api.put(`/api/materials/${m.id}/sharing`,{shared:!m.shared});await load()}catch(e:any){error.value=e.message}}
onMounted(load)
</script>
<template><main class="p-6 flex flex-col gap-3"><h1>公共素材共享确认</h1><p>旧公共库保持管理员私有。确认共享后团队成员可读取；复制到项目的副本保留，不随公共库撤销共享删除。</p><p role="alert" v-if="error">{{error}}</p><div v-for="m in materials" :key="m.id" class="flex gap-3 flex-wrap border-b p-2"><span>{{m.title}}</span><button @click="share(m)">{{m.shared?'撤销团队共享':'确认团队共享'}}</button></div></main></template>
