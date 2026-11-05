<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { api } from '../api'
const props = defineProps<{ articleId: string }>()
const data = ref<any>(null), error = ref(''), busy = ref(false)
async function load() { try { data.value = await api.get(`/api/articles/${props.articleId}/access`); error.value='' } catch (e:any) { error.value=e.message } }
function grant(id:string) { return data.value.members.find((m:any)=>m.member_id===id) }
function toggle(id:string, enabled:boolean) {
  data.value.members = data.value.members.filter((m:any)=>m.member_id!==id)
  if(enabled) data.value.members.push({member_id:id,can_create:false,can_review:false})
}
async function save() {
  busy.value=true
  try { await api.put(`/api/articles/${props.articleId}/access`, {expected_revision:data.value.revision,owner_id:data.value.owner_id,archived:!!data.value.archived,members:data.value.members}); await load() }
  catch(e:any) { error.value=e.message } finally {busy.value=false}
}
onMounted(load); watch(()=>props.articleId,load)
</script>
<template>
  <section class="p-4 flex flex-col gap-3" v-if="data">
    <h2>项目访问权限 · {{ data.archived ? '已归档（成员只读）' : '可协作' }}</h2>
    <p>项目授权独立于成员等级；普通成员可创作和自审，定稿与发布包由维护负责人或管理员执行。</p>
    <template v-if="data.capabilities.manage">
      <label>负责人 <select v-model="data.owner_id" class="border p-2"><option v-for="m in data.candidates" :value="m.id" :key="m.id">{{m.name}}（{{m.login}}）</option></select></label>
      <label><input type="checkbox" v-model="data.archived" /> 归档项目</label>
      <div v-for="m in data.candidates" :key="m.id" class="flex flex-wrap gap-3 border-b py-2">
        <label><input type="checkbox" :checked="!!grant(m.id)" @change="toggle(m.id,($event.target as HTMLInputElement).checked)" /> {{ m.name }}</label>
        <template v-if="grant(m.id)"><label><input type="checkbox" v-model="grant(m.id).can_create" /> 创作</label><label><input type="checkbox" v-model="grant(m.id).can_review" /> 审核</label><span>未勾选能力时为只读</span></template>
      </div>
      <button class="border rounded p-2" :disabled="busy" @click="save">保存项目权限</button>
    </template>
    <p v-else>本项目成员：{{data.members.map((m:any)=>m.name).join('、')}}</p>
    <p v-if="error" role="alert">{{error}}</p>
  </section><p v-else class="p-4">{{error || '正在加载项目权限…'}}</p>
</template>
