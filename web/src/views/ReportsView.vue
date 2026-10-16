<script setup>
// S4-F1 第一批：报告中心（对标 v1.2 v3_reports.js 功能）
import { ref, onMounted, computed } from 'vue'
import { api, toast, esc, fmtTime, statusName, statusTag, REPORT_TABS, matchReport } from '../lib/api'

const kbStats = ref({ patterns: {}, kb: {} })
const reports = ref([])
const curTab = ref('')
const loading = ref(true)

// 知识库学习统计（语料/沉淀/已提炼章节）
const TYPE_NAMES = { monitoring: '监测', acceptance: '验收', eia: '环评' }
const learnedTip = computed(() => {
  const parts = []
  for (const [k, nm] of Object.entries(TYPE_NAMES)) {
    const secs = ((kbStats.value.patterns || {})[k] || {}).sections || []
    if (secs.length) parts.push(`${nm}: ${secs.map((x) => x.name).slice(0, 3).join('、')}`)
  }
  return parts
})

const tabCount = (t) => reports.value.filter((x) => matchReport(x, t)).length
const activeTab = computed(() => REPORT_TABS.find((t) => t.k === curTab.value) || REPORT_TABS[0])
const list = computed(() => reports.value.filter((x) => matchReport(x, activeTab.value)))

async function loadLearningStats() {
  try {
    const r = await api('GET', '/api/v2/reports/learning-stats')
    kbStats.value = r.stats || {}
  } catch (_) { /* 静默 */ }
}

async function loadReports() {
  loading.value = true
  try {
    const r = await api('GET', '/api/v2/reports')
    reports.value = r.reports || []
  } catch (_) { reports.value = [] }
  loading.value = false
}

async function createBlank() {
  try {
    await api('POST', '/api/v2/reports/generate', { type: 'blank', project_id: 'P-DEMO' })
    toast('空白报告已创建')
    loadReports()
  } catch (e) { toast(e.message) }
}

const emptyTips = {
  '': '暂无报告，任务对话完成后将自动生成并沉淀至报告中心，亦可「+ 空白报告」手动起草',
  draft: '暂无草稿报告，任务对话结束后自动生成，亦可「+ 空白报告」手动起草',
  review: '暂无审核中的报告，任务自动生成的报告将在此排队审核',
  done: '暂无已归档报告，完成审核签发后自动归档学习',
  exported: '暂无已导出的报告，在编辑器点击「导出 Word」后出现在这里',
}

// 专家意见弹窗（对齐 v1.2）
const expert = ref({ open: false, rid: '', msg: '' })
function openExpert(rid) { expert.value = { open: true, rid, msg: '' } }
async function submitExpert() {
  if (!expert.value.msg.trim()) return toast('请填写专家意见')
  try {
    const r = await api('POST', '/api/v2/reports/expert-opinion',
      { report_id: expert.value.rid, opinion: expert.value.msg })
    expert.value.open = false
    if (r.ok) { toast(`已提交，返回对话工作台查看修改（任务 #${r.task_id}）`); loadReports() }
    else toast(r.error || '提交失败')
  } catch (e) { toast(e.message) }
}

// 报告编辑器（查看 + 合规 + 导出；大纲/溯源第一版简化为只读展示）
const editor = ref({ open: false, report: null, content: '', outline: [], compliance: '' })
async function openEditor(rid) {
  try {
    const r = await api('GET', `/api/v2/reports/${rid}`)
    let content = typeof r.content === 'string' ? r.content : (r.body || '')
    if (!content.trim() && Array.isArray(r.sections)) {
      content = r.sections.map((s) => `## ${s.name || ''}\n\n${s.content || ''}`).join('\n\n')
    }
    const outline = (content || '').split('\n')
      .filter((l) => /^#{1,4}\s/.test(l) || l.trim().startsWith('附件') || l.trim().startsWith('附表'))
      .map((l) => ({ level: (l.match(/^#+/) || [''])[0].length, text: l.replace(/^#+\s*/, '') }))
    editor.value = { open: true, report: r, content, outline, compliance: '' }
  } catch (e) { toast(e.message) }
}
function closeEditor() { editor.value.open = false; loadReports() }
async function runCompliance() {
  try {
    const res = await api('POST', '/api/v2/reports/compliance',
      { report_id: editor.value.report.report_id, content: editor.value.content })
    const out = res.result || res.feedback || res
    editor.value.compliance = typeof out === 'string' ? out
      : (out.annotations ? out.annotations.map((a) => (a.severity ? '[' + a.severity + '] ' : '') + (a.note || a.message || '')).join('\n')
        : JSON.stringify(out, null, 2))
    toast('合规检查完成')
  } catch (e) { toast(e.message) }
}
function exportDocx(rid) { window.open(`/api/v2/reports/${rid}/export?fmt=docx`, '_blank') }

onMounted(() => { loadLearningStats(); loadReports() })
</script>

<template>
  <div class="shell" style="height:100vh;overflow:hidden">
    <div class="app-body" style="height:100%">
      <div class="main" style="padding:0">
        <!-- 报告中心（v-reports 视图） -->
        <section v-if="!editor.open" class="view active" style="padding:20px;overflow:auto;height:100%">
          <div class="topbar">
            <h1>报告中心</h1><span class="sp"></span>
            <span class="btn sm kb-hint" title="报告由任务列表自动生成并沉淀，反复学习提炼后反哺后续报告">自动沉淀知识库</span>
            <button class="btn sm gold" @click="createBlank">+ 空白报告</button>
          </div>
          <div class="content">
            <!-- 知识库统计条 -->
            <div class="kb-strip">
              <div class="kb-item kb-title">知识库</div>
              <div v-for="(nm, k) in TYPE_NAMES" :key="k" class="kb-item">
                <b>{{ ((kbStats.patterns || {})[k] || {}).source_count || 0 }}</b>
                <span>{{ nm }}报告语料</span>
              </div>
              <div class="kb-item"><b>{{ kbStats.kb?.report_entries || 0 }}</b><span>报告沉淀条目</span></div>
              <div class="kb-item"><b>{{ kbStats.kb?.total || 0 }}</b><span>知识库总量</span></div>
              <div v-if="learnedTip.length" class="kb-item kb-tip" :title="learnedTip.join('\n')">
                已提炼: {{ learnedTip[0] }}{{ learnedTip.length > 1 ? ' …' : '' }}
              </div>
            </div>
            <!-- Tab 过滤 -->
            <div class="tabs" style="margin-bottom:18px">
              <button v-for="t in REPORT_TABS" :key="t.k"
                :class="{ active: t.k === curTab }" @click="curTab = t.k">
                {{ t.label }} ({{ tabCount(t) }})
              </button>
            </div>
            <!-- 报告列表 -->
            <div v-if="loading" class="grid"><div class="card" style="grid-column:1/-1;text-align:center;color:var(--text-3)">加载中…</div></div>
            <div v-else-if="list.length" class="grid">
              <div v-for="r in list" :key="r.report_id || r.rid" class="card rcard">
                <div style="display:flex;justify-content:space-between;align-items:start">
                  <div class="tt">{{ esc(r.title || r.report_id || '未命名报告') }}</div>
                  <span class="tag" :class="statusTag(r.status)">{{ esc(r.status_name || statusName(r.status)) }}</span>
                </div>
                <div class="meta">
                  <span>任务 #{{ r.task_id || '—' }}</span><span>{{ fmtTime(r.updated_at) }}</span>
                </div>
                <div class="ft">
                  <span style="font-size:12px;color:var(--text-3)">{{ esc(r.workflow_node || '') }}</span>
                  <span style="display:flex;gap:6px">
                    <button class="btn sm" @click="openExpert(r.report_id || r.rid || '')">专家意见</button>
                    <button class="btn sm pri" @click="openEditor(r.report_id || r.rid || '')">打开编辑器</button>
                  </span>
                </div>
              </div>
            </div>
            <div v-else class="empty-report">
              <div class="ico">📄</div>
              <div class="txt">{{ emptyTips[activeTab.k] || emptyTips[''] }}</div>
            </div>
          </div>
        </section>

        <!-- 报告编辑器 -->
        <section v-else class="view active" style="height:100%;display:flex;flex-direction:column">
          <div class="ed-top">
            <button class="btn sm" @click="closeEditor">返回</button>
            <h2 style="margin:0;font-size:16px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
              {{ esc(editor.report?.title || editor.report?.report_id || '') }}
            </h2>
            <span class="tag" :class="statusTag(editor.report?.status)">{{ esc(statusName(editor.report?.status)) }}</span>
            <span class="sp" style="flex:1"></span>
            <button class="btn sm" @click="runCompliance">合规检查</button>
            <button class="btn sm pri" @click="exportDocx(editor.report?.report_id || editor.report?.rid || '')">导出 Word</button>
          </div>
          <div class="ed-body" style="flex:1;overflow:hidden">
            <div class="outline" style="overflow:auto">
              <h4>大纲</h4>
              <div v-if="editor.outline.length">
                <div v-for="(o, i) in editor.outline" :key="i" class="ol" :class="{ sub: o.level > 2 }">{{ esc(o.text) }}</div>
              </div>
              <div v-else style="color:var(--text-3);font-size:12px">暂无大纲</div>
            </div>
            <div class="paper" style="overflow:auto">
              <div class="sheet">
                <h1>{{ esc(editor.report?.title || '') }}</h1>
                <div class="sub2">报告编号 {{ esc(editor.report?.report_id || '') }}</div>
                <pre style="white-space:pre-wrap;font-family:inherit;margin:0">{{ esc(editor.content) }}</pre>
              </div>
            </div>
            <div class="side" style="overflow:auto">
              <h4>合规总览</h4>
              <div class="card" style="padding:12px;text-align:center">
                <div style="font-size:28px;font-weight:700;font-family:var(--mono);color:var(--green)">{{ editor.report?.compliance_score || editor.report?.score || '—' }}</div>
                <div style="font-size:12px;color:var(--text-2)">CMA 合规评分</div>
              </div>
              <h4 v-if="editor.compliance">合规批注</h4>
              <div v-if="editor.compliance" class="cmt">{{ esc(editor.compliance.slice(0, 500)) }}</div>
            </div>
          </div>
        </section>
      </div>
    </div>

    <!-- 专家意见弹窗 -->
    <div v-if="expert.open" class="overlay" @click.self="expert.open = false">
      <div class="modal">
        <h3>提交专家意见</h3>
        <div style="font-size:12px;color:var(--text-2);margin-bottom:8px">
          意见将写入该报告的关联任务对话，Agent 会按意见逐条修改并复审报告 <b>{{ esc(expert.rid) }}</b>。
        </div>
        <div class="form-row"><label>专家意见</label>
          <textarea class="input" v-model="expert.msg" style="min-height:100px"
            placeholder="如：第三章监测数据缺少质控信息，请补充质控措施及判定依据…"></textarea>
        </div>
        <div class="modal-btns">
          <button class="btn" @click="expert.open = false">取消</button>
          <button class="btn pri" @click="submitExpert">提交并修改</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ed-body { display: grid; grid-template-columns: 220px 1fr 260px; gap: 0; }
</style>
