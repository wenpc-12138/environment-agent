import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// S4-F1 渐进迁移：Vite 构建产物输出到 ../static/vue/（Flask static 目录可直接伺服）
// base='/static/vue/' 使产物内资源引用指向 Flask 可伺服路径
// 入口为多页应用（第一批 reports 报告中心；后续批次追加 kb/memory/... 入口）
export default defineConfig({
  plugins: [vue()],
  base: '/static/vue/',
  build: {
    outDir: '../static/vue',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        reports: 'src/reports.html',
        kb: 'src/kb.html',
        planner: 'src/planner.html',
        chat: 'src/chat.html',
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // dev 模式代理到 Flask（127.0.0.1:5837）
      '/api': 'http://127.0.0.1:5837',
    },
  },
})
