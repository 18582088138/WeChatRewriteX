<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const members = ref<any[]>([]), error = ref(''), busy = ref(false)
const login = ref(''), name = ref(''), password = ref(''), role = ref('member')
const roles = [{value:'admin',label:'管理员'},{value:'maintainer',label:'维护负责人'},{value:'member',label:'普通成员'}]
async function load() { try { members.value = (await api.get('/api/auth/members')).members } catch(e:any) { error.value=e.message } }
onMounted(load)
async function create() {
  busy.value=true; error.value=''
  try { await api.post('/api/auth/members',{login:login.value,name:name.value,password:password.value,role:role.value}); password.value=''; login.value=''; name.value=''; await load() }
  catch(e:any) { error.value=e.message } finally { busy.value=false }
}
async function save(member:any) {
  error.value=''
  try { await api.put('/api/auth/members/'+member.id,{role:member.role,enabled:!!member.enabled,password:member.reset || undefined}); member.reset=''; await load() }
  catch(e:any) { error.value=e.message }
}
</script>
<template>
  <main class="mx-auto p-5" style="max-width:980px">
    <h1 class="text-xl mb-3">团队成员</h1><p class="mb-4 text-sm">等级决定能力，项目授权决定可见范围。重置或新增账号首次登录需改密。</p>
    <p v-if="error" role="alert" class="mb-3">{{ error }}</p>
    <form @submit.prevent="create" class="flex flex-wrap gap-3 mb-6">
      <input v-model="login" aria-label="新成员登录名" placeholder="登录名" required class="border rounded p-2" />
      <input v-model="name" aria-label="新成员名称" placeholder="显示名称" required class="border rounded p-2" />
      <input v-model="password" aria-label="初始密码" placeholder="初始密码 ≥10字符" type="password" minlength="10" required class="border rounded p-2" />
      <select v-model="role" aria-label="新成员等级" class="border p-2"><option v-for="r in roles" :value="r.value">{{r.label}}</option></select>
      <button :disabled="busy" class="border rounded p-2">添加成员</button>
    </form>
    <div v-for="m in members" :key="m.id" class="flex flex-wrap items-center gap-3 border-t py-4">
      <span style="min-width:140px">{{m.name}} · {{m.login}}</span>
      <select v-model="m.role" :aria-label="m.login+'等级'" class="border p-2"><option v-for="r in roles" :value="r.value">{{r.label}}</option></select>
      <label><input v-model="m.enabled" type="checkbox" :true-value="1" :false-value="0" /> 启用</label>
      <input v-model="m.reset" type="password" :aria-label="m.login+'重置密码'" placeholder="新重置密码（可不填）" class="border p-2" />
      <button @click="save(m)" class="border rounded p-2">保存</button>
    </div>
  </main>
</template>
