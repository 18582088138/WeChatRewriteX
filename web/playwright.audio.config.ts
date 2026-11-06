import {defineConfig} from '@playwright/test'
const python=process.env.WENSHU_TEST_PYTHON||'python'
export default defineConfig({
  testDir:'./audio-e2e',outputDir:'./audio-test-results',timeout:90000,workers:1,
  use:{baseURL:'http://127.0.0.1:8015',viewport:{width:1440,height:1100},trace:'retain-on-failure'},
  webServer:{command:`"${python}" -X utf8 ../scripts/audio_e2e_server.py`,url:'http://127.0.0.1:8015/api/health',reuseExistingServer:false,timeout:60000},
})
