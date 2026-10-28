import { defineConfig } from '@playwright/test'

const python = process.env.WENSHU_TEST_PYTHON || 'python'
export default defineConfig({
  testDir: './e2e', timeout: 45000, workers: 1,
  use: { baseURL: 'http://127.0.0.1:8011', viewport: { width: 1440, height: 1000 }, trace: 'retain-on-failure' },
  webServer: {
    command: `"${python}" -X utf8 ../scripts/e2e_server.py`,
    url: 'http://127.0.0.1:8011/api/ready', reuseExistingServer: false, timeout: 45000,
  },
})
