import {test,expect} from '@playwright/test'

test('audio edit, cached synthesis, approval, export and mobile playback',async({page,request})=>{
  const article=(await (await request.get('/api/articles')).json()).articles[0]
  const aid=article.id,base=`/api/articles/${aid}/audio`
  async function generateFull(){
    const pending=page.waitForResponse(r=>r.url().endsWith(base+'/generate') && r.request().method()==='POST')
    await page.getByRole('button',{name:'生成/更新完整旁白',exact:true}).click()
    const response=await pending;expect(response.status()).toBe(200)
    const batch=await response.json()
    await expect.poll(async()=>(await (await request.get(base+'/batches/'+batch.id)).json()).status,{timeout:40000}).toBe('done')
    return batch.id
  }
  const original=(await (await request.get(`/api/articles/${aid}/draft`)).json()).draft.doc
  await page.goto(`/articles/${aid}`)
  await page.getByText('音频创作',{exact:true}).click()
  await page.getByRole('button',{name:'从图文派生口播稿',exact:true}).click()
  await expect(page.getByLabel('口播段落 1',{exact:true})).toBeVisible()
  const data=await (await request.get(base)).json()
  await page.getByLabel('已有音色',{exact:true}).selectOption(data.voices[0].id)
  await page.getByRole('button',{name:'保存口播与设置',exact:true}).click()
  await page.getByRole('button',{name:'估算本次调用',exact:true}).click()
  await expect(page.getByText('新请求 2 次', {exact:false})).toBeVisible()
  await generateFull()
  await generateFull()
  let batches=(await (await request.get(base)).json()).batches
  expect(batches).toHaveLength(1)
  expect(batches[0].attempts).toHaveLength(2)
  await page.getByLabel('口播段落 1',{exact:true}).fill('2026年11月5日，模型运行速度提高12.5%。这是修订后的口播。')
  await page.waitForTimeout(3100) // background polling must preserve edited input
  await expect(page.getByLabel('口播段落 1',{exact:true})).toHaveValue(/这是修订后的口播/)
  await page.getByRole('button',{name:'保存口播与设置',exact:true}).click()
  await generateFull()
  batches=(await (await request.get(base)).json()).batches
  expect(batches[0].attempts).toHaveLength(1)
  expect(batches[0].result.cache_hits).toBe(1)
  const articleAfter=(await (await request.get(`/api/articles/${aid}/draft`)).json()).draft.doc
  expect(articleAfter).toEqual(original)
  await page.getByRole('button',{name:'提交口播审核',exact:true}).click()
  await page.getByRole('button',{name:'人工批准口播快照',exact:true}).click()
  await page.getByRole('button',{name:'提交成品试听确认',exact:true}).first().click()
  await page.getByRole('button',{name:'已试听，批准成品快照',exact:true}).click()
  await page.getByRole('button',{name:'核验批准并导出完整音频包',exact:true}).click()
  await expect(page.getByRole('link',{name:'下载已批准音频包 ZIP',exact:true})).toBeVisible()
  const url=await page.getByRole('link',{name:'下载已批准音频包 ZIP',exact:true}).getAttribute('href')
  expect((await request.get(url!)).status()).toBe(200)
  // Actual Chromium decodes and plays the generated MP3.
  const audio=page.locator('.batch audio').first()
  await audio.evaluate(async(node:HTMLAudioElement)=>{node.load();await node.play()})
  await expect.poll(()=>audio.evaluate((node:HTMLAudioElement)=>node.currentTime),{timeout:10000}).toBeGreaterThan(0)
  await audio.evaluate((node:HTMLAudioElement)=>node.pause())
  await page.setViewportSize({width:390,height:844})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy()
  await page.screenshot({path:'audio-test-results/mobile-studio.png',fullPage:true})
  await page.setViewportSize({width:1440,height:1100})
  await page.screenshot({path:'audio-test-results/desktop-studio.png',fullPage:true})
})
