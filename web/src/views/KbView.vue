<script setup>
// S4-F1 第二批：知识库管理（对标 v1.2 v3_kb.js 核心功能）
import { ref, onMounted, computed } from 'vue'
import { api, toast, esc, fmtTime } from '../lib/api'

const CATS = [
  { v: '', label: '全部' },
  { v: 'standard', label: '标准规范' },
  { v: 'policy', label: '政策法规' },
  { v: 'gov', label: '政府发布' },
  { v: 'draft', label: '征求意见稿' },
  { v: 'network', label: '网络资料' },
  { v: 'other', label: '其他' },
]
const CAT_COLOR = { standard: 'blue', policy: 'green', gov: 'gold', draft: 'gray', network: 'gray', other: 'gray' }
const catLabel = (v) => (CATS.find((c) => c.v === v) || { label: v || '其他' }).label

const stats = ref({})
const seg = ref('search')
const cat = ref('')
const q = ref('')
const entries = ref([])
const cur = ref(null)
const detailMode = ref('view') // view | new
const newForm = ref({ title: '', category: 'standard', content: '' })
const loading = ref(false)

const segs = [
  { v: 'search', label: '关键词' },
  { v: 'hybrid', label: '混合' },
  { v: 'vector', label: '向量' },
]

async function loadStats() {
  try { stats.value = await api('GET', '/api/kb/stats') } catch (_) {}
}
let debounceTimer = null
function onSearch() { clearTimeout(debounceTimer); debounceTimer = setTimeout(loadList, 350) }

async function loadList() {
  loading.value = true
  let items = []
  try {
    const c = cat.value ? `&category=${encodeURIComponent(cat.value)}` : ''
    if (q.value.trim()) {
      const path = seg.value === 'hybrid' ? '/api/kb/hybrid' : seg.value === 'vector' ? '/api/kb/vector' : '/api/kb/search'
      const r = await api('GET', `${path}?q=${encodeURIComponent(q.value.trim())}${c}`)
      items = Array.isArray(r) ? r : (r.results || r.items || [])
    } else {
      const r = await api('GET', `/api/kb${c}`)
      items = Array.isArray(r) ? r : (r.items || r.results || [])
    }
  } catch (_) { items = [] }
  entries.value = items
  loading.value = false
}

function openDetail(e) { cur.value = e; detailMode.value = 'view' }

async function saveNew() {
  if (!newForm.value.title.trim()) return toast('请填写标题')
  try {
    await api('POST', '/api/kb', { ...newForm.value })
    toast('已创建'); detailMode.value = 'view'; cur.value = null
    loadStats(); loadList()
  } catch (e) { toast(e.message) }
}

function pickImport() {
  const inp = document.createElement('input')
  inp.type = 'file'; inp.multiple = true; inp.accept = '.pdf,.docx,.doc,.html,.htm,.txt,.md,.xlsx'
  inp.onchange = async () => {
    const fd = new FormData()
    for (const f of inp.files) fd.append('files', f)
    try {
      const r = await fetch('/api/kb/import', { method: 'POST', body: fd })
      const j = await r.json()
      if (!r.ok) throw new Error(j.error || '导入失败')
      toast(`导入完成：${j.imported || j.count || '完成'}`)
      loadStats(); loadList()
    } catch (e) { toast(e.message) }
  }
  inp.click()
}

async function runOp(name, path, body) {
  try {
    const r = await api('POST', path, body || {})
    toast(`${name}完成：${(r && (r.message || r.detail)) || '完成'}`)
    loadStats(); loadList()
  } catch (e) { toast(e.message) }
}
async function runGet(name, path) {
  try {
    const r = await api('GET', path)
    const items = Array.isArray(r) ? r : (r.issues || r.conflicts || r.imports || [])
    const txt = items.length ? items.map((x) => (x.issue || x.type || x.message || x.file || JSON.stringify(x))).slice(0, 10).join('\n') : '无结果'
    toast(`${name}：${items.length} 项`)
    alert(`${name}\n${txt.slice(0, 800)}`)
  } catch (e) { toast(e.message) }
}

onMounted(() => { loadStats(); loadList() })
</script>

<template>
  <div class="shell" style="height:100vh;overflow:hidden">
    <div class="app-body" style="height:100%">
      <div class="main" style="padding:0">
        <section class="view active" style="height:100%;display:flex;flex-direction:column;padding:20px;overflow:hidden">
          <div class="topbar" style="flex-wrap:wrap;gap:6px">
            <h1>知识库管理</h1><span class="sp"></span>
            <button class="btn sm" @click="pickImport">导入文件</button>
            <button class="btn sm" @click="runGet('质量检查', '/api/kb/qc')">质量检查</button>
            <button class="btn sm" @click="runOp('备份', '/api/kb/backup')">备份</button>
            <button class="btn sm" @click="runOp('批量解读', '/api/kb/interpret-batch')">批量解读</button>
            <button class="btn sm" @click="runOp('批量总结', '/api/kb/summarize-batch')">批量总结</button>
            <button class="btn sm" @click="runGet('导入历史', '/api/kb/imports')">导入历史</button>
            <button class="btn sm" @click="runOp('采集', '/api/kb/harvest', { title: '对话收割', qa_pairs: [] })">采集</button>
            <button class="btn sm" @click="runGet('冲突检测', '/api/kb/conflicts')">冲突检测</button>
            <button class="btn sm" @click="runOp('知识库审计', '/api/kb/audit')">审计</button>
            <button class="btn sm gold" @click="detailMode='new'">+ 新建条目</button>
          </div>

          <!-- 统计行 -->
          <div class="stat-row" style="margin:14px 0">
            <div class="stat" v-for="(v, k) in stats" :key="k" style="text-align:center;padding:6px 14px">
              <div style="font-size:20px;font-weight:700;font-family:var(--mono)">{{ v }}</div>
              <div style="font-size:11px;color:var(--text-3)">{{ k }}</div>
            </div>
          </div>

          <div class="kb" style="flex:1;min-height:0">
            <!-- 列表 -->
            <div class="kb-list" style="display:flex;flex-direction:column;min-height:0">
              <div class="search-zone">
                <div class="seg">
                  <button v-for="s in segs" :key="s.v" :class="{ on: seg === s.v }" @click="seg=s.v; loadList()">{{ s.label }}</button>
                </div>
                <input class="input" v-model="q" placeholder="检索标准号 / 关键词，如 HJ 166" @input="onSearch">
                <div class="cats">
                  <span v-for="c in CATS" :key="c.v" class="tag"
                    :class="[(cat === c.v ? 'on ' : '') + (c.v ? (CAT_COLOR[c.v] || 'gray') : 'gray')]"
                    @click="cat=c.v; loadList()">{{ c.label }}</span>
                </div>
              </div>
              <div class="ent" style="flex:1;overflow:auto">
                <div v-if="loading" style="color:var(--text-3);padding:20px;text-align:center">加载中…</div>
                <div v-else-if="!entries.length" style="color:var(--text-3);padding:40px;text-align:center">暂无条目</div>
                <div v-for="e in entries" :key="e.id" class="ei" @click="openDetail(e)">
                  <div class="t">{{ esc(e.title) }} <span v-if="e.std_no" class="tag blue" style="margin-left:6px">{{ esc(e.std_no) }}</span></div>
                  <div class="m">
                    <span class="tag" :class="CAT_COLOR[e.category] || 'gray'">{{ catLabel(e.category) }}</span>
                    <span v-if="e.validity" class="tag gray">{{ esc(e.validity) }}</span>
                    <span style="color:var(--text-3);font-size:11px">{{ fmtTime(e.updated_at || e.created_at) }}</span>
                  </div>
                  <div class="s" style="color:var(--text-3);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                    {{ esc(String(e.content || e.snippet || '').slice(0, 80)) }}
                  </div>
                </div>
              </div>
            </div>

            <!-- 详情 / 新建 -->
            <div class="kb-detail" style="overflow:auto">
              <div v-if="detailMode === 'new'" class="kb-body">
                <div class="kb-head"><h2 style="font-size:18px">新建条目</h2>
                  <span class="sp" style="flex:1"></span>
                  <button class="btn pri sm" @click="saveNew">保存</button>
                </div>
                <input class="input" v-model="newForm.title" placeholder="标题" style="width:100%;margin-bottom:8px">
                <select class="input" v-model="newForm.category" style="width:100%;margin-bottom:8px">
                  <option v-for="c in CATS.filter(x=>x.v)" :key="c.v" :value="c.v">{{ c.label }}</option>
                </select>
                <textarea class="input" v-model="newForm.content" style="width:100%;min-height:260px" placeholder="正文内容"></textarea>
              </div>
              <div v-else-if="cur" class="kb-body">
                <div class="kb-head"><h2 style="font-size:18px">{{ esc(cur.title) }}</h2></div>
                <div class="m" style="margin:8px 0">
                  <span class="tag" :class="CAT_COLOR[cur.category] || 'gray'">{{ catLabel(cur.category) }}</span>
                  <span v-if="cur.std_no" class="tag blue">{{ esc(cur.std_no) }}</span>
                  <span v-if="cur.validity" class="tag gray">{{ esc(cur.validity) }}</span>
                  <span v-if="cur.org" class="tag gray">{{ esc(cur.org) }}</span>
                </div>
                <div v-if="cur.url" style="font-size:12px;margin-bottom:8px"><a :href="cur.url" target="_blank" style="color:var(--accent)">{{ esc(cur.url) }}</a></div>
                <pre style="white-space:pre-wrap;font-family:inherit;font-size:13px;line-height:1.7;color:var(--text-1)">{{ esc(cur.content) }}</pre>
              </div>
              <div v-else style="color:var(--text-3);padding:40px;text-align:center">选择左侧条目查看详情</div>
            </div>

            <!-- 侧栏 -->
            <div class="kb-side" style="overflow:auto">
              <h4>操作</h4>
              <div class="card" style="padding:12px;display:flex;flex-direction:column;gap:6px">
                <button class="btn sm" @click="runOp('批量解读', '/api/kb/interpret-batch')">批量解读</button>
                <button class="btn sm" @click="runOp('批量总结', '/api/kb/summarize-batch')">批量总结</button>
                <button class="btn sm" @click="runOp('知识库备份', '/api/kb/backup')">备份快照</button>
                <button class="btn sm" @click="runOp('知识库审计', '/api/kb/audit')">健康审计</button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
