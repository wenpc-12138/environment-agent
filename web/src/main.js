// 生态Agent Vue3 前端 — 入口（多页应用）
// S4-F1 渐进迁移：各视图独立挂载，构建产物伺服于 /static/vue/
// 挂载点：reports.html → #reports-app / kb.html → #kb-app /
// planner.html → #planner-app / chat.html → #chat-app
import { createApp } from 'vue'
import ReportsView from './views/ReportsView.vue'
import KbView from './views/KbView.vue'
import PlannerView from './views/PlannerView.vue'
import ChatView from './views/ChatView.vue'

function mount(id, comp) {
  const el = document.getElementById(id)
  if (el) createApp(comp).mount(el)
}

mount('reports-app', ReportsView)
mount('kb-app', KbView)
mount('planner-app', PlannerView)
mount('chat-app', ChatView)
