import { test, expect } from '@playwright/test'

test('stage workbench preserves edits, reuses segments and plays MP3', async ({ page, request }) => {
  const article = (await (await request.get('/api/articles')).json()).articles.find((row: any) => row.title === '音频阶段测试主题')
  const base = `/api/articles/${article.id}/audio`
  await page.goto(`/articles/${article.id}`)
  await page.getByText('音频创作', { exact: true }).click()
  await page.getByRole('button', { name: '从图文派生口播稿', exact: true }).click()
  await expect(page.getByLabel('口播段落 1', { exact: true })).toBeVisible()
  let state = await (await request.get(base)).json()
  await page.getByLabel('已有音色', { exact: true }).selectOption(state.voices[0].id)
  await page.getByRole('button', { name: '保存口播与设置', exact: true }).click()
  await page.getByRole('button', { name: '估算本次调用', exact: true }).click()
  await expect(page.getByText('新请求 2 次', { exact: false })).toBeVisible()
  if (!state.features.reviews) {
    await expect(page.getByRole('button', { name: '提交口播审核', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'AI 口播审阅（产生模型调用）', exact: true })).toHaveCount(0)
  }
  if (!state.features.mix) {
    await expect(page.getByText('段后停顿（毫秒）', { exact: true })).toHaveCount(0)
  }
  async function generate() {
    const pending = page.waitForResponse(r => r.url().endsWith(base + '/generate') && r.request().method() === 'POST')
    await page.getByRole('button', { name: '生成/更新完整旁白', exact: true }).click()
    const response = await pending
    expect(response.status()).toBe(200)
    const batch = await response.json()
    await expect.poll(async () => (await (await request.get(base + '/batches/' + batch.id)).json()).status,
      { timeout: 40000 }).toBe('done')
  }
  await generate()
  await expect(page.getByText('新请求 2 次', { exact: false })).toHaveCount(0)
  await page.getByLabel('口播段落 1', { exact: true }).fill('保留事实的人工修订，背景轮询不能覆盖这段输入。')
  await page.waitForTimeout(3100)
  await expect(page.getByLabel('口播段落 1', { exact: true })).toHaveValue(/人工修订/)
  await page.getByRole('button', { name: '保存口播与设置', exact: true }).click()
  await generate()
  state = await (await request.get(base)).json()
  expect(state.batches[0].attempts).toHaveLength(1)
  expect(state.batches[0].result.cache_hits).toBe(1)
  const player = page.locator('.batch audio').first()
  const expectedUrl = state.batches[0].files.find((file: any) => file.name === 'audio.mp3').url
  await expect(player).toHaveAttribute('src', expectedUrl)
  await player.evaluate(async (node: HTMLAudioElement) => { node.load(); await node.play() })
  await expect.poll(() => player.evaluate((node: HTMLAudioElement) => node.currentTime), { timeout: 10000 }).toBeGreaterThan(0)
  await player.evaluate((node: HTMLAudioElement) => node.pause())
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  await page.screenshot({ path: 'audio-test-results/staged-workbench.png', fullPage: true })
})
