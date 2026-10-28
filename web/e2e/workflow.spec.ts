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
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}/draft`)).json()).draft.version).toBe(2)
  await request.post(`/api/articles/${aid}/advance`, { data: { stage: 'review' } })
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}`)).json()).status).toBe('EDITING')
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}/reviews/latest`)).json()).current).toBe(true)
  await page.getByRole('button', { name: '去审稿 →', exact: true }).click()
  await page.getByRole('button', { name: '定稿', exact: true }).click()
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}`)).json()).status).toBe('FINALIZED')
  await request.post(`/api/articles/${aid}/publish`, { data: { platforms: ['wechat_mp', 'weibo', 'x'] } })
  await expect.poll(async () => (await (await request.get(`/api/articles/${aid}`)).json()).status).toBe('DONE')
  await page.reload()
  await expect(page.getByText('发布包已生成', { exact: false }).first()).toBeVisible()
  const files = await (await request.get(`/api/articles/${aid}/exports`)).json()
  const manifest = files.files.find((path: string) => path.endsWith('manifest.json'))
  expect(manifest).toBeTruthy()
  expect((await request.get('/files/' + manifest.replace(/\\/g, '/'))).ok()).toBe(true)
  expect((await request.get('/files/app.db')).status()).toBe(404)
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
