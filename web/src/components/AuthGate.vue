<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const emit = defineEmits(['ready'])
const mode = ref(false), checking = ref(true), initialized = ref(true), busy = ref(false)
const member = ref<any>(null), error = ref(''), login = ref(''), password = ref(''), name = ref(''), token = ref('')
const changing = ref(false), newPassword = ref('')
onMounted(async () => {
  try {
    const status = await api.get('/api/auth/status')
    mode.value = status.team_mode; initialized.value = status.initialized
    if (mode.value) { try { member.value = (await api.get('/api/auth/me')).member } catch { /* login */ } }
    if (!mode.value || (member.value && !member.value.must_change)) emit('ready')
  } catch (e: any) { error.value = e.message } finally { checking.value = false }
})
async function signIn() {
  busy.value = true; error.value = ''
  try {
    if (!initialized.value) { await api.post('/api/auth/bootstrap', { login: login.value, password: password.value, name: name.value, token: token.value }); initialized.value = true }
    member.value = (await api.post('/api/auth/login', { login: login.value, password: password.value })).member
    password.value = ''; token.value = ''
    if (!member.value.must_change) emit('ready')
  } catch (e: any) { error.value = e.message } finally { busy.value = false }
}
async function changePassword() {
  try { await api.post('/api/auth/password', { old_password: password.value, password: newPassword.value }); location.reload() }
  catch (e: any) { error.value = e.message }
}
async function logout() { try { await api.post('/api/auth/logout') } finally { location.reload() } }
</script>
<template>
  <main v-if="checking" class="p-8">正在连接文枢…</main>
  <main v-else-if="mode && !member" class="mx-auto p-6" style="max-width:420px">
    <h1 class="text-xl mb-4">{{ initialized ? '文枢 · 成员登录' : '文枢 · 初始化管理员' }}</h1>
    <form @submit.prevent="signIn" class="flex flex-col gap-3">
      <label>登录名<input v-model="login" autocomplete="username" required class="w-full border rounded p-2" /></label>
      <label v-if="!initialized">显示名称<input v-model="name" required class="w-full border rounded p-2" /></label>
      <label>密码<input v-model="password" type="password" autocomplete="current-password" required class="w-full border rounded p-2" /></label>
      <label v-if="!initialized">一次性初始化凭据<input v-model="token" type="password" required class="w-full border rounded p-2" /></label>
      <p v-if="error" role="alert">{{ error }}</p><button class="border rounded p-2" :disabled="busy">{{ initialized ? '登录' : '初始化并登录' }}</button>
    </form>
  </main>
  <template v-else>
    <nav v-if="mode" class="flex gap-4 flex-wrap p-3 border-b text-sm">
      <span>{{ member.name }} · {{ {admin:'管理员',maintainer:'维护负责人',member:'普通成员'}[member.role as 'admin'] }}</span>
      <a href="/articles">项目</a><a href="/work">我的工作</a><a v-if="member.role==='admin'" href="/team">成员管理</a>
      <a v-if="member.role==='admin'" href="/settings">系统设置</a><a v-if="member.role==='admin'" href="/shared">公共素材</a><button @click="changing=!changing">更改密码</button><button @click="logout">退出</button>
    </nav>
    <form v-if="mode && (member.must_change || changing)" @submit.prevent="changePassword" class="mx-auto p-6 flex flex-col gap-3" style="max-width:420px">
      <h2>{{ member.must_change ? '请先更改初始或重置密码' : '更改密码后需重新登录' }}</h2>
      <label>当前密码<input v-model="password" type="password" required class="w-full border p-2" /></label>
      <label>新密码（至少10字符）<input v-model="newPassword" type="password" minlength="10" required class="w-full border p-2" /></label>
      <p v-if="error" role="alert">{{ error }}</p><button class="border p-2">保存新密码</button>
    </form>
    <slot v-if="!mode || (member && !member.must_change && !changing)" />
  </template>
</template>
