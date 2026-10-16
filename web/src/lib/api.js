// 生态Agent Vue3 前端 — 统一 API 封装（对标 v1.2 EA.api）
// S4-F1：fetch 封装 + toast/modal/esc/时间格式化工具

export async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch(path, opt);
  } catch (e) {
    throw new Error('网络错误：' + e.message);
  }
  if (!r.ok) {
    let e = '请求失败';
    try { const j = await r.json(); e = j.error || e; } catch (_) {}
    throw new Error(e);
  }
  return r.json();
}

let toastEl = null;
export function toast(msg, ms = 2200) {
  if (!toastEl) {
    toastEl = document.createElement('div');
    toastEl.id = 'toast';
    document.body.appendChild(toastEl);
  }
  toastEl.textContent = msg;
  toastEl.classList.add('show');
  clearTimeout(toastEl._tm);
  toastEl._tm = setTimeout(() => toastEl.classList.remove('show'), ms);
}

export function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

export function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return String(ts).slice(0, 16);
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 报告状态 → 中文/标签色（对齐 v1.2 v3_reports.js）
export const STATUS_NAME = {
  drafting: '草稿', review: '审核中', auto_fix: '修订中', compliance: '合规审核',
  escalate: '已升级', signoff: '已签收', learn: '归档学习', done: '已归档',
};
export function statusName(s) { return STATUS_NAME[s] || (s || '草稿'); }
export function statusTag(s) {
  return {
    drafting: 'gray', review: 'amber', auto_fix: 'amber', compliance: 'amber',
    escalate: 'red', signoff: 'green', learn: 'green', done: 'green',
  }[s] || 'gray';
}

// Tab 与后端状态机对齐（同 v1.2）
export const REPORT_TABS = [
  { k: '', label: '全部' },
  { k: 'draft', label: '草稿', match: ['drafting'] },
  { k: 'review', label: '审核中', match: ['review', 'auto_fix', 'compliance', 'escalate'] },
  { k: 'done', label: '已归档', match: ['signoff', 'learn', 'done'] },
  { k: 'exported', label: '已导出', exported: true },
];
export function matchReport(x, tab) {
  if (!tab || !tab.k) return true;
  if (tab.exported) return !!x.exported;
  return (tab.match || []).includes(x.status);
}
