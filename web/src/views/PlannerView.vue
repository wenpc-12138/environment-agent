<script setup>
// S4-F1 第二批：计划调度（定时任务 + 规划器）
// H3 Cron 记忆：任务卡片显示上次运行摘要 / 记忆草稿本编辑 / continuity 开关
import { ref, onMounted } from 'vue'
import { api, toast, esc, fmtTime } from '../lib/api'

const tasks = ref([])
const nlInput = ref('')
const planInput = ref('')
const planOut = ref('')
const planSteps = ref([])
const notepad = ref({ sid: null, text: '', open: false })

async function loadTasks() {
  try {
    const r = await api('GET', '/api/v2/schedule')
    tasks.value = r?.schedules || r?.items || []
  } catch (_) { tasks.value = [] }
}

async function addTask() {
  if (!nlInput.value.trim()) return toast('请输入定时任务描述，如「每天9点生成空气质量日报」')
  try {
    const r = await api('POST', '/api/v2/schedule', { title: nlInput.value.trim() })
    toast(r.message || '已创建'); nlInput.value = ''; loadTasks()
  } catch (e) { toast(e.message) }
}

async function taskAction(sid, action) {
  try {
    const r = await api('POST', `/api/v2/schedule/${sid}/${action}`)
    toast(r.message || '已' + ({ pause: '暂停', resume: '恢复', remove: '删除' })[action])
    loadTasks()
  } catch (e) { toast(e.message) }
}

async function tickNow() {
  try { await api('POST', '/api/v2/schedule/tick'); toast('已触发到期任务'); loadTasks() }
  catch (e) { toast(e.message) }
}

// ---- H3 Cron 记忆 ----
async function toggleContinuity(t) {
  try {
    await api('POST', `/api/v2/schedule/${t.id}/continuity`, { on: !t.continuity })
    toast(t.continuity ? '已关闭连续性' : '已开启连续性（下次运行注入上次摘要）')
    loadTasks()
  } catch (e) { toast(e.message) }
}

function openNotepad(t) {
  notepad.value = { sid: t.id, text: t.notepad || '', open: true }
}
async function saveNotepad() {
  try {
    await api('POST', `/api/v2/schedule/${notepad.value.sid}/notepad`,
      { text: notepad.value.text })
    toast('草稿本已保存'); notepad.value.open = false; loadTasks()
  } catch (e) { toast(e.message) }
}

async function runPlan() {
  if (!planInput.value.trim()) return toast('请输入规划任务描述')
  try {
    const r = await api('POST', '/api/v2/plan/run', { text: planInput.value.trim(), mode_hint: 'plan' })
    planSteps.value = r.steps || []
    planOut.value = planSteps.value.length
      ? planSteps.value.map((s) => `${s.seq}. ${s.goal} — ${s.action}(${s.target || ''})`).join('\n')
      : '（未生成计划）'
  } catch (e) { toast(e.message); planOut.value = '' }
}

onMounted(loadTasks)
</script>

<template>
  <div class="shell" style="height:100vh;overflow:hidden">
    <div class="app-body" style="height:100%">
      <div class="main" style="padding:0">
        <section class="view active" style="height:100%;overflow:auto;padding:20px">
          <div class="topbar"><h1>计划调度</h1><span class="sp"></span>
            <button class="btn sm" @click="tickNow">立即触发</button>
          </div>

          <!-- 定时任务 -->
          <div class="card" style="padding:16px;margin-bottom:16px">
            <h4 style="margin:0 0 10px">定时任务（自然语言创建，H3 跨运行记忆）</h4>
            <div style="display:flex;gap:8px;margin-bottom:12px">
              <input class="input" v-model="nlInput" style="flex:1"
                placeholder="如：每天9点生成空气质量日报 / 每周一10:30 查新标准"
                @keydown.enter="addTask">
              <button class="btn pri" @click="addTask">添加</button>
            </div>
            <div v-if="tasks.length" class="list" style="display:flex;flex-direction:column;gap:8px">
              <div v-for="t in tasks" :key="t.id" class="card" style="padding:10px 12px">
                <div style="display:flex;align-items:center;gap:10px">
                  <span class="tag" :class="t.enabled ? 'green' : 'gray'">{{ t.enabled ? 'ON' : 'OFF' }}</span>
                  <div style="flex:1;min-width:0">
                    <div style="font-size:13px">{{ esc(t.title) }}</div>
                    <div style="font-size:11px;color:var(--text-3)">cron: {{ esc(t.cron_desc) }} · 下次: {{ fmtTime(t.next_run) }}</div>
                  </div>
                  <span style="display:flex;gap:6px;align-items:center">
                    <span class="tag" :class="t.continuity ? 'blue' : 'gray'" title="上次运行摘要注入下次（H3）"
                      style="cursor:pointer" @click="toggleContinuity(t)">连续性 {{ t.continuity ? '开' : '关' }}</span>
                    <button class="btn sm" @click="openNotepad(t)" title="任务级持久草稿本（H3）">草稿本</button>
                    <button class="btn sm" @click="taskAction(t.id, 'pause')" v-if="t.enabled">暂停</button>
                    <button class="btn sm" @click="taskAction(t.id, 'resume')" v-else>恢复</button>
                    <button class="btn sm danger" @click="taskAction(t.id, 'remove')">删除</button>
                  </span>
                </div>
                <!-- H3：上次运行摘要（连续性记忆） -->
                <div v-if="t.last_summary" style="margin-top:6px;padding:6px 8px;background:var(--bg-2);border-radius:6px;font-size:11px;color:var(--text-2)">
                  <b>上次运行摘要</b>：{{ esc(String(t.last_summary).slice(0, 200)) }}{{ String(t.last_summary).length > 200 ? '…' : '' }}
                </div>
                <div v-else style="margin-top:6px;font-size:11px;color:var(--text-3)">（尚未运行；运行后此处显示上次摘要，供下次连续性参考）</div>
              </div>
            </div>
            <div v-else style="color:var(--text-3);font-size:12px;padding:10px 0">暂无定时任务</div>
          </div>

          <!-- 显式规划器 -->
          <div class="card" style="padding:16px">
            <h4 style="margin:0 0 10px">显式规划器（G1 Plan-Execute）</h4>
            <div style="display:flex;gap:8px;margin-bottom:12px">
              <input class="input" v-model="planInput" style="flex:1"
                placeholder="如：编制噪声监测报告"
                @keydown.enter="runPlan">
              <button class="btn pri" @click="runPlan">生成计划</button>
            </div>
            <pre v-if="planOut" style="white-space:pre-wrap;font-family:inherit;font-size:13px;line-height:1.7;background:var(--bg-2);padding:12px;border-radius:8px">{{ planOut }}</pre>
          </div>
        </section>
      </div>
    </div>

    <!-- H3：草稿本编辑弹窗 -->
    <div v-if="notepad.open" class="overlay" @click.self="notepad.open = false">
      <div class="modal">
        <h3>任务 #{{ notepad.sid }} 记忆草稿本</h3>
        <div style="font-size:12px;color:var(--text-2);margin-bottom:8px">
          草稿本跨每次运行保留；Agent 运行时会读取，可经对话维护（H3 Cron 记忆）。
        </div>
        <textarea class="input" v-model="notepad.text" style="min-height:120px"
          placeholder="如：用户偏好关注 PM2.5 与氨氮；上次已报告超标点位勿重复…"></textarea>
        <div class="modal-btns">
          <button class="btn" @click="notepad.open = false">取消</button>
          <button class="btn pri" @click="saveNotepad">保存</button>
        </div>
      </div>
    </div>
  </div>
</template>
