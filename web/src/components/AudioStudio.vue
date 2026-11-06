<script setup lang="ts">
import {computed, onMounted, onUnmounted, ref, watch} from 'vue'
import {api} from '../api'
import {onBeforeRouteLeave, onBeforeRouteUpdate} from 'vue-router'

const props = defineProps<{articleId:string}>()
const state = ref<any>(null), doc = ref<any>(null), baseRevision = ref(0)
const error = ref(''), notice = ref(''), busy = ref(false), estimate = ref<any>(null)
const permissions = ref({write:true,review:true,release:true,manage:true}), isAdmin = ref(true)
const teamMode = ref(false), memberId = ref(''), reviewers = ref<any[]>([]), reviewerId = ref('')
const brief = ref({audience:'科技资讯读者',persona:'清晰、自然、准确',language:'zh',target_seconds:180,purpose:'单人旁白'})
const useLlm = ref(false), reason = ref(''), selectedReview = ref(''), comment = ref(''), commentAnchor = ref('')
const rewriteInstruction = ref('缩短长句，保持全部事实和数值。'), unknownRetry = ref(false)
const dictTerm = ref(''), dictReading = ref(''), history = ref<any[]>([]), cueText = ref(''), cueBatch = ref('')
const voiceForm = ref({provider:'minimax',voice_id:'',name:'已有音色',authorization:''})
const profileError = ref(''), mixMaterials = ref<any[]>([])
const base = computed(()=>`/api/articles/${props.articleId}/audio`)
const dirty = computed(()=>doc.value && JSON.stringify(doc.value)!==JSON.stringify(state.value?.product?.doc))
const selected = computed(()=>state.value?.reviews?.find((r:any)=>r.id===selectedReview.value))
const readyBatch = computed(()=>state.value?.batches?.find((b:any)=>b.status==='done' && !b.stale && !b.result.selected_only))
const labels:Record<string,string> = {queued:'排队中',running:'请求/校验/合并中',done:'已完成',unknown:'响应未知，费用待核对',failed:'失败',cancelled:'已取消',pending:'待审核',approved:'已批准',returned:'退回修改'}
let timer:ReturnType<typeof setInterval>|undefined, generation=0

async function load(replace=false) {
  const id=props.articleId, sequence=++generation
  try {
    const data=await api.get(`/api/articles/${id}/audio`)
    if(id!==props.articleId || sequence!==generation)return
    const keep=dirty.value && !replace
    state.value=data
    if(!keep){doc.value=data.product?structuredClone(data.product.doc):null;baseRevision.value=data.product?.revision||0}
    if(!selectedReview.value)selectedReview.value=data.reviews?.[0]?.id||''
  } catch(e:any){error.value=e.message}
}
async function initialize(){
  const id=props.articleId
  try {
    const status=await api.get('/api/auth/status');teamMode.value=status.team_mode
    if(status.team_mode){
      const me=await api.get('/api/auth/me');memberId.value=me.member.id;isAdmin.value=me.member.role==='admin'
      const access=await api.get(`/api/articles/${id}/access`);permissions.value=access.capabilities
      const review=await api.get(`/api/articles/${id}/human-review`);reviewers.value=review.reviewers
      reviewerId.value=review.reviewers.find((m:any)=>m.id===memberId.value)?.id||review.reviewers[0]?.id||''
    }
    const materials=await api.get(`/api/articles/${id}/materials`)
    if(id===props.articleId)mixMaterials.value=(materials.materials||[]).filter((m:any)=>m.kind==='audio' || /\.(mp3|wav|m4a|aac|ogg|flac)$/i.test(m.path||''))
    if(isAdmin.value){const settings=await api.get('/api/audio/settings');voiceForm.value.voice_id=settings.default_voice_id||''}
    await load(true)
  }catch(e:any){error.value=e.message}
}
async function act(fn:()=>Promise<any>,replace=false){
  busy.value=true;error.value='';notice.value=''
  try{await fn();await load(replace)}catch(e:any){error.value=e.message}finally{busy.value=false}
}
async function derive(){await act(()=>api.post(base.value+'/derive',{revision:baseRevision.value,brief:brief.value,use_llm:useLlm.value}),true)}
async function save(){await act(async()=>{const data=await api.put(base.value+'/speech',{revision:baseRevision.value,doc:doc.value});state.value=data;doc.value=structuredClone(data.product.doc);baseRevision.value=data.product.revision;notice.value='口播与声音设置已保存'},true)}
function addParagraph(){doc.value.paragraphs.push({id:crypto.randomUUID().replace(/-/g,''),text:'',speech_text:'',manual_speech:false,source_block_ids:[],citations:[],pause_ms:300})}
function restoreHistory(value:any){doc.value=structuredClone(value)}
function keepLocalOnLatest(){baseRevision.value=state.value.product.revision;error.value='';notice.value='已保留本地内容，请对照最新稿核对后再保存'}
function move(index:number,step:number){const p=doc.value.paragraphs.splice(index,1)[0];doc.value.paragraphs.splice(index+step,0,p)}
async function generate(ids?:string[]){
  if(dirty.value){error.value='请先保存口播和声音设置';return}
  await act(()=>api.post(base.value+'/generate',{revision:baseRevision.value,paragraph_ids:ids||null,confirm_unknown_retry:unknownRetry.value}))
}
async function getEstimate(){await act(async()=>{estimate.value=await api.get(base.value+'/estimate')})}
async function rewrite(id:string){await act(async()=>{const data=await api.post(base.value+'/rewrite',{revision:baseRevision.value,paragraph_id:id,instruction:rewriteInstruction.value});state.value=data;doc.value=structuredClone(data.product.doc);baseRevision.value=data.product.revision},true)}
async function submit(kind:string,batchId?:string){await act(async()=>{const r=await api.post(base.value+'/reviews',{kind,revision:baseRevision.value,batch_id:batchId||null,reviewer_id:reviewerId.value||null});selectedReview.value=r.id})}
async function decide(status:string){await act(()=>api.put(base.value+`/reviews/${selected.value.id}`,{status,revision:selected.value.revision,reason:reason.value}))}
async function addComment(){await act(()=>api.post(base.value+`/reviews/${selected.value.id}/comments`,{revision:selected.value.revision,paragraph_id:commentAnchor.value,message:comment.value}));comment.value=''}
async function registerVoice(){profileError.value='';try{await api.post('/api/audio/voices',{...voiceForm.value,projects:[props.articleId],enabled:true});await load();notice.value='已有音色已登记，请选择并保存'}catch(e:any){profileError.value=e.message}}
function addDictionary(){if(!dictTerm.value.trim()||!dictReading.value.trim())return;doc.value.dictionary[dictTerm.value.trim()]=dictReading.value.trim();dictTerm.value='';dictReading.value=''}
async function loadHistory(){await act(async()=>{history.value=(await api.get(base.value+'/history')).versions})}
function editCues(batch:any){cueBatch.value=batch.id;cueText.value=JSON.stringify(batch.result.timeline.map((c:any)=>({paragraph_id:c.paragraph_id,start:c.start,end:c.end,text:c.text})),null,2)}
async function saveCues(){await act(async()=>{const parsed=JSON.parse(cueText.value);await api.put(base.value+`/batches/${cueBatch.value}/subtitles`,{cues:parsed});cueText.value='';cueBatch.value=''})}
function beforeUnload(event:BeforeUnloadEvent){if(dirty.value){event.preventDefault();event.returnValue=''}}
function mayLeave(){return !dirty.value || window.confirm('口播与设置有未保存修改，确认离开并放弃这些修改？')}
onBeforeRouteLeave(mayLeave);onBeforeRouteUpdate(mayLeave)
onMounted(()=>{initialize();timer=setInterval(()=>{if(!busy.value)load()},2500);window.addEventListener('beforeunload',beforeUnload)})
onUnmounted(()=>{generation++;if(timer)clearInterval(timer);window.removeEventListener('beforeunload',beforeUnload)})
watch(()=>props.articleId,()=>{generation++;state.value=null;doc.value=null;baseRevision.value=0;selectedReview.value='';history.value=[];estimate.value=null;cueText.value='';initialize()})
</script>

<template>
  <section class="audio-studio" aria-label="音频创作工作台">
    <header class="flex flex-wrap items-center justify-between gap-3"><div><h2 class="text-xl font-semibold">音频创作</h2><p class="muted mt-1">从图文派生口播，按段试听，审阅后导出单人旁白。</p></div><span class="badge" v-if="state?.product">口播 r{{baseRevision}} · {{dirty?'有未保存修改':'已保存'}}</span></header>
    <p v-if="error" role="alert" class="alert">{{error}}</p><p v-if="notice" role="status" class="notice">{{notice}}</p>
    <div v-if="!state" class="muted">正在加载音频工作台…</div>
    <template v-else>
      <details :open="!doc" class="card" v-if="permissions.write"><summary>创作目标与图文转口播</summary><div class="grid-fields mt-4">
        <label>目标听众<input v-model="brief.audience" /></label><label>口播人设<input v-model="brief.persona" /></label>
        <label>语言<select v-model="brief.language"><option value="zh">中文</option><option value="en">英文</option></select></label>
        <label>目标时长<select v-model.number="brief.target_seconds"><option :value="120">2 分钟</option><option :value="180">3 分钟</option><option :value="240">4 分钟</option><option :value="300">5 分钟</option></select></label>
      </div><label class="check mt-3"><input type="checkbox" v-model="useLlm" />使用 AI 改为开场、事实、解释与结尾（产生模型调用）</label><p class="muted mt-2">保守派生保留原文事实，实际时长以音频测量为准。重新派生会生成新口播版本。</p><button @click="derive" :disabled="busy || !!dirty" class="primary mt-3">{{doc?'从当前图文重新派生':'从图文派生口播稿'}}</button></details>
      <template v-if="doc">
        <div v-if="state.product.source_stale" class="alert">图文来源已改变，请对照来源复核口播。<button v-if="permissions.write" :disabled="busy||!!dirty" @click="act(()=>api.post(base+'/confirm-source',{revision:baseRevision}),true)">确认口播不受影响</button></div>
        <div v-if="state.product.revision!==baseRevision" class="alert">服务端口播已更新到 r{{state.product.revision}}，本地输入仍保留。<details class="mt-2"><summary>对照服务器最新口播</summary><p v-for="p in state.product.doc.paragraphs" :key="p.id">{{p.text}}</p></details><button @click="keepLocalOnLatest" class="mt-2">对照后，以本地内容继续编辑最新版本</button></div>
        <div class="studio-columns">
          <section class="card script-area"><div class="flex flex-wrap justify-between items-center gap-2"><h3>口播稿</h3><div class="flex gap-2"><button @click="loadHistory">历史版本</button><button v-if="permissions.write" class="primary" @click="save" :disabled="busy||!dirty">保存口播与设置</button></div></div>
            <label class="mt-3">口播标题<input v-model="doc.title" :disabled="!permissions.write" /></label>
            <div class="paragraph" v-for="(p,i) in doc.paragraphs" :key="p.id">
              <div class="flex items-center justify-between gap-2"><strong>段落 {{i+1}}</strong><span class="muted">{{state.segments?.find((s:any)=>s.paragraph_id===p.id)?.stale?'待生成/需更新':'片段可复用'}}</span></div>
              <label>展示文本<textarea :aria-label="`口播段落 ${i+1}`" v-model="p.text" rows="4" :disabled="!permissions.write" /></label>
              <label class="check"><input type="checkbox" v-model="p.manual_speech" :disabled="!permissions.write" />手工指定读法</label>
              <label>发送给语音服务的发音文本<textarea :aria-label="`发音文本 ${i+1}`" v-model="p.speech_text" rows="2" :disabled="!permissions.write||!p.manual_speech" /></label>
              <div class="flex flex-wrap items-center gap-2 mt-2"><label v-if="state.features.mix" class="pause">段后停顿（毫秒）<input type="number" v-model.number="p.pause_ms" min="0" max="3000" :disabled="!permissions.write" /></label><template v-if="permissions.write"><button :disabled="i===0" @click="move(i,-1)">上移</button><button :disabled="i===doc.paragraphs.length-1" @click="move(i,1)">下移</button><button @click="doc.paragraphs.splice(i,1)">删除</button><button @click="generate([p.id])" :disabled="busy||!!dirty">合成/更新这一段</button><button @click="rewrite(p.id)" :disabled="busy||!!dirty">AI 局部改写</button></template></div>
              <details class="muted mt-2"><summary>来源定位</summary><p>图文块：{{p.source_block_ids.join('、')||'人工新增，待核对'}}</p><p>素材：{{p.citations.join('、')||'暂无引用'}}</p></details>
              <audio v-if="state.segments?.find((s:any)=>s.paragraph_id===p.id)?.url" controls preload="none" :src="state.segments.find((s:any)=>s.paragraph_id===p.id).url" :aria-label="`段落 ${i+1} 试听`" class="mt-3" />
            </div>
            <button v-if="permissions.write" @click="addParagraph">添加口播段落</button>
            <label class="mt-3" v-if="permissions.write">局部改写要求<input v-model="rewriteInstruction" /></label>
            <details v-if="history.length" class="mt-4"><summary>已保存的口播历史（{{history.length}}）</summary><div v-for="v in history" :key="v.revision" class="paragraph"><strong>r{{v.revision}}</strong><p v-for="p in v.doc.paragraphs" :key="p.id">{{p.text}}</p><button v-if="permissions.write" @click="restoreHistory(v.doc)">载入此历史为编辑副本</button></div></details>
          </section>
          <aside class="space-y-4">
            <section class="card"><h3>声音设置</h3><label class="mt-3">已有音色<select aria-label="已有音色" v-model="doc.voice.profile_id" :disabled="!permissions.write"><option value="">选择获准音色</option><option v-for="v in state.voices" :value="v.id" :key="v.id">{{v.name}} · {{v.provider==='fake'?'离线测试音':v.verified_at?'已查询确认':'待验证'}}</option></select></label><p v-if="state.voices.find((v:any)=>v.id===doc.voice.profile_id)?.provider==='fake'" class="alert mt-2">当前是离线测试音，不是真人人声。</p>
              <label class="mt-2">合成模型<select v-model="doc.voice.model" :disabled="!permissions.write"><option>speech-2.6-hd</option><option>speech-2.6-turbo</option><option>speech-02-hd</option><option>speech-02-turbo</option></select></label>
              <div class="grid-fields mt-3"><label>语速<input aria-label="语速" type="number" v-model.number="doc.voice.speed" min="0.5" max="2" step="0.1" :disabled="!permissions.write" /></label><label>音高<input type="number" v-model.number="doc.voice.pitch" min="-12" max="12" :disabled="!permissions.write" /></label><label>音量<input type="number" v-model.number="doc.voice.volume" min="0.1" max="10" step="0.1" :disabled="!permissions.write" /></label></div><p class="muted mt-3">情绪与 SSML 暂未开放。声音参数变更后需要更新片段并重新确认成品。</p>
            </section>
            <section v-if="state.features.mix" class="card"><h3>发音词典</h3><div v-for="(reading,term) in doc.dictionary" :key="term" class="flex items-center gap-2 mt-2"><span>{{term}} → {{reading}}</span><button v-if="permissions.write" @click="delete doc.dictionary[term]">移除</button></div><template v-if="permissions.write"><label class="mt-2">原词<input v-model="dictTerm" placeholder="例如 NVIDIA" /></label><label>读法<input v-model="dictReading" placeholder="例如 英伟达" /></label><button @click="addDictionary" class="mt-2">添加读法</button></template><p class="muted mt-2">保存后，仅使用该词条的自动发音文本会改变；手工读法保持不变。</p></section>
            <details v-if="state.features.mix" class="card"><summary>停顿、片头片尾与背景音乐</summary><div class="mt-3"><label v-for="kind in ['intro','outro','music']" :key="kind">{{{intro:'片头',outro:'片尾',music:'背景音乐'}[kind as 'intro']}}<select v-model="doc.mix[kind+'_id']" :disabled="!permissions.write"><option :value="null">不使用</option><option v-for="m in mixMaterials" :key="m.id" :value="m.id">{{m.title||m.path}}</option></select></label><label>来源与授权说明<textarea v-model="doc.mix.license_note" :disabled="!permissions.write" /></label><div class="grid-fields"><label>背景音量<input type="number" v-model.number="doc.mix.music_gain" min="0" max="0.25" step="0.01" :disabled="!permissions.write" /></label><label>响度目标 LUFS<input type="number" v-model.number="doc.mix.loudness_lufs" min="-24" max="-12" :disabled="!permissions.write" /></label><label>素材裁切起点（秒）<input type="number" v-model.number="doc.mix.trim_start" min="0" max="300" :disabled="!permissions.write" /></label><label>素材使用时长（秒）<input type="number" v-model.number="doc.mix.trim_seconds" min="0.5" max="120" :disabled="!permissions.write" /></label><label>音乐淡入淡出（秒）<input type="number" v-model.number="doc.mix.fade_seconds" min="0" max="5" :disabled="!permissions.write" /></label></div><p class="muted mt-2">背景自动循环并压低到旁白之下。仅修改混音会复用声音片段。</p></div></details>
            <section class="card"><h3>生成与费用</h3><button class="mt-3" @click="getEstimate" :disabled="busy||!!dirty">估算本次调用</button><p v-if="estimate" class="mt-2">新请求 {{estimate.new_requests}} 次 · {{estimate.chars}} 字符 · 缓存 {{estimate.cache_hits}} 段<br />{{estimate.estimated_cost==null?estimate.cost_status:`预计 ¥${estimate.estimated_cost.toFixed(4)}（待账单核对）`}}</p><p class="muted mt-3">已发送 {{state.billing?.sent_requests||0}} 次 / {{state.billing?.sent_chars||0}} 字符；当前预留 {{state.billing?.reserved_requests||0}} 次。累计上限 {{state.limits.max_requests}} 次 / {{state.limits.max_chars}} 字符。</p><label v-if="state.batches.some((b:any)=>b.status==='unknown')" class="check alert mt-2"><input type="checkbox" v-model="unknownRetry" />已核对响应未知请求，明确同意重试可能重复收费</label><button v-if="permissions.write" class="primary mt-3" @click="generate()" :disabled="busy||!!dirty">生成/更新完整旁白</button></section>
            <section class="card"><h3>规则与 AI 审阅</h3><p class="muted mt-2">策划估时 {{state.rules_review?.planning_seconds||0}} 秒；事实、读音和自然度需人工确认。</p><p v-for="(i,index) in state.rules_review?.issues" :key="index" class="mt-2">{{i.message}}</p><button v-if="permissions.write && state.features.reviews" class="mt-3" :disabled="busy||!!dirty" @click="act(()=>api.post(base+'/review-ai',{revision:baseRevision}))">AI 口播审阅（产生模型调用）</button><div v-if="state.ai_review" class="mt-3"><p class="muted">AI 意见不代替人工批准</p><p v-for="(i,index) in state.ai_review.issues" :key="index" class="mt-2">{{i.message}} {{i.suggestion}}</p></div></section>
          </aside>
        </div>
        <section class="card"><h3>试听与任务记录</h3><p v-if="!state.batches.length" class="muted mt-3">尚未生成音频。</p><article v-for="b in state.batches" :key="b.id" class="batch mt-4"><div class="flex flex-wrap justify-between gap-2"><strong>{{labels[b.status]||b.status}} · 口播 r{{b.revision}}</strong><span>{{b.stale?'内容已过期，保留历史试听':b.result.selected_only?'单段试听':'完整旁白'}}</span><button v-if="permissions.write && ['queued','running'].includes(b.status)" @click="act(()=>api.post(base+`/batches/${b.id}/cancel`))">取消后续处理</button></div><p v-if="b.error" class="alert mt-2">{{b.error}}</p><p class="muted mt-2">已校验 {{b.attempts.filter((a:any)=>a.state==='completed').length}} 段 · 缓存命中 {{b.result.cache_hits||0}} 段 · {{b.result.duration?.toFixed(2)||'待测量'}} 秒</p><p v-if="b.status==='done' && !b.result.within_target" class="muted">时长超出 2～5 分钟目标，请调整脚本。</p><audio v-if="b.files.find((f:any)=>f.name==='audio.mp3')" controls preload="none" :src="b.files.find((f:any)=>f.name==='audio.mp3').url" class="mt-3" :aria-label="`完整音频 ${b.id}`" /><div class="flex flex-wrap gap-3 mt-3"><a v-for="f in b.files.filter((f:any)=>!f.name.startsWith('manifest-')&&!f.name.startsWith('audio-package-'))" :key="f.id" :href="f.url" :download="f.name">{{f.name}}</a><button v-if="permissions.write && b.status==='done' && state.features.subtitles" @click="editCues(b)">预览/修正段落字幕</button><button v-if="permissions.write && !b.stale && b.status==='done' && !b.result.selected_only && state.features.reviews" @click="submit('audio',b.id)" :disabled="busy||!!dirty">提交成品试听确认</button></div><details v-if="b.result.loudness" class="muted mt-2"><summary>实测响度</summary><p>目标 {{b.result.loudness.target_lufs}} LUFS · 成品 {{b.result.loudness.measured.input_i}} LUFS · 真峰值 {{b.result.loudness.measured.input_tp}} dBTP</p></details></article></section>
        <section v-if="cueBatch" class="card"><h3>段落字幕修正</h3><p class="muted mt-2">时间来自实际音频段落，不是逐字对齐。修改将生成新候选，声音稿不变。</p><textarea aria-label="段落字幕修正" v-model="cueText" rows="12" :disabled="!permissions.write" /><button v-if="permissions.write" @click="saveCues" :disabled="busy">保存为新候选字幕</button></section>
        <section v-if="state.features.reviews" class="card"><h3>人工审核与成品批准</h3><p class="muted mt-2">先审核口播，再试听并批准完整音频。每次批准都绑定提交快照。</p><label v-if="teamMode" class="mt-3">音频审核者<select aria-label="音频审核者" v-model="reviewerId"><option v-for="m in reviewers" :key="m.id" :value="m.id">{{m.name}}</option></select></label><button v-if="permissions.write" @click="submit('script')" :disabled="busy||!!dirty" class="mt-3">提交口播审核</button><label class="mt-3">审核历史<select aria-label="音频审核历史" v-model="selectedReview"><option v-for="r in state.reviews" :key="r.id" :value="r.id">{{r.kind==='script'?'口播':'成品'}} · {{labels[r.status]||r.status}} · {{r.id.slice(0,8)}}</option></select></label><template v-if="selected"><details class="mt-3" open><summary>本次实际提交快照</summary><template v-if="selected.kind==='script'"><p v-for="p in selected.snapshot.doc.paragraphs" :key="p.id" class="whitespace-pre-wrap mt-2">{{p.text}}</p></template><template v-else><p>成品 {{selected.target_id}} · {{selected.snapshot.result.duration.toFixed(2)}} 秒</p><audio controls preload="none" :src="state.batches.find((b:any)=>b.id===selected.target_id)?.files.find((f:any)=>f.name==='audio.mp3')?.url" /></template></details><p v-if="selected.reason" class="mt-3">处理说明：{{selected.reason}}</p><template v-if="permissions.review && state.features.reviews"><label class="mt-3">审核意见/退回理由<textarea v-model="reason" rows="2" /></label><div class="flex gap-3 mt-2" v-if="selected.status==='pending' && (!teamMode||selected.reviewer_id===memberId)"><button @click="decide('approved')" :disabled="busy">{{selected.kind==='script'?'人工批准口播快照':'已试听，批准成品快照'}}</button><button @click="decide('returned')" :disabled="busy||!reason.trim()">退回修订</button></div><label class="mt-3">意见段落<select v-model="commentAnchor"><option value="">整体意见</option><option v-for="p in selected.snapshot.doc?.paragraphs||[]" :key="p.id" :value="p.id">{{p.text.slice(0,25)}}</option></select></label><label>具体意见<textarea v-model="comment" /></label><button @click="addComment" :disabled="busy||!comment.trim()">添加审核意见</button></template><p v-for="c in selected.comments" :key="c.id" class="mt-2">{{c.message}}</p></template></section>
        <section v-if="state.features.reviews" class="card"><h3>正式音频导出</h3><button v-if="permissions.release && readyBatch && state.features.reviews" class="primary mt-3" @click="act(async()=>{await api.post(base+'/export',{batch_id:readyBatch.id});notice='正式音频导出已完成'})" :disabled="busy||!!dirty">核验批准并导出完整音频包</button><p v-if="!permissions.release" class="muted mt-2">正式导出由维护负责人或管理员完成。</p><div v-if="state.export" class="flex flex-wrap gap-4 mt-3"><a :href="JSON.parse(state.export.manifest_json).package_url" download="audio-package.zip">下载已批准音频包 ZIP</a><a :href="base+'/exports/audio.mp3'" download="audio.mp3">下载正式 MP3</a><a :href="JSON.parse(state.export.manifest_json).manifest_url" download="manifest.json">下载成品清单</a></div></section>
      </template>
      <details v-if="isAdmin" class="card"><summary>管理员：登记本项目已有音色</summary><p class="muted mt-3">填写已有 voice ID 与授权说明。账号音色清单和累计额度在设置页管理。</p><div class="grid-fields mt-3"><label>已有 voice ID<input aria-label="已有 voice ID" v-model="voiceForm.voice_id" /></label><label>显示名称<input v-model="voiceForm.name" /></label></div><label class="mt-3">声音来源与授权说明<textarea aria-label="声音授权说明" v-model="voiceForm.authorization" /></label><button @click="registerVoice" :disabled="busy||!voiceForm.voice_id||!voiceForm.authorization" class="mt-3">登记已有音色到本项目</button><p class="alert" v-if="profileError">{{profileError}}</p></details>
    </template>
  </section>
</template>

<style scoped>
.audio-studio{display:flex;flex-direction:column;gap:18px;padding:12px 0 36px;color:var(--text)}
.card{border:1px solid var(--rule,#dedbd4);border-radius:12px;padding:20px;background:var(--surface,#fff)}
h3{font-weight:650;font-size:16px}.muted{font-size:12px;color:var(--muted,#777);line-height:1.6}.badge{font-size:12px;border-radius:20px;padding:7px 12px;background:var(--pill-pos-bg,#ecf3ef)}
label{display:flex;flex-direction:column;gap:5px;font-size:13px}input,textarea,select{border:1px solid var(--rule,#ddd);border-radius:6px;padding:8px;background:var(--surface,#fff);color:inherit;min-width:0;width:100%;font:inherit}textarea{resize:vertical}
button{border:1px solid var(--rule,#ddd);border-radius:6px;padding:7px 11px;font-size:12px;background:var(--surface,#fff);color:inherit}button:disabled{opacity:.45;cursor:not-allowed}button.primary{background:var(--accent,#38644a);color:white;border-color:transparent}button:hover:not(:disabled){filter:brightness(.95)}
.check{flex-direction:row;align-items:center}.check input{width:auto}.alert{padding:10px 12px;border-radius:6px;background:#fff0e9;color:#943e23;font-size:13px}.notice{padding:10px;background:#edf6ee;font-size:13px}
.studio-columns{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:20px}.grid-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.paragraph{border-top:1px solid var(--rule,#ddd);margin-top:18px;padding-top:16px;display:flex;flex-direction:column;gap:8px}.batch{border-top:1px solid var(--rule,#ddd);padding-top:16px}audio{width:100%;max-width:650px}.pause{max-width:160px}a{font-size:13px;color:var(--accent,#38644a);text-decoration:underline}summary{cursor:pointer;font-size:14px;font-weight:600}
@media(max-width:1000px){.studio-columns{grid-template-columns:1fr}.grid-fields{grid-template-columns:1fr 1fr}.card{padding:15px}}
@media(max-width:480px){.grid-fields{grid-template-columns:1fr}.audio-studio{padding:5px 0 28px}.card{padding:12px}}
</style>
