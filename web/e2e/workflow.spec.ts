import { test, expect, type APIRequestContext } from '@playwright/test'

async function prepared(request: APIRequestContext) {
  const article = await (await request.post('/api/articles', { data: { title: '浏览器验收', auto_collect: false } })).json()
  const aid = article.article.id
  await request.post(`/api/articles/${aid}/materials/upload-batch`, { multipart: {
    files: { name: 'source.md', mimeType: 'text/markdown', buffer: Buffer.from('原始段落：开源模型发布了新的功能，本文讨论实际影响。') },
  } })
  await request.post(`/api/articles/${aid}/advance`, { data: { stage: 'create' } })
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}`)).json()).status).toBe('DRAFTED')
  return aid
}

test('editing survives event refresh and produces downloadable packages', async ({ page, request }) => {
  const aid = await prepared(request)
  await page.goto(`/articles/${aid}`)
  const paragraph = page.locator('.block-item p').first()
  await expect(paragraph).toBeVisible()
  await paragraph.dblclick()
  const editor = page.locator('.block-item textarea').first()
  await editor.fill('浏览器人工修改：这一段是尚未提交的内容。')
  const refresh = page.waitForResponse(response => response.url().includes(`${aid}/materials?scope=article`))
  await request.post(`/api/articles/${aid}/materials/upload`, { multipart: {
    file: { name: 'event.txt', mimeType: 'text/plain', buffer: Buffer.from('event refresh material') },
  } })
  await refresh
  await expect(editor).toHaveValue('浏览器人工修改：这一段是尚未提交的内容。')
  await editor.blur()
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}/draft`)).json()).draft.doc.edit_revision).toBeGreaterThan(1)
  expect((await (await request.get(`/api/articles/${aid}/draft`)).json()).draft.version).toBe(1)
  // The UI action itself queues review, including in EDITING. Do not queue a
  // separate API review first and then race finalization against a second one.
  const reviewQueued = page.waitForResponse(r => r.url().endsWith(`/articles/${aid}/advance`) && r.request().method() === 'POST')
  await page.getByRole('button', { name: '去审稿 →', exact: true }).click()
  expect((await reviewQueued).status()).toBe(200)
  await expect.poll(async () => {
    const jobs = (await (await request.get(`/api/jobs?article_id=${aid}`)).json()).jobs
    const reviews = jobs.filter((job: { type: string }) => job.type === 'review')
    return reviews.length > 0 && reviews.every((job: { status: string }) => job.status === 'done')
  }).toBe(true)
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}/reviews/latest`)).json()).current).toBe(true)
  const finalized = page.waitForResponse(r => r.url().endsWith(`/articles/${aid}/finalize`) && r.request().method() === 'POST')
  await page.getByRole('button', { name: '定稿', exact: true }).click()
  expect((await finalized).status()).toBe(200)
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}`)).json()).status).toBe('FINALIZED')
  await request.post(`/api/articles/${aid}/publish`, { data: { platforms: ['wechat_mp', 'weibo', 'x', 'xhs'] } })
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}`)).json()).status, { timeout: 15000 }).toBe('DONE')
  await page.reload()
  await expect(page.getByText('发布包已生成', { exact: false }).first()).toBeVisible()
  const files = await (await request.get(`/api/articles/${aid}/exports`)).json()
  const manifest = files.files.find((path: string) => path.endsWith('manifest.json'))
  expect(manifest).toBeTruthy()
  expect((await request.get('/files/' + manifest.replace(/\\/g, '/'))).ok()).toBe(true)
  expect((await request.get('/files/app.db')).status()).toBe(404)
  const sealed = (await (await request.get(`/api/articles/${aid}/draft`)).json()).draft
  const cards = files.files.filter((path: string) => /page-\d+\.png$/.test(path))
  expect(cards.length).toBe(sealed.doc.meta.xhs_pages.length + 1)
  await page.locator('.pub-box img').first().click()
  const viewer = page.getByRole('dialog', { name: '小红书卡片阅览' })
  await expect(viewer.getByRole('img')).toHaveAttribute('alt', '小红书卡片 1')
  await page.keyboard.press('ArrowLeft')
  await expect(viewer.getByRole('img')).toHaveAttribute('alt', '小红书卡片 1')
  await page.keyboard.press('ArrowRight')
  await expect(viewer.getByRole('img')).toHaveAttribute('alt', '小红书卡片 2')
  for (let i = 0; i < cards.length + 1; i++) await page.keyboard.press('ArrowRight')
  await expect(viewer.getByRole('img')).toHaveAttribute('alt', `小红书卡片 ${cards.length}`)
  await expect(viewer.getByRole('button', { name: '下一张卡片' })).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(viewer).toHaveCount(0)
  await page.getByText('创作', { exact: true }).click()
  await page.locator('.block-item p').first().dblclick()
  const nextEditor = page.locator('.block-item textarea').first()
  await nextEditor.fill('定稿后首次编辑，自动进入新版本。')
  await nextEditor.blur()
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}/draft`)).json()).draft.version).toBe(2)
  await expect(page.locator('.block-item p').first()).toHaveText('定稿后首次编辑，自动进入新版本。')
  await expect(page.getByText('正在查看历史版本', { exact: false })).toHaveCount(0)
  await page.getByRole('button', { name: 'v1', exact: true }).click()
  await expect(page.getByText('正在查看历史版本', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: '回滚', exact: true }).click()
  await page.locator('.n-dialog').getByRole('button', { name: '回滚', exact: true }).click()
  await expect(page.locator('.block-item p').first()).toHaveText('浏览器人工修改：这一段是尚未提交的内容。')
  expect((await (await request.get(`/api/articles/${aid}/draft`)).json()).draft.version).toBe(2)
})

test('a stale edit keeps its local buffer and receives a conflict', async ({ page, request }) => {
  const aid = await prepared(request)
  const draft = (await (await request.get(`/api/articles/${aid}/draft`)).json()).draft
  const block = draft.doc.blocks.find((block: { type: string }) => block.type === 'paragraph')
  await page.goto(`/articles/${aid}`)
  await page.locator('.block-item p').first().dblclick()
  const editor = page.locator('.block-item textarea').first()
  await editor.fill('需要保留的本地编辑')
  await request.put(`/api/drafts/${draft.id}/edit`, { data: { ops: [{ op: 'update', block_id: block.id, text: '另一个编辑会话已提交' }] } })
  const conflict = page.waitForResponse(response => response.url().endsWith('/edit') && response.status() === 409)
  await editor.blur()
  await conflict
  await expect(editor).toHaveValue('需要保留的本地编辑')
  const head = (await (await request.get(`/api/articles/${aid}/draft`)).json()).draft
  expect(head.doc.blocks.find((b: { id: string }) => b.id === block.id).text).toBe('另一个编辑会话已提交')
})

test('creation completion refreshes the open page and review receives live content', async ({ page, request }) => {
  const article = await (await request.post('/api/articles', { data: { title: '自动刷新验收', auto_collect: false } })).json()
  const aid = article.article.id
  await request.post(`/api/articles/${aid}/materials/upload-batch`, { multipart: {
    files: { name: 'source.md', mimeType: 'text/markdown', buffer: Buffer.from('任务完成后这段文稿应自动出现，无需重载页面。') },
  } })
  await page.goto(`/articles/${aid}`)
  await page.getByText('创作', { exact: true }).click()
  await page.getByRole('button', { name: '开始创作', exact: true }).click()
  await expect(page.locator('.block-item p').first()).toBeVisible()
  await request.post(`/api/articles/${aid}/advance`, { data: { stage: 'review' } })
  await page.getByText('审稿', { exact: true }).click()
  await expect(page.locator('.reader p').first()).toBeVisible()
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}`)).json()).status).toBe('EDITING')
  const draft = (await (await request.get(`/api/articles/${aid}/draft`)).json()).draft
  const block = draft.doc.blocks.find((b: { type: string }) => b.type === 'paragraph')
  await page.locator('.reader p').first().dblclick()
  const editor = page.locator('.reader textarea').first()
  await editor.fill('审稿页尚未保存的输入')
  await request.put(`/api/drafts/${draft.id}/edit`, { data: { ops: [{ op: 'update', block_id: block.id, text: '任务完成后的新内容' }] } })
  await expect(editor).toHaveValue('审稿页尚未保存的输入')
  await editor.press('Escape')
  await expect(page.locator('.reader p').first()).toHaveText('任务完成后的新内容')
  await page.getByText('创作', { exact: true }).click()
  await expect(page.locator('.block-item p').first()).toHaveText('任务完成后的新内容')
})

test('AI completion refreshes after the modal closes, including deferred events', async ({ page, request }) => {
  const aid = await prepared(request)
  const draft = (await (await request.get(`/api/articles/${aid}/draft`)).json()).draft
  const block = draft.doc.blocks.find((b: { type: string }) => b.type === 'paragraph')
  await page.goto(`/articles/${aid}`)
  await expect(page.locator('.block-item p').first()).toBeVisible()
  await page.getByRole('button', { name: '整篇重写', exact: true }).click()
  // Simulate completed LLM output via real persistence and real SSE; no paid call.
  await page.route('**/regenerate', async route => {
    const result = await (await request.put(`/api/drafts/${draft.id}/edit`, { data: {
      expected_revision: draft.doc.edit_revision,
      ops: [{ op: 'update', block_id: block.id, text: 'AI 完成后自动显示的新文案' }],
    } })).json()
    await route.fulfill({ json: result })
  })
  await page.getByRole('button', { name: '生成新版本', exact: true }).click()
  await expect(page.locator('.block-item p').first()).toHaveText('AI 完成后自动显示的新文案')
  await page.getByRole('button', { name: '整篇重写', exact: true }).click()
  await request.put(`/api/drafts/${draft.id}/edit`, { data: {
    ops: [{ op: 'update', block_id: block.id, text: '弹窗期间收到的事件也要补刷新' }],
  } })
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.locator('.block-item p').first()).toHaveText('弹窗期间收到的事件也要补刷新')
})

test('Settings reload reports success and refreshes service availability', async ({ page }) => {
  await page.goto('/settings')
  const reload = page.getByRole('button', { name: '刷新环境变量（Reload Env）', exact: true })
  await expect(reload).toBeVisible()
  const response = page.waitForResponse(r => r.url().endsWith('/settings/reload-env') && r.request().method() === 'POST')
  await reload.click()
  expect((await response).status()).toBe(200)
  await expect(page.getByText('环境变量已刷新', { exact: false })).toBeVisible()
  await expect(page.getByText('LLM 未配置（降级模式）', { exact: false })).toBeVisible()
  await page.route('**/settings/reload-env', route => route.fulfill({ status: 422, json: { detail: '.env 第 2 行格式无效（需 KEY=value）' } }))
  await reload.click()
  await expect(page.getByText('环境变量刷新失败', { exact: false })).toBeVisible()
})

test('collapsed side panels can be reopened with the mouse in wide and narrow layouts', async ({ page, request }) => {
  const aid = await prepared(request)
  await page.goto(`/articles/${aid}`)
  const left = page.locator('.left-panel')
  const right = page.locator('.right-panel')
  await expect(left).toBeVisible()
  await left.getByRole('button', { name: '收起', exact: true }).click()
  await right.getByRole('button', { name: '收起', exact: true }).click()
  await page.getByRole('button', { name: '展开创作素材窗口', exact: true }).hover()
  await expect(left).toBeVisible()
  await page.getByRole('button', { name: '展开 AI 与版本窗口', exact: true }).hover()
  await expect(right).toBeVisible()
  await page.locator('.doc-title').hover()
  await expect(left).toBeVisible()
  await expect(right).toBeVisible() // wide panels stay open on mouse leave
  await right.getByRole('button', { name: '收起', exact: true }).click()
  await page.getByRole('button', { name: '展开 AI 与版本窗口', exact: true }).click()
  await expect(right).toBeVisible()
  await page.setViewportSize({ width: 1000, height: 900 })
  await expect(left).toBeHidden()
  await page.getByRole('button', { name: '展开创作素材窗口', exact: true }).hover()
  await expect(left).toBeVisible()
  await left.hover()
  await page.locator('.doc-title').hover()
  await expect(left).toBeHidden() // narrow auto-close behavior remains
})

test('review renders image and playable video alongside independent remove controls', async ({ page, request }) => {
  const aid = await prepared(request)
  await page.goto(`/articles/${aid}`)
  const media = await page.evaluate(async () => {
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 64
    const context = canvas.getContext('2d')!
    context.fillStyle = '#cc5544'
    context.fillRect(0, 0, 64, 64)
    const png = canvas.toDataURL('image/png').split(',')[1]!
    const stream = canvas.captureStream(10)
    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm;codecs=vp8' })
    const chunks: Blob[] = []
    recorder.ondataavailable = event => chunks.push(event.data)
    const stopped = new Promise<void>(resolve => { recorder.onstop = () => resolve() })
    recorder.start()
    let frame = 0
    const timer = setInterval(() => {
      context.fillStyle = frame++ % 2 ? '#cc5544' : '#4455cc'
      context.fillRect(0, 0, 64, 64)
    }, 50)
    setTimeout(() => recorder.stop(), 400)
    await stopped
    clearInterval(timer)
    stream.getTracks().forEach(track => track.stop())
    return { png, video: Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer())) }
  })
  const image = await (await request.post(`/api/articles/${aid}/materials/upload`, { multipart: {
    file: { name: 'image.png', mimeType: 'image/png', buffer: Buffer.from(media.png, 'base64') },
  } })).json()
  const video = await (await request.post(`/api/articles/${aid}/materials/upload`, { multipart: {
    file: { name: 'clip.webm', mimeType: 'video/webm', buffer: Buffer.from(media.video) },
  } })).json()
  const draft = (await (await request.get(`/api/articles/${aid}/draft`)).json()).draft
  const edited = await request.put(`/api/drafts/${draft.id}/edit`, { data: {
    expected_revision: draft.doc.edit_revision, ops: [
      { op: 'insert_after', block_type: 'image', asset_id: image.material_id, caption: '审稿配图' },
      { op: 'insert_after', block_type: 'video', asset_id: video.material_id, caption: '审稿视频' },
    ],
  } })
  expect(edited.ok()).toBe(true)
  await page.getByText('审稿', { exact: true }).click()
  const readerImage = page.locator('.reader img')
  const readerVideo = page.locator('.reader video')
  await expect(readerImage).toBeVisible()
  await expect.poll(() => readerImage.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBe(64)
  await expect(readerVideo).toBeVisible()
  await expect.poll(() => readerVideo.evaluate((video: HTMLVideoElement) => video.videoWidth)).toBe(64)
  await readerVideo.evaluate((video: HTMLVideoElement) => video.play())
  await expect.poll(() => readerVideo.evaluate((video: HTMLVideoElement) => video.currentTime)).toBeGreaterThan(0)
  const videoBlock = page.locator('.reader-block').filter({ has: page.locator('video') })
  await videoBlock.hover()
  await videoBlock.getByTitle('删除该素材', { exact: true }).click()
  await expect(readerVideo).toHaveCount(0)
  await expect(readerImage).toBeVisible()
  const head = (await (await request.get(`/api/articles/${aid}/draft`)).json()).draft
  expect(head.version).toBe(1)
  expect(head.doc.blocks.some((b: { type: string }) => b.type === 'image')).toBe(true)
  expect(head.doc.blocks.some((b: { type: string }) => b.type === 'video')).toBe(false)
})
