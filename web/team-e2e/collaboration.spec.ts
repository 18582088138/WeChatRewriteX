import {test,expect,type Browser,type BrowserContext} from '@playwright/test'

async function signed(browser:Browser,login:string,password:string,mobile=false){
  const context=await browser.newContext({baseURL:'http://127.0.0.1:8013',viewport:mobile?{width:390,height:844}:{width:1440,height:1000}})
  const page=await context.newPage();await page.goto('/articles')
  await page.getByLabel('登录名',{exact:true}).fill(login)
  await page.getByLabel('密码',{exact:true}).fill(password)
  await page.getByRole('button',{name:'登录',exact:true}).click()
  await expect(page.getByRole('button',{name:'退出',exact:true})).toBeVisible()
  const csrf=(await (await context.request.get('/api/auth/me')).json()).csrf
  return {context,page,csrf}
}
async function write(context:BrowserContext,csrf:string,aid:string,method:string,path:string,data:any){
  const state=await context.request.get(`/api/articles/${aid}`)
  return context.request.fetch(path,{method,data,headers:{'X-Wenshu-CSRF':csrf,'X-Wenshu-Project-Revision':state.headers()['x-wenshu-project-revision']!}})
}

test('team browsers return, revise, approve, finalize and export an explicit snapshot',async({browser})=>{
  const b=await signed(browser,'writer','writer-password'), c=await signed(browser,'maintainer','maintainer-password',true), d=await signed(browser,'outsider','outsider-password')
  const projects=(await (await b.context.request.get('/api/articles')).json()).articles
  const p=projects.find((p:any)=>p.title==='开源模型'), aid=p.id
  expect((await d.context.request.get(`/api/articles/${aid}`)).status()).toBe(404)
  expect((await (await b.context.request.get('/api/materials/common')).json()).materials).toEqual([])
  await b.page.goto(`/articles/${aid}`);await b.page.getByText('人工审核',{exact:true}).click()
  await b.page.getByLabel('审核者',{exact:true}).selectOption({label:'维护负责人'})
  await b.page.getByRole('button',{name:/提交当前/}).click()
  await expect(b.page.getByText('实际提交快照（只读）',{exact:true})).toBeVisible()
  await c.page.goto('/work');await expect(c.page.getByRole('link',{name:/开源模型/})).toBeVisible()
  await c.page.getByRole('link',{name:/开源模型/}).click();await c.page.getByText('人工审核',{exact:true}).click()
  await c.page.getByLabel('处理/退回/不采纳说明').fill('请补充正文说明')
  await c.page.getByRole('button',{name:'退回修改',exact:true}).click()
  await expect(c.page.getByText('处理说明：请补充正文说明',{exact:false})).toBeVisible()
  const head=(await (await b.context.request.get(`/api/articles/${aid}/draft`)).json()).draft
  expect((await write(b.context,b.csrf,aid,'PUT',`/api/drafts/${head.id}/edit`,{expected_revision:head.doc.edit_revision,ops:[{op:'update',block_id:'paragraph',text:'根据人工意见修订后的完整正文。'}]})).status()).toBe(200)
  await b.page.reload();await b.page.getByText('人工审核',{exact:true}).click()
  await b.page.getByLabel('审核者',{exact:true}).selectOption({label:'维护负责人'});await b.page.getByRole('button',{name:/提交当前/}).click()
  await c.page.reload();await c.page.getByText('人工审核',{exact:true}).click()
  await c.page.getByRole('button',{name:'确认批准此快照',exact:true}).click()
  await expect(c.page.getByText('人工审核 · 当前内容已批准',{exact:true})).toBeVisible()
  await c.page.getByLabel('显式跳过 AI/规则阻断（留痕，不代替人工批准）').check()
  const finalized=c.page.waitForResponse(r=>r.url().endsWith(`/articles/${aid}/finalize`) && r.request().method()==='POST')
  await c.page.getByRole('button',{name:'核验当前版本并定稿',exact:true}).click();expect((await finalized).status()).toBe(200)
  const exp=await write(c.context,c.csrf,aid,'POST',`/api/articles/${aid}/publish`,{platforms:['wechat_mp','weibo','x','xhs']});expect(exp.status()).toBe(200)
  const exportJob=(await exp.json()).job_id
  await expect.poll(async()=>{const jobs=(await (await c.context.request.get(`/api/jobs?article_id=${aid}`)).json()).jobs;return jobs.find((j:any)=>j.id===exportJob)?.status},{timeout:25000}).toBe('done')
  const files=(await (await c.context.request.get(`/api/articles/${aid}/exports`)).json()).files
  expect(files.some((f:string)=>f.endsWith('manifest.json'))).toBe(true)
  expect((await b.context.request.get('/files/'+files.find((f:string)=>f.endsWith('manifest.json')))).status()).toBe(200)
  expect((await d.context.request.get('/files/'+files[0])).status()).toBe(404)
  await b.context.close();await c.context.close();await d.context.close()
})

test('two browser sessions keep a conflicting local edit and revoke old file links',async({browser})=>{
  const b=await signed(browser,'writer','writer-password'),c=await signed(browser,'maintainer','maintainer-password')
  const projects=(await (await b.context.request.get('/api/articles')).json()).articles,aid=projects.find((p:any)=>p.title==='城市交通').id
  await b.page.goto(`/articles/${aid}`)
  await b.page.locator('.block-item p').first().dblclick()
  const editor=b.page.locator('.block-item textarea').first();await editor.fill('此处是必须保留的本地修改')
  const head=(await (await c.context.request.get(`/api/articles/${aid}/draft`)).json()).draft
  expect((await write(c.context,c.csrf,aid,'PUT',`/api/drafts/${head.id}/edit`,{expected_revision:head.doc.edit_revision,ops:[{op:'update',block_id:'paragraph',text:'另一个成员已经提交'}]})).status()).toBe(200)
  const conflict=b.page.waitForResponse(r=>r.url().endsWith('/edit') && r.status()===409)
  await editor.blur();await conflict;await expect(editor).toHaveValue('此处是必须保留的本地修改')
  const material=(await (await c.context.request.get(`/api/articles/${aid}/materials`)).json()).materials[0]
  const access=(await (await b.context.request.get(`/api/articles/${aid}/access`)).json())
  expect((await b.context.request.put(`/api/articles/${aid}/access`,{headers:{'X-Wenshu-CSRF':b.csrf},data:{expected_revision:access.revision,owner_id:access.owner_id,members:[]}})).status()).toBe(200)
  expect((await c.context.request.get(`/api/materials/${material.id}/file`)).status()).toBe(404)
  expect((await c.context.request.get(`/api/articles/${aid}/versions`)).status()).toBe(404)
  await c.page.reload();await expect(c.page.getByText('另一个成员已经提交',{exact:true})).toHaveCount(0)
  await b.context.close();await c.context.close()
})

test('active SSE session stops after member disable and never receives later events',async({browser})=>{
  const a=await signed(browser,'admin','admin-password'),b=await signed(browser,'writer','writer-password'),c=await signed(browser,'maintainer','maintainer-password')
  const projects=(await (await b.context.request.get('/api/articles')).json()).articles,aid=projects.find((p:any)=>p.title==='教育工具').id
  await c.page.evaluate(()=>new Promise<void>((resolve,reject)=>{
    const state={events:[] as any[],closed:false};(window as any).__teamEvents=state
    const stream=new EventSource('/api/sse');(window as any).__teamStream=stream
    stream.onopen=()=>resolve();stream.onmessage=e=>state.events.push(JSON.parse(e.data));stream.onerror=()=>{if(stream.readyState===EventSource.CLOSED)state.closed=true}
    setTimeout(()=>reject(new Error('SSE did not open')),5000)
  }))
  const head=await b.context.request.get(`/api/articles/${aid}`)
  const upload=await b.context.request.post(`/api/articles/${aid}/materials/upload`,{headers:{'X-Wenshu-CSRF':b.csrf,'X-Wenshu-Project-Revision':head.headers()['x-wenshu-project-revision']!},multipart:{file:{name:'sse-before.txt',mimeType:'text/plain',buffer:Buffer.from('SSE before disable')}}})
  expect(upload.status()).toBe(200)
  const mid=(await upload.json()).material_id
  await expect.poll(()=>c.page.evaluate((id:string)=>(window as any).__teamEvents.events.some((e:any)=>e.material_id===id),mid)).toBe(true)
  const members=(await (await a.context.request.get('/api/auth/members')).json()).members,reviewer=members.find((m:any)=>m.login==='maintainer')
  expect((await a.context.request.put(`/api/auth/members/${reviewer.id}`,{headers:{'X-Wenshu-CSRF':a.csrf},data:{role:'maintainer',enabled:false}})).status()).toBe(200)
  await expect.poll(()=>c.page.evaluate(()=>(window as any).__teamEvents.closed),{timeout:10000}).toBe(true)
  expect((await c.context.request.get(`/api/articles/${aid}`)).status()).toBe(401)
  const before=await c.page.evaluate(()=>(window as any).__teamEvents.events.length)
  const next=await write(b.context,b.csrf,aid,'PUT',`/api/articles/${aid}/selection`,{material_ids:[]});expect(next.status()).toBe(200)
  expect(await c.page.evaluate(()=>(window as any).__teamEvents.events.length)).toBe(before)
  await a.context.close();await b.context.close();await c.context.close()
})
