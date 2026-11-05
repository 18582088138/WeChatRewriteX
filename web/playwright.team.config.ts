import {defineConfig} from '@playwright/test'
const python=process.env.WENSHU_TEST_PYTHON || 'python'
export default defineConfig({
  testDir:'./team-e2e',outputDir:'./team-test-results',timeout:60000,workers:1,
  use:{baseURL:'http://127.0.0.1:8013',viewport:{width:1440,height:1000},trace:'retain-on-failure'},
  webServer:{command:`"${python}" -X utf8 ../scripts/team_e2e_server.py`,url:'http://127.0.0.1:8013/api/health',reuseExistingServer:false,timeout:60000},
})
