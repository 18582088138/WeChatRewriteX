<script setup lang="ts">
import {onMounted,ref,watch} from 'vue'
import {api} from '../api'
const props=defineProps<{articleId:string}>()
const data=ref<any>(null), doc=ref<any>(null), access=ref<any>(null), selected=ref(''), error=ref(''), reason=ref(''), reviewer=ref(''), comment=ref(''), anchor=ref('meta'), exception=ref(''), force=ref(false), busy=ref(false)
const labels:Record<string,string>={pending:'待审核',returned:'退回修改',approved:'人工批准',withdrawn:'已撤回',superseded:'已被新提交替代'}
async function load(){try{
  data.value=await api.get(`/api/articles/${props.articleId}/human-review`)
  access.value=await api.get(`/api/articles/${props.articleId}/access`)
  try{doc.value=(await api.get(`/api/articles/${props.articleId}/draft`)).draft.doc}catch{doc.value=null}
  if(!reviewer.value)reviewer.value=data.value.reviewers[0]?.id||''
  if(!selected.value)selected.value=data.value.submissions[0]?.id||''
}catch(e:any){error.value=e.message}}
function current(){return data.value?.submissions.find((s:any)=>s.id===selected.value)}
function revision(){return{expected_version:doc.value?.version,expected_revision:doc.value?.edit_revision}}
async function run(fn:()=>Promise<any>){busy.value=true;error.value='';try{await fn();await load()}catch(e:any){error.value=e.message}finally{busy.value=false}}
async function submit(){await run(async()=>{const r=await api.post(`/api/articles/${props.articleId}/human-review`,{reviewer_id:reviewer.value,...revision()});selected.value=r.id})}
async function decide(status:string){await run(()=>api.put(`/api/articles/${props.articleId}/human-review/${current().id}`,{status,reason:reason.value,reviewer_id:reviewer.value,submission_revision:current().revision,...revision()}))}
async function addComment(){await run(()=>api.post(`/api/articles/${props.articleId}/human-review/${current().id}/comments`,{anchor:anchor.value,message:comment.value}));comment.value=''}
async function resolve(c:any,status:string){await run(()=>api.put(`/api/articles/${props.articleId}/human-review/${current().id}/comments/${c.id}`,{status,reason:reason.value,expected_revision:c.revision}))}
async function finalize(){await run(()=>api.post(`/api/articles/${props.articleId}/finalize`,{...revision(),force:force.value,exception_reason:exception.value}))}
onMounted(load);watch(()=>props.articleId,()=>{selected.value='';reviewer.value='';load()})
</script>
<template><section class="p-3 flex flex-col gap-4" v-if="data && access">
  <h2 class="text-lg">人工审核 · {{data.valid_approval?'当前内容已批准':'当前内容尚未批准或批准已过期'}}</h2>
  <p>人工审核与 AI/规则审稿分别记录。批准仅适用于所选快照；修改正文、标题、图片或引用素材后须重新提交。{{data.self_review?'允许自审，仍需显式确认。':'当前团队禁止自审。'}}</p>
  <p v-if="error" role="alert" class="text-red-700">{{error}}</p>
  <label>审核者 <select aria-label="审核者" v-model="reviewer" class="border rounded p-2"><option v-for="m in data.reviewers" :key="m.id" :value="m.id">{{m.name}}</option></select></label>
  <button v-if="access.capabilities.write" @click="submit" :disabled="busy || !doc" class="border rounded p-2">提交当前 v{{doc?.version}} / revision {{doc?.edit_revision}} 快照</button>
  <label>历史提交 <select v-model="selected" class="border rounded p-2 max-w-full"><option v-for="s in data.submissions" :key="s.id" :value="s.id">v{{s.version}} / r{{s.edit_revision}} · {{labels[s.status]||s.status}} · {{new Date(s.created_at*1000).toLocaleString()}}</option></select></label>
  <template v-if="current()">
    <p>处理说明：{{current().reason||'暂无'}} · 快照状态：{{labels[current().status]}}</p>
    <details open class="border rounded p-3"><summary>实际提交快照（只读）</summary><p>{{current().doc.meta.title_candidates?.[0]}}</p><div v-for="b in current().doc.blocks" :key="b.id" class="py-2 whitespace-pre-wrap break-words"><strong v-if="b.type==='heading'">{{b.text}}</strong><p v-else>{{b.text}}</p><img v-if="b.type==='image' && b.asset_id" :src="`/api/materials/${b.asset_id}/file`" class="max-w-full" /><p v-if="b.caption">{{b.caption}}</p></div></details>
    <label>处理/退回/不采纳说明<textarea v-model="reason" class="border rounded p-2 w-full" rows="3" /></label>
    <div v-if="current().status==='pending'" class="flex flex-wrap gap-3">
      <template v-if="current().reviewer_id===data.member_id && access.capabilities.review"><button @click="decide('approved')" :disabled="busy" class="border rounded p-2">确认批准此快照</button><button @click="decide('returned')" :disabled="busy" class="border rounded p-2">退回修改</button></template>
      <template v-if="access.capabilities.write && (current().submitter_id===data.member_id || access.capabilities.manage)"><button @click="decide('withdrawn')" :disabled="busy">撤回</button><button @click="decide('reassigned')" :disabled="busy">改派所选审核者</button></template>
    </div>
    <div v-if="current().reviewer_id===data.member_id && access.capabilities.review" class="flex flex-col gap-2"><label>意见位置 <select v-model="anchor" class="border p-2"><option value="meta">标题/元信息</option><option v-for="b in current().doc.blocks" :key="b.id" :value="b.id">{{b.type}} · {{b.text.slice(0,25)||b.caption||b.id}}</option></select></label><textarea v-model="comment" placeholder="具体审核意见" class="border p-2" /><button @click="addComment" :disabled="busy || !comment">添加意见</button></div>
    <div v-for="c in current().comments" :key="c.id" class="border-b py-2"><p>{{c.name}} · {{c.anchor}} · {{c.message}}</p><p>{{{pending:'待处理',resolved:'已解决',declined:'不采纳'}[c.status as 'pending']}} {{c.reason}}</p><div v-if="access.capabilities.write" class="flex gap-3"><button @click="resolve(c,'resolved')">标记已解决</button><button @click="resolve(c,'declined')">注明不采纳</button></div></div>
  </template>
  <div v-if="access.capabilities.release && doc" class="border rounded p-3 flex flex-col gap-3"><h3>维护人员定稿</h3><label><input v-model="force" type="checkbox" /> 显式跳过 AI/规则阻断（留痕，不代替人工批准）</label><label v-if="access.candidates.some((m:any)=>m.id===data.member_id && m.role==='admin')">管理员例外原因（需要时填写）<textarea v-model="exception" class="border p-2 w-full" /></label><button @click="finalize" :disabled="busy" class="border rounded p-2">核验当前版本并定稿</button></div>
</section><p v-else class="p-4">{{error||'正在加载人工审核…'}}</p></template>
