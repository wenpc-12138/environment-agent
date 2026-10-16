<script setup>
// S4-F1 第三批：对话工作台（对标 v1.2 v3_chat.js 核心；SSE 事件协议不变）
import { ref, onMounted, nextTick } from 'vue'
import { api, toast, esc } from '../lib/api'

// ---------- 状态 ----------
const tasks = ref([])
const curTask = ref(null)
const messages = ref([])      // 历史消息（role/content）
const input = ref('')
const busy = ref(false)
const thinking = ref('')      // 深度思考流
const thinkOpen = ref(true)
const toolCards = ref([])     // 工具卡片 [{name, ok, output}]
const md = ref('')            // 当前回答 Markdown
const budget = ref(null)
const usage = ref(null)
const flow = ref(null)        // 消息流容器
const pipeline = ref(null)    // 报告流水线阶段

const MODE = ref('craft')

// ---- H4 子代理实时操控（对齐 Hermes subagent steering）----
const subagents = ref([])       // 运行中子代理 [{id,name,role,round,partial}]
const steerDraft = ref({ sid: '', text: '' })
let subPollTimer = null

async function pollSubagents() {
  try {
    const r = await api('GET', '/api/v2/subagent/running')
    subagents.value = r?.running || []
  } catch (_) { /* 静默 */ }
}
function startSubPolling() {
  if (subPollTimer) return
  subPollTimer = setInterval(pollSubagents, 1500)
  pollSubagents()
}
function stopSubPolling() {
  if (subPollTimer) { clearInterval(subPollTimer); subPollTimer = null }
  subagents.value = []
}
async function steerSub(sid) {
  if (!steerDraft.value.text.trim()) return toast('请输入纠偏指令')
  try {
    await api('POST', `/api/v2/subagent/${sid}/steer`, { instruction: steerDraft.value.text.trim() })
    toast('纠偏指令已发送（子代理下一轮生效）')
    steerDraft.value.text = ''
  } catch (e) { toast(e.message) }
}
async function stopSub(sid) {
  try {
    await api('POST', `/api/v2/subagent/${sid}/stop`)
    toast('已请求停止（保留部分结果，可 collect 回收）')
    setTimeout(pollSubagents, 1000)
  } catch (e) { toast(e.message) }
}

// ---------- 任务 ----------
async function loadTasks() {
  try { tasks.value = (await api('GET', '/api/tasks')) || [] } catch (_) {}
}
async function openTask(tid) {
  try {
    const t = await api('GET', `/api/tasks/${tid}`)
    curTask.value = { ...t, id: tid }
    messages.value = (t.messages || []).filter((m) => m.role !== 'tool').map((m) => ({ role: m.role, content: m.content }))
    MODE.value = t.mode || 'craft'
  } catch (e) { toast(e.message) }
}
async function newTask() {
  if (!input.value.trim()) return
  try {
    const r = await api('POST', '/api/tasks', { title: input.value.slice(0, 24), mode: MODE.value })
    await openTask(r.id)
    await send()
  } catch (e) { toast(e.message) }
}

// ---------- 斜杠命令（S3-H3） ----------
async function tryCommand(content) {
  if (!content.startsWith('/')) return false
  try {
    const r = await fetch(`/api/v2/commands?text=${encodeURIComponent(content)}`)
    const j = await r.json()
    if (j.ok) {
      messages.value.push({ role: 'user', content })
      messages.value.push({ role: 'assistant', content: `[${j.label} 快捷指令] ${j.endpoint}${j.args ? '\n参数: ' + j.args : ''}` })
      input.value = ''
      scrollDown()
      return true
    }
    toast(j.error || '未知命令')
    return true
  } catch (e) { toast('命令解析失败: ' + e.message); return true }
}

// ---------- 发送 / SSE ----------
async function send() {
  const content = input.value.trim()
  if (!content || busy.value) return
  if (await tryCommand(content)) return
  if (!curTask.value) return newTask()

  messages.value.push({ role: 'user', content })
  input.value = ''
  busy.value = true
  thinking.value = ''; md.value = ''; toolCards.value = []; budget.value = null; usage.value = null; pipeline.value = null

  const body = { content, mode: MODE.value, effort: 'mid' }
  try {
    const resp = await fetch(`/api/tasks/${curTask.value.id}/chat`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    if (!resp.ok) { const j = await resp.json().catch(() => ({})); throw new Error(j.error || '发送失败') }
    const reader = resp.body.getReader()
    const dec = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2)
        for (const line of chunk.split('\n')) {
          if (!line.startsWith('data:')) continue
          let ev; try { ev = JSON.parse(line.slice(5).trim()) } catch (_) { continue }
          handleSSE(ev)
        }
      }
    }
    scrollDown()
  } catch (e) {
    md.value = `**错误**：${e.message}`
  } finally {
    busy.value = false
    loadTasks(); loadMessages()
    // H4：对话回合结束，短暂延迟后若无运行子代理则停止轮询
    setTimeout(() => {
      if (!subagents.value.length) stopSubPolling()
      else pollSubagents()
    }, 2500)
  }
}

function handleSSE(ev) {
  switch (ev.event) {
    case 'budget': budget.value = ev; break
    case 'usage': usage.value = { ...ev }; break
    case 'pipeline_stage': pipeline.value = ev; break
    case 'reasoning': thinking.value += ev.content || ''; scrollDown(); break
    case 'delta': md.value += ev.content || ''; scrollDown(); break
    case 'web_search_status':
      toolCards.value.push({ name: '内置联网搜索', ok: true, output: ({ in_progress: '正在初始化联网搜索…', searching: '正在联网搜索…', completed: '搜索完成' })[ev.status] || '联网搜索中…' })
      break
    case 'tool_start':
      toolCards.value.push({ name: ev.name || '工具', ok: null, output: '', args: ev.args, running: true })
      // H4：派生子代理时启动运行状态轮询
      if (ev.name === 'spawn_subagent' || (ev.name || '').includes('子代理')) {
        startSubPolling()
      }
      break
    case 'tool_end': {
      const t = toolCards.value[toolCards.value.length - 1]
      if (t) { t.ok = ev.ok; t.output = ev.output || ''; t.running = false }
      break
    }
    case 'assistant_done': break
    case 'kb_changed': break
    case 'done': break
    case 'error': md.value += `\n\n**错误**：${ev.message || ''}`; break
  }
}

async function loadMessages() {
  if (!curTask.value) return
  try {
    const t = await api('GET', `/api/tasks/${curTask.value.id}`)
    messages.value = (t.messages || []).filter((m) => m.role !== 'tool').map((m) => ({ role: m.role, content: m.content }))
  } catch (_) {}
}

function scrollDown() {
  nextTick(() => { const el = flow.value; if (el) el.scrollTop = el.scrollHeight })
}
function stop() {
  busy.value = false
  if (curTask.value) api('POST', `/api/tasks/${curTask.value.id}/stop`).catch(() => {})
}

// 简单 Markdown 渲染（标题/粗体/列表/换行，对标 EA.md 轻量版）
function renderMd(text) {
  let t = esc(text || '')
  t = t.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
  t = t.replace(/^### (.+)$/gm, '<h4>$1</h4>')
  t = t.replace(/^## (.+)$/gm, '<h3>$1</h3>')
  t = t.replace(/^# (.+)$/gm, '<h2>$1</h2>')
  t = t.replace(/^- (.+)$/gm, '<div>• $1</div>')
  t = t.replace(/^\d+\. (.+)$/gm, '<div>• $1</div>')
  t = t.replace(/\n/g, '<br>')
  return t
}

onMounted(() => { loadTasks(); loadMessages() })
</script>

<template>
  <div class="shell" style="height:100vh;overflow:hidden">
    <div class="app-body" style="height:100%">
      <div class="main" style="padding:0;display:flex;height:100%">
        <!-- 任务侧栏 -->
        <aside style="width:220px;border-right:1px solid var(--border);padding:12px;overflow:auto;flex-shrink:0">
          <h4 style="margin:0 0 10px">任务</h4>
          <button class="btn sm gold" style="width:100%;margin-bottom:8px" @click="curTask=null; input=''">+ 新对话</button>
          <div v-for="t in tasks" :key="t.id" class="card" style="padding:8px 10px;margin-bottom:6px;cursor:pointer;font-size:12px"
            :class="{ 'kb-item': false }" :style="{ borderColor: curTask && curTask.id === t.id ? 'var(--accent)' : '' }"
            @click="openTask(t.id)">
            <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ esc(t.title) }}</div>
            <div style="font-size:10px;color:var(--text-3)">{{ t.status }} · {{ t.mode }}</div>
          </div>
        </aside>

        <!-- 对话区 -->
        <div style="flex:1;display:flex;flex-direction:column;min-width:0">
          <!-- 消息流 -->
          <div ref="flow" class="msg-flow" style="flex:1;overflow:auto;padding:20px">
            <div v-if="!messages.length && !md && !busy" style="text-align:center;color:var(--text-3);padding:60px 0">
              开始新的对话，输入指令让 Agent 工作
            </div>
            <!-- 历史消息 -->
            <div v-for="(m, i) in messages" :key="i" class="msg">
              <div class="who">{{ m.role === 'user' ? '你' : 'Agent' }}</div>
              <div class="bubble"><div class="md" v-html="renderMd(m.content)"></div></div>
            </div>
            <!-- 当前回答 -->
            <div v-if="md || busy" class="msg">
              <div class="who">Agent · {{ MODE }} 模式</div>
              <div class="bubble">
                <!-- 思考面板 -->
                <div v-if="thinking" class="thinkbox" :class="{ open: thinkOpen, done: !busy }" style="display:block">
                  <div class="think-head" @click="thinkOpen = !thinkOpen">
                    <span class="think-label">{{ busy ? '深度思考中' : '已思考' }}</span>
                    <span class="think-count">{{ thinking.length }} 字</span>
                  </div>
                  <div v-if="thinkOpen" class="think-body">{{ thinking }}</div>
                </div>
                <!-- 报告流水线阶段 -->
                <div v-if="pipeline" class="toolcard">
                  <div class="tt">{{ pipeline.label || pipeline.stage }}</div>
                  <div class="out">{{ pipeline.desc }}</div>
                </div>
                <!-- 工具卡片 -->
                <div v-for="(t, i) in toolCards" :key="i" class="toolcard">
                  <div class="tt">
                    {{ esc(t.name) }}
                    <span v-if="t.running" class="tag blue">执行中…</span>
                    <span v-else-if="t.ok === false" class="tag red">失败</span>
                    <span v-else-if="t.ok" class="tag green">完成</span>
                  </div>
                  <div class="out">{{ esc(String(t.output || '').slice(0, 200)) }}</div>
                </div>
                <!-- 正文 -->
                <div class="md" v-html="renderMd(md)"></div>
              </div>
            </div>
          </div>

          <!-- H4 子代理运行中面板（对齐 Hermes subagent steering） -->
          <div v-if="subagents.length" style="padding:0 20px 6px">
            <div style="font-size:11px;color:var(--text-2);margin-bottom:4px;display:flex;justify-content:space-between">
              <b>子代理运行中（{{ subagents.length }}）</b>
              <span style="cursor:pointer;color:var(--text-3)" @click="pollSubagents">刷新</span>
            </div>
            <div style="display:flex;flex-direction:column;gap:6px">
              <div v-for="s in subagents" :key="s.id" class="toolcard"
                style="border:1px solid var(--border);border-radius:8px;padding:8px 10px">
                <div style="display:flex;align-items:center;gap:8px">
                  <span class="tag blue">{{ esc(s.name) }}</span>
                  <span style="font-size:11px;color:var(--text-3)">{{ esc(s.role) }} · 第 {{ s.round }} 轮 · {{ esc(s.state) }}</span>
                  <span style="margin-left:auto;display:flex;gap:6px">
                    <button class="btn sm" @click="steerDraft.sid = s.id">纠偏</button>
                    <button class="btn sm danger" @click="stopSub(s.id)">停止</button>
                  </span>
                </div>
                <div v-if="s.partial" style="font-size:11px;color:var(--text-3);margin-top:4px">
                  {{ esc(s.partial) }}
                </div>
                <div v-if="steerDraft.sid === s.id" style="display:flex;gap:6px;margin-top:6px">
                  <input class="input" v-model="steerDraft.text" style="flex:1;font-size:12px"
                    placeholder="纠偏指令，如：请聚焦第三章监测结果…"
                    @keydown.enter="steerSub(s.id)">
                  <button class="btn sm pri" @click="steerSub(s.id)">发送</button>
                </div>
              </div>
            </div>
          </div>

          <!-- 预算/用量 -->
          <div style="padding:0 20px 8px;font-size:11px;color:var(--text-3);display:flex;gap:14px;justify-content:flex-end">
            <span v-if="budget">Token {{ budget.estimated_tokens }} / {{ budget.soft_budget }}（{{ budget.context_source }}）</span>
            <span v-if="usage">用量 {{ usage.completion || 0 }} 输出 · 缓存命中 {{ usage.hit || 0 }}</span>
          </div>

          <!-- 输入区 -->
          <div class="inputbar">
            <div class="inputbox">
              <textarea id="chat-input-vue" rows="2" v-model="input" style="width:100%;resize:none;border:none;outline:none;background:transparent;color:var(--text-1);font-size:14px;font-family:inherit"
                placeholder="继续提问，或输入 / 调用技能…"
                @keydown.enter.exact.prevent="busy ? null : (curTask ? send() : newTask())"></textarea>
              <div style="display:flex;align-items:center;gap:8px;padding-top:6px">
                <select v-model="MODE" class="input" style="width:120px;font-size:12px">
                  <option value="craft">craft 执行</option>
                  <option value="ask">ask 问答</option>
                  <option value="plan">plan 规划</option>
                </select>
                <span style="flex:1"></span>
                <button v-if="busy" class="btn danger sm" @click="stop">结束</button>
                <button v-else class="btn pri sm" @click="curTask ? send() : newTask()">发送</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.msg-flow::-webkit-scrollbar { width: 6px }
.msg-flow::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px }
.thinkbox { border: 1px solid var(--border); border-radius: 8px; margin-bottom: 8px; overflow: hidden }
.think-head { display: flex; align-items: center; gap: 8px; padding: 6px 10px; cursor: pointer; font-size: 12px; color: var(--text-2) }
.think-body { padding: 0 10px 8px; font-size: 12px; color: var(--text-3); max-height: 120px; overflow: auto; white-space: pre-wrap }
.toolcard { border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-bottom: 6px; font-size: 12px }
.toolcard .tt { display: flex; align-items: center; gap: 8px; font-weight: 600 }
.toolcard .out { color: var(--text-3); margin-top: 4px }
.bubble .md { line-height: 1.7 }
</style>
