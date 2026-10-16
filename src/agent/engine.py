# -*- coding: utf-8 -*-
"""S2-M1 主循环迁移：Agent 引擎（主循环 + 对话旁路）。

自根目录 agent_core.py 原样迁入：Agent 类（run/_loop/规划/报告流水线/
专家意见/模块蓝图旁路）+ request_stop/_stopped/infer_domain 等模块级
函数。系统提示组装见 prompts.py。
"""
import json
import threading
import time
from src.core import db_v12 as db
import tools
from ..core import context as context_mgr
from ..llm import providers
from src.gateway import bridge_compat as v2_bridge
import report_orchestrator as orch
import materials_check
import report_rewrite

from .prompts import build_system_prompt

STOP_EVENTS = {}

def request_stop(task_id):
    ev = STOP_EVENTS.setdefault(task_id, threading.Event())
    ev.set()

def _stopped(task_id):
    ev = STOP_EVENTS.get(task_id)
    return bool(ev and ev.is_set())

_DOMAIN_KEYWORDS = [
    ("大气", ["大气", "废气", "vocs", "voc", "颗粒物", "pm2.5", "pm10", "排放"]),
    ("水环境", ["水", "废水", "污水", "河流", "湖泊", "地下水", "cod", "氨氮", "总磷", "水质"]),
    ("土壤", ["土壤", "污染地块", "耕地", "地下水污染", "场地调查"]),
    ("固废", ["固废", "危废", "固体废物", "危险废物", "垃圾"]),
    ("噪声", ["噪声", "噪音", "声环境"]),
    ("辐射", ["辐射", "放射", "电磁"]),
    ("环评", ["环评", "环境影响评价", "环保验收"]),
    ("监测", ["监测", "检测", "采样", "分析方法"]),
    ("政策法规", ["标准", "法规", "条例", "办法", "政策", "规定"]),
]

def infer_domain(title):
    """按任务标题关键词推断领域, 未命中返回 未分类"""
    t = (title or "").lower()
    for name, kws in _DOMAIN_KEYWORDS:
        for k in kws:
            if k in t:
                return name
    return "未分类"

class Agent:
    # 写库类工具:执行成功后推送 kb_changed 事件,触发前端实时刷新知识库(无需手动刷新页面)
    KB_WRITE_TOOLS = {
        "kb_save", "kb_import", "kb_harvest", "kb_correct", "kb_interpret",
        "kb_summarize", "kb_summarize_batch", "kb_recheck_batch", "kb_convert",
    }

    def __init__(self, task_id, provider, mode="craft"):
        self.task_id = task_id
        self.provider = provider
        self.mode = mode
        self.task = db.get_task(task_id) or {"title": "", "mode": mode}
        self.stop_event = STOP_EVENTS.setdefault(task_id, threading.Event())

    # ---------- 事件生成 ----------
    def _sse(self, event, **data):
        return {"event": event, **data}

    # ---------- G3 链路追踪辅助（tracer 不可用时静默空转） ----------
    def _trace_span(self, span_type, name, **meta):
        """手动生命周期 span：返回 (cm, record)；无 tracer 时返回 (None, None)。"""
        if getattr(self, '_tracer', None) is None:
            return None, None
        try:
            cm = self._tracer.span(span_type, name, **meta)
            return cm, cm.__enter__()
        except Exception:
            return None, None

    def _trace_end(self, cm, rec, status='ok', **fields):
        if cm is None:
            return
        try:
            self._tracer.flush_span(rec['span_id'], status=status, **fields)
            cm.__exit__(None, None, None)
        except Exception:
            pass

    # ---------- 主流程 ----------
    def run(self, user_content):
        db.update_task(self.task_id, status="running")
        db.add_message(self.task_id, "user", user_content)
        # D3 跨会话引用（对齐 Harness session-reference）：解析 `@任务N`/`@会话N`
        # 语法，读取目标任务上下文注入当前会话窗口。
        try:
            import re
            _refs = re.findall(r'@(?:任务|会话)?\s*(\d{1,6})', user_content or '')
            _ref_ids = [int(x) for x in dict.fromkeys(_refs) if int(x) != self.task_id][:3]
            if _ref_ids:
                _blocks = []
                from src.gateway import bridge_compat as v2_bridge
                for _rid in _ref_ids:
                    _r = v2_bridge.session_ref(_rid)
                    if _r.get('ok'):
                        _ref = _r['ref']
                        _b = '【引用历史任务 #%s】%s\n  状态:%s | 摘要:%s\n  关键输出:%s' % (
                            _ref['task_id'], _ref['title'] or '(无标题)', _ref['status'],
                            (_ref['summary'] or '(空)')[:200], (_ref['key_output'] or '(空)')[:300])
                        if _ref.get('refs_tail'):
                            _b += '\n  全文引用片段:%s' % _ref['refs_tail'][:300]
                        _blocks.append(_b)
                if _blocks:
                    self._session_refs = _blocks
                    db.add_message(self.task_id, "system",
                                   '已注入跨会话引用：\n' + '\n\n'.join(_blocks)[:1500])
        except Exception:
            pass
        # G4：会话恢复——存在断点（paused=已暂停 / resumed=已点击继续）时注入恢复上下文。
        # 无论用户是先点"恢复"按钮还是直接输入"继续任务"，只要消息开始执行即消费断点。
        self._resume_ctx = None
        try:
            from src.agents.checkpoint import CheckpointManager
            ck = CheckpointManager().get(self.task_id)
            if ck and ck.get('status') in ('paused', 'resumed'):
                self._resume_ctx = ck
                CheckpointManager().resume(self.task_id)  # 置 resumed，标记本次已消费
        except Exception:
            pass
        # G3：链路追踪（JSONL 落盘，失败静默）
        try:
            from src.obs.trace import get_tracer
            self._tracer = get_tracer()
            self._trace_id = self._tracer.begin_trace(
                task_id=self.task_id, title=self.task.get('title', '')[:200])
        except Exception:
            self._tracer = None
            self._trace_id = ''
        try:
            yield from self._loop(user_content)
        except Exception as e:
            yield self._sse("error", message=f"智能体运行异常: {e}")
        finally:
            db.update_task(self.task_id, status="idle")
            self.stop_event.clear()
            STOP_EVENTS.pop(self.task_id, None)
            # G3：结束 trace 落盘
            if self._tracer is not None:
                try:
                    self._tracer.end_trace()
                except Exception:
                    pass
            # G4：断点保留——任务收尾时不主动清除断点。
            # 手动暂停（paused）的断点必须保留，供"继续任务"注入恢复上下文；
            # 若在此处清除会与 /resume 置 resumed 的时序产生竞态（旧 run 收尾时
            # 刚点"恢复"的断点会被误删）。断点的"消费清除"发生在 _loop 注入恢复
            # 上下文之后；"放弃清除"由 /stop 接口负责。
            # 每次任务运行结束, 自动把对话记录导出到任务输出文件夹
            try:
                db.export_task_chat(self.task_id)
            except Exception:
                pass
            # 记忆沉淀异步化：OERCR 学习 / 事实抽取 / 两级摘要全部转后台线程，
            # 避免同步阻塞任务收尾（对标 TencentDB-Agent-Memory 异步记忆管道）
            try:
                tid = self.task_id
                tsk = self.task
                def _post_task_learning():
                    # S3-H1 goal 自动登记（对标 Harness goal）：任务收尾即完成目标
                    try:
                        from src.memory import goals
                        _title = tsk.get('title') if isinstance(tsk, dict) else str(tsk or '')
                        goals.register(tid, _title or f'任务 #{tid}', progress=100,
                                       status='completed')
                    except Exception:
                        pass
                    try:
                        from src.gateway import bridge_compat as v2_bridge
                        v2_bridge.oercr_auto_learn(tsk, tid)
                    except Exception:
                        pass
                    try:
                        from src.gateway import bridge_compat as v2_bridge
                        v2_bridge.facts_extract(tsk, source='agent-task')
                    except Exception:
                        pass
                    # M5：两级摘要（L1 abstract + L2 overview），写入后自动登记资产
                    try:
                        from src.memory import summary
                        summary.save_task_summaries(tid, db.get_messages(tid))
                    except Exception:
                        pass
                    # 短期任务压缩：offload 长工具输出 + 符号画布落盘（对标 TencentDB 上下文卸载）
                    try:
                        from src.memory import offload
                        offload.save_task_canvas(tid, db.get_messages(tid))
                    except Exception:
                        pass
                    # 自动技能沉淀：从任务轨迹生成技能草稿（pending_review，需 R8 审核）
                    try:
                        from src.memory import skillforge
                        skillforge.forge_skill_from_trace(tid, db.get_messages(tid))
                    except Exception:
                        pass
                    # V3 全自动知识沉淀：任务级情景事件自动写入（对标 Mem0 ADD / Harness
                    # episodic memory），无需用户手动记录
                    try:
                        from src.memory import episodic
                        _ev = f'完成任务 #{tid}：{(tsk or "")[:40]}'
                        episodic.EpisodicMemory().add(
                            '任务', _ev,
                            {'task_id': tid, 'title': (tsk or '')[:80],
                             'auto': True, 'source': 'agent_task'})
                    except Exception:
                        pass
                    # V3 画像蒸馏：任务结束后自动从已激活事实聚合稳定偏好/约束到 profile
                    # （对标 Harness profile 子系统 / Mem0 Long-Term Memory 蒸馏）
                    try:
                        from src.memory import profile
                        profile.distill()
                    except Exception:
                        pass
                    # V3 wiki 自动登记：任务摘要沉淀为标准知识条目（可复用方法论/标准知识）
                    try:
                        from src.memory import wiki
                        from src.core.db import get_conn
                        _rows = get_conn().execute(
                            'SELECT abstract, overview FROM task_summaries WHERE task_id=?',
                            (str(tid),)).fetchall()
                        _txt = (_rows[0]['overview'] or _rows[0]['abstract'] or '') if _rows else ''
                        if not _txt:
                            _txt = (tsk or '')[:200]
                        if len(_txt.strip()) > 30:
                            wiki.create_wiki(
                                title=f'任务#{tid}：{(tsk or "")[:40]}',
                                content=_txt[:2000],
                                tags='auto,task-summary', created_by='agent-auto',
                                source=f'task#{tid}')
                    except Exception:
                        pass
                th = threading.Thread(
                    target=_post_task_learning,
                    name=f"post-task-learning-{tid}",
                    daemon=True,
                )
                th.start()
            except Exception:
                pass

    def _load_window(self):
        """从数据库加载最近对话,构建消息列表"""
        msgs = db.get_messages(self.task_id)
        window = []
        for m in msgs:
            if m["role"] == "tool":
                continue
            window.append({"role": m["role"], "content": m["content"] or ""})
        if not window:
            window = []
        return window

    def _should_onboard(self, user_content):
        """P5 新领域引导触发：消息含"发起新领域/新业务/新团队"意图。"""
        t = (user_content or "").strip()
        return any(k in t for k in ("发起新领域", "新领域", "新业务", "新团队", "搭建团队",
                                    "新建团队", "领域引导", "onboard"))

    def _run_domain_onboarding(self, user_content):
        """P5 新领域引导：收集资料 → 建议书 → 用户确认 → 自动搭建新 Team。

        流程（全部在对话内完成，产物 pending 审核）：
        1) 解析领域描述 → 2) recommend 生成建议书（资料不足则追问）
        3) 展示建议书 → 4) confirm 自动搭建（技能草稿+团队 onboarding）
        """
        from src.gateway import bridge_compat as v2_bridge
        yield self._sse("pipeline_stage", stage="collect", label="领域收集",
                        skill="domain-onboarding", desc="识别新领域意图，解析领域描述")
        # 1) 解析领域与描述（消息内提取"领域=xx"或取消息整体）
        import re
        m = re.search(r"领域[=:：]\s*([^\s,，。]+)", user_content)
        domain = m.group(1) if m else "custom"
        desc = user_content.strip()
        for k in ("发起新领域", "新领域", "新业务", "新团队", "搭建团队", "新建团队", "领域引导", "onboard"):
            desc = desc.replace(k, "")
        desc = desc.strip()
        if not desc or len(desc) < 4:
            desc = f"用户发起新领域：{domain}"
        # 2) 建议书
        rec = v2_bridge.domain_onboarding_recommend(domain, desc, materials=[])
        yield self._sse("pipeline_stage", stage="draft", label="能力建议书",
                        skill="domain-onboarding", desc="分析领域资料，生成《能力建议书》")
        if not rec.get("ready"):
            q = "；".join(rec.get("questions") or [])
            text = f"[新领域引导] 请补充更多信息：{q}\n例如：我们要做\"碳普惠\"业务，可参考碳排放核算标准。"
            yield self._sse("tool_start", id="onboard", name="新领域引导", args="资料不足，追问补充")
            yield self._sse("delta", content="\n" + text + "\n")
            yield self._sse("tool_end", id="onboard", name="新领域引导", ok=False, output="资料不足")
            try:
                mid = db.add_message(self.task_id, "assistant", text, meta={"onboard_question": True}, tokens=0)
            except Exception:
                mid = 0
            yield self._sse("assistant_done", message_id=mid)
            yield self._sse("done", task_id=self.task_id)
            return
        sug = rec.get("suggestion", {})
        # 3) 展示建议书
        skills_txt = "\n".join(f"  · {s.get('skill_id')} {s.get('name')}" for s in sug.get("skills", []))
        roles_txt = "\n".join(f"  · {r.get('node_id')} {r.get('label')}" for r in sug.get("roles", []))
        text = (f"[新领域引导] 《能力建议书》——领域：{sug.get('domain')} / {sug.get('name')}\n"
                f"业务范围：{sug.get('business')}\n"
                f"建议技能：\n{skills_txt or '（无）'}\n"
                f"团队节点：\n{roles_txt or '（无）'}\n"
                f"流程模板：{sug.get('wf_template')}\n"
                f"缺口：{'；'.join(sug.get('gaps') or [])}\n"
                f"回复\"确认搭建\"即自动创建团队（技能草稿待 R8 审核）")
        yield self._sse("pipeline_stage", stage="review", label="用户确认",
                        skill="", desc="展示建议书，等待用户确认")
        yield self._sse("tool_start", id="onboard", name="新领域引导", args=f"领域 {domain}")
        yield self._sse("delta", content="\n" + text + "\n")
        yield self._sse("tool_end", id="onboard", name="新领域引导", ok=True, output="建议书已生成，等待确认")
        try:
            mid = db.add_message(self.task_id, "assistant", text,
                                 meta={"onboard_suggestion": sug, "domain": domain}, tokens=0)
        except Exception:
            mid = 0
        # 若消息本身含"确认"，直接搭建
        if "确认" in user_content or "确认搭建" in user_content:
            yield from self._confirm_and_build(sug)
            return
        yield self._sse("assistant_done", message_id=mid)
        yield self._sse("done", task_id=self.task_id)

    def _confirm_and_build(self, sug):
        """确认建议书 → 自动搭建新 Team（复用 confirm API）。"""
        from src.gateway import bridge_compat as v2_bridge
        yield self._sse("pipeline_stage", stage="complete", label="团队搭建",
                        skill="R8", desc="确认建议书，自动创建团队与技能草稿")
        try:
            r = v2_bridge.domain_onboarding_confirm(sug)
            team = r.get("team", {})
            text = (f"[新领域引导] 团队已创建：{team.get('team_id')} {team.get('name')}\n"
                    f"状态：onboarding（技能草稿 {len(r.get('skill_ids') or [])} 个待 R8 审核）\n"
                    f"提示：审核通过后即可承接该领域任务")
            yield self._sse("delta", content="\n" + text + "\n")
            yield self._sse("tool_end", id="onboard", name="新领域引导", ok=True,
                            output=f"团队 {team.get('team_id')} 已创建")
        except Exception as e:  # noqa: BLE001
            yield self._sse("error", message=f"团队搭建失败：{e}")
            return
        try:
            mid = db.add_message(self.task_id, "assistant", text, meta={"team_built": True}, tokens=0)
        except Exception:
            mid = 0
        yield self._sse("assistant_done", message_id=mid)
        yield self._sse("done", task_id=self.task_id)

    def _should_expert_revise(self, user_content):
        """P3 专家意见修改触发：历史或当前消息含"[专家意见]"且未处理过。"""
        try:
            # 防重复：checkpoint 标记已处理
            import json as _json
            cp = db.get_checkpoint(self.task_id)
            ds = ((cp or {}).get("done_steps")) or "[]"
            done = _json.loads(ds) if isinstance(ds, str) else list(ds or [])
            if any("expert_revised" in str(d) for d in done):
                return False
            # 历史消息含专家意见（且非最近一次修改已执行完）
            for m in (db.get_messages(self.task_id) or []):
                if m.get("role") == "user" and "[专家意见]" in (m.get("content") or ""):
                    return True
        except Exception:
            pass
        return "[专家意见]" in (user_content or "")

    def _should_orchestrate(self, user_content):
        """报告任务（标题含"报告"或消息含报告生成意图）触发专家团流水线。"""
        try:
            title = self.task.get("title") or ""
            if "报告" in title:
                return True
            t = (user_content or "").strip()
            if any(k in t for k in ("生成报告", "编制报告", "编写报告", "出具报告", "制作报告",
                                    "监测报告", "验收报告", "环评报告", "报告初稿", "专家意见")):
                return True
        except Exception:
            pass
        return False

    def _run_planning(self, user_content):
        """G1 显式规划器：输出结构化执行计划（plan 模式，不执行）。"""
        import json as _json
        from src.gateway import bridge_compat as v2_bridge
        try:
            out = v2_bridge.plan_run(user_content, self.mode, execute=False)
        except Exception as exc:  # noqa: BLE001
            yield self._sse("error", message=f"规划失败: {exc}")
            return
        steps = out.get('steps') or []
        route = out.get('route') or {}
        lines = [f"[执行计划] 领域 D{route.get('domain') or '-'} | 共 {len(steps)} 步（plan 模式仅规划，不执行）："]
        for st in steps:
            lines.append(f"{st['seq']}. {st['goal']} —— {st['action']}({st['target']})"
                         f"{(' | 产出: ' + st['outputs_name']) if st.get('outputs_name') else ''}")
        lines.append("确认后切换 craft 模式发送任务即可按此计划执行（或在 V2 模块-规划器卡片一键执行）。")
        text = "\n".join(lines)
        yield self._sse("tool_start", id="plan", name="显式规划器（G1）", args=user_content[:100])
        yield self._sse("delta", content="\n" + text + "\n")
        yield self._sse("tool_end", id="plan", name="显式规划器（G1）", ok=True,
                        output=_json.dumps(steps, ensure_ascii=False)[:400])
        try:
            mid = db.add_message(self.task_id, "assistant", text,
                                 meta={"plan": steps}, tokens=0)
        except Exception:
            mid = 0
        yield self._sse("assistant_done", message_id=mid)
        yield self._sse("done", task_id=self.task_id)

    def _run_report_orchestration(self, user_content):
        """专家团报告流水线：P2 资料核对 → R4→R5→R6→R8 多角色协作 + 状态机自动流转。

        资料缺失时不生成"待填写"占位报告，改为对话追问用户补充；
        补充后再次触发重新校验，通过后自动继续流水线。
        消息含"专家意见"时走 P3 专家意见修改分支（按意见修改已有报告并复审）。
        """
        import report_orchestrator as orch
        from src.gateway import bridge_compat as v2_bridge
        import materials_check

        # ---- P5 新领域引导：消息含"发起新领域/新业务/新团队" → 引导流程 ----
        if self._should_onboard(user_content):
            try:
                yield from self._run_domain_onboarding(user_content)
            except Exception as e:  # noqa: BLE001
                yield self._sse("error", message=f"新领域引导失败：{e}")
            return

        # ---- P3 专家意见修改：消息或历史含专家意见 → 按意见修改已有报告并复审 ----
        if self._should_expert_revise(user_content):
            try:
                yield from self._run_expert_revision(user_content)
            except Exception as e:  # noqa: BLE001
                yield self._sse("error", message=f"专家意见修改失败：{e}")
            return
        rtype = orch._infer_type(user_content)
        # 取消意图：解除资料阻塞
        if any(k in user_content for k in ("取消报告", "不要了", "放弃报告", "算了", "先不做了")):
            v2_bridge.materials_clear(self.task_id)
            text = "[资料核对] 已取消当前报告任务。需要时直接发送报告需求即可重新开始。"
            yield self._sse("tool_start", id="materials", name="资料核对", args="cancel")
            yield self._sse("delta", content="\n" + text + "\n")
            try:
                mid = db.add_message(self.task_id, "assistant", text, meta={"materials_cancel": True}, tokens=0)
            except Exception:
                mid = 0
            yield self._sse("assistant_done", message_id=mid)
            yield self._sse("done", task_id=self.task_id)
            return
        # P2 资料核对：缺失则追问，不执行流水线
        check = v2_bridge.materials_check(rtype, user_content, self.task_id)
        yield self._sse("tool_start", id="materials", name="资料核对",
                        args=f"{rtype} 必需{check.get('total', 0)}项，已具备{check.get('have_n', 0)}项")
        if not check.get("complete"):
            text = materials_check.ask_text(check)
            yield self._sse("tool_end", id="materials", name="资料核对", ok=False,
                            output="缺 " + "、".join(m["name"] for m in check.get("missing", [])))
            yield self._sse("delta", content="\n" + text + "\n")
            try:
                mid = db.add_message(self.task_id, "assistant", text,
                                     meta={"materials_missing": [m["key"] for m in check.get("missing", [])]},
                                     tokens=0)
            except Exception:
                mid = 0
            yield self._sse("assistant_done", message_id=mid)
            yield self._sse("done", task_id=self.task_id)
            return
        # 资料齐备：解除阻塞并执行专家团流水线
        v2_bridge.materials_clear(self.task_id)
        yield self._sse("tool_end", id="materials", name="资料核对", ok=True,
                        output=f"资料齐备（{check.get('have_n', 0)}/{check.get('total', 0)}）")
        # P2 对话进度卡：阶段事件流（collect → draft → review → complete → archive）
        yield self._sse("pipeline_stage", stage="collect", label="材料收集",
                        skill="", desc=f"资料核对通过（{check.get('have_n', 0)}/{check.get('total', 0)}），进入起草")
        try:
            res = orch.run(user_content, project_id=f"P-{self.task_id}", task_id=self.task_id,
                           materials=check.get("have", {}),
                           rewriter_caller=self._rewriter_caller())
        except Exception as e:
            yield self._sse("error", message=f"报告流水线执行失败：{e}")
            return
        report = res.get("report", {})
        wf = res.get("workflow", {})
        steps = res.get("steps", [])
        lines = [f"[专家团] {report.get('id', '')}（{report.get('type', '')}，状态机 {wf.get('state', '')}）"]
        yield self._sse("tool_start", id="orchestrator", name="专家团 · 报告流水线", args="R4→R5→R6→R8 多角色协作")
        # 按角色映射阶段：R4=draft，R5/R6=review，R8=archive
        stage_map = {"R4": "draft", "R5": "review", "R6": "review", "R8": "archive"}
        stage_label = {"draft": "报告起草", "review": "审核", "archive": "归档学习"}
        _last_stage = None
        for step in steps:
            role = step.get('role', '?')
            stage = stage_map.get(role, "draft")
            if stage != _last_stage:
                yield self._sse("pipeline_stage", stage=stage, label=stage_label.get(stage, stage),
                                skill=role, desc=f"{role} {step.get('name', '')}")
                _last_stage = stage
            tag = f"{role} {step.get('name', '')}"
            text = orch.step_text(step)
            lines.append(f"[{tag}] {text}")
            yield self._sse("tool_start", id=tag, name=tag, args=step.get("action", ""))
            yield self._sse("tool_end", id=tag, name=tag, ok=True, output=text[:400])
            yield self._sse("delta", content=f"\n[{tag}] {text}\n")
        yield self._sse("tool_end", id="orchestrator", name="专家团 · 报告流水线",
                        ok=True, output=f"状态机 {wf.get('state', '')}")
        # P2/P4 完成阶段：报告自动入报告中心 + 自动学习归档（无签发，完成即归档）
        learn = res.get("learning") or {}
        learn_txt = ""
        if learn:
            learn_txt = f"（已自动归档 {learn.get('archived', 0)} 章节入知识库"
            if learn.get("learned"):
                learn_txt += " · 语料学习完成"
            if learn.get("proposal"):
                learn_txt += " · 已生成技能迭代提案"
            learn_txt += "）"
        yield self._sse("pipeline_stage", stage="complete", label="完成",
                        skill="", desc=f"报告 {report.get('id', '')} 已生成并自动归档报告中心 {learn_txt}")
        yield from self._flush_orch_usage()
        full = "\n".join(lines)
        try:
            mid = db.add_message(self.task_id, "assistant", full,
                                 meta={"tool_trace": [s.get("role") for s in steps], "orchestrated": True},
                                 tokens=0)
        except Exception:
            mid = 0
        yield self._sse("assistant_done", message_id=mid)
        yield self._sse("done", task_id=self.task_id)

    def _run_expert_revision(self, user_content):
        """P3 专家意见修改：解析专家意见 → 按意见修改报告 → R5 复审 → 版本 v+1。

        复用 report_rewrite 重写闭环（规则/LLM 重写 + 计算验证 + 复审），
        意见作为审核问题注入；完成后更新报告版本，pipeline_stage 推送修改进度。
        """
        import re
        from src.gateway import bridge_compat as v2_bridge
        import report_rewrite
        import report_orchestrator as orch
        from src.review.engine import ReviewEngine, ReviewIssue

        # 1) 提取专家意见文本与目标报告 id：优先从历史"[专家意见]"消息解析
        opinion = ""
        report_id = ""
        svc = v2_bridge._report_svc()
        for msg in reversed(db.get_messages(self.task_id) or []):
            if msg.get("role") == "user" and "[专家意见]" in (msg.get("content") or ""):
                m = re.search(r"报告\s*([A-Za-z0-9-]+)", msg.get("content", ""))
                if m:
                    report_id = m.group(1)
                raw = msg.get("content", "")
                opinion = raw.split("[专家意见]")[-1].split("（请针对报告")[0].strip()
                break
        if not opinion:
            m = re.search(r"报告\s*([A-Za-z0-9-]+)", user_content or "")
            if m:
                report_id = m.group(1)
            opinion = (user_content or "").replace("[专家意见]", "").strip()
        report = svc.get(report_id) if report_id else None
        if report is None:
            yield self._sse("error", message="未找到目标报告，请指定报告编号（如：请修改报告 rpt-20260809-001）")
            return
        yield self._sse("pipeline_stage", stage="review", label="审核",
                        skill="R5", desc=f"收到专家意见，正在修改报告 {report_id}（v{report.version}）")
        sections = svc._sections.get(report_id, [])
        content = report_rewrite.join_sections(sections)
        # 3) 专家意见构造为审核问题（P1 级别）→ 重写闭环
        issues = [ReviewIssue(
            severity="P1", description=f"专家意见：{opinion[:120]}",
            suggested_fix=opinion, auto_fixable=True, id="expert-opinion",
            location="全文", type="expert_opinion")]
        def _review_with_issue(t: str):
            eng = ReviewEngine()
            fb = eng.review(t)
            # 追加专家意见问题（重写闭环据此逐轮修改）
            fb.issues = list(fb.issues) + [ReviewIssue(**i) if isinstance(i, dict) else i for i in issues]
            fb.summary = (fb.summary or "") + "；专家意见待处理"
            return fb

        try:
            rewrite = report_rewrite.rewrite_loop(
                sections, _review_with_issue,
                caller=self._rewriter_caller(), max_rounds=3)
        except Exception as e:  # noqa: BLE001
            yield self._sse("error", message=f"专家意见修改失败：{e}")
            return
        new_content = report_rewrite.join_sections(sections)
        # 4) 复审
        from src.review.engine import ReviewEngine as _RE
        fb2 = _RE().review(new_content)
        fb2.issues = list(fb2.issues) + [ReviewIssue(**i) if isinstance(i, dict) else i for i in issues]
        hard = any(i.severity in ("P0", "P1") for i in fb2.issues)
        # 5) 更新报告版本与内容
        try:
            report.version = (report.version or 1) + 1
            report.status = "revised"
            svc._sections[report_id] = sections
        except Exception:  # noqa: BLE001
            pass
        yield self._sse("pipeline_stage", stage="complete", label="完成", skill="",
                        desc=f"专家意见已处理：重写 {rewrite.get('rounds', 0)} 轮，报告 {report_id} 更新至 v{report.version}")
        text = (f"[专家意见修改] 报告 {report_id}（v{report.version}）已按专家意见重写 "
                f"{rewrite.get('rounds', 0)} 轮并复审。\n"
                f"{'通过，无遗留 P0/P1' if not hard else '仍余待处理问题，已标注在报告中。'}\n"
                f"修改说明：{rewrite.get('rewrites', [])[-1] if rewrite.get('rewrites') else '规则重写'}")
        yield self._sse("tool_start", id="expert", name="专家意见修改", args=opinion[:60])
        yield self._sse("delta", content="\n" + text + "\n")
        yield self._sse("tool_end", id="expert", name="专家意见修改", ok=not hard,
                        output=f"报告 {report_id} v{report.version}")
        try:
            mid = db.add_message(self.task_id, "assistant", text,
                                 meta={"expert_revision": report_id, "version": report.version},
                                 tokens=0)
        except Exception:
            mid = 0
        # 标记该专家意见已处理（防重复修改）
        try:
            import json as _json
            cp = db.get_checkpoint(self.task_id) or {}
            ds = cp.get("done_steps") or "[]"
            done = _json.loads(ds) if isinstance(ds, str) else list(ds or [])
            done.append({"expert_revised": report_id, "at": "done"})
            db.save_checkpoint(self.task_id, round_no=cp.get("round") or 0,
                               window_summary="", done_steps=done, status="resumed")
        except Exception as _e:
            import sys as _sys
            print(f"[agent_core] save_checkpoint err: {_e!r}", file=_sys.stderr)
        yield from self._flush_orch_usage()
        yield self._sse("assistant_done", message_id=mid)
        yield self._sse("done", task_id=self.task_id)

    def _rewriter_caller(self):
        """P3 LLM 重写回调：聚合 provider 流式输出；不可用时返回空串（降级规则重写）。"""
        if not hasattr(self, "_orch_usage"):
            self._orch_usage = {"prompt": 0, "completion": 0, "hit": 0, "miss": 0,
                                "cache_creation": 0, "thinking": 0}
        def _call(messages):
            try:
                prov = providers.build_provider(self.provider)
                out = []
                for ch in prov.stream(messages, tools=None, temperature=0.2):
                    d = ch.get("delta", {})
                    if d.get("content"):
                        out.append(d["content"])
                    if ch.get("usage"):
                        u = ch["usage"]
                        for k in self._orch_usage:
                            self._orch_usage[k] += u.get(k, 0)
                return "".join(out)
            except Exception:
                return ""
        return _call

    def _flush_orch_usage(self):
        """报告流水线/专家意见等编排路径：把重写回调累计的 LLM 用量落账并推送 SSE。"""
        agg = getattr(self, "_orch_usage", None)
        if not agg or not any(agg.values()):
            return
        try:
            db.log_usage(
                self.task_id, self.provider.get("id"), self.provider.get("model"),
                agg["prompt"], agg["completion"], agg["hit"], agg["miss"],
                cache_creation=agg.get("cache_creation", 0),
                thinking_tokens=agg.get("thinking", 0),
                mode=self.mode,
                domain=infer_domain(self.task.get("title", "")),
            )
        except Exception as _e:
            import sys as _sys
            print(f"[agent_core] log_usage(orchestration) err: {_e!r}", file=_sys.stderr)
            return
        yield self._sse("usage", **agg)
        self._orch_usage = {"prompt": 0, "completion": 0, "hit": 0, "miss": 0,
                            "cache_creation": 0, "thinking": 0}

    def _should_orchestrate_module(self, user_content):
        """模块创建意图：消息含"开发/创建/搭建/做一套 + 模块/系统/工具"。"""
        try:
            t = (user_content or "").strip()
            if any(k in t for k in ("开发一个", "开发一套", "创建模块", "模块流水线", "搭建一套", "帮我做一个", "做一套")):
                if "模块" in t or "系统" in t or "工具" in t:
                    return True
        except Exception:
            pass
        return False

    def _should_approve_module(self, user_content):
        """R8 审批意图：消息含审批关键词且存在待审蓝图。"""
        try:
            t = (user_content or "").strip()
            if any(k in t for k in ("审批通过", "确认通过", "批准", "R8 审批", "激活模块", "通过审批")):
                from src.gateway import bridge_compat as v2_bridge
                return v2_bridge.pipeline_has_pending()
        except Exception:
            pass
        return False

    def _run_module_orchestration(self, user_content):
        """对话 -> ModuleBlueprint（M15），SSE 输出蓝图摘要，提示 R8 审批。"""
        try:
            from src.gateway import bridge_compat as v2_bridge
            bp = v2_bridge.pipeline_run(user_content)
        except Exception as e:
            yield self._sse("error", message=f"模块流水线执行失败：{e}")
            return
        roles = bp.get("roles") or []
        skills = bp.get("skills") or []
        kb = bp.get("knowledge_base") or []
        yield self._sse("tool_start", id="m15", name="M15 模块流水线", args="对话→ModuleBlueprint")
        yield self._sse("tool_end", id="m15", name="M15 模块流水线", ok=True,
                        output=f"领域 {bp.get('domain')} [{bp.get('status')}] 角色{len(roles)} 技能{len(skills)}")
        roles_str = '、'.join(f"{r.get('id')} {r.get('name')}" for r in roles)
        skills_str = '、'.join(s.get('name', '') for s in skills)
        text = (f"[模块蓝图] 领域 {bp.get('domain', '')}（{bp.get('status', '')}）\n"
                f"角色：{roles_str}\n"
                f"技能：{skills_str}\n"
                f"知识库 {len(kb)} 条 · 合规规则 {len(bp.get('compliance_rules') or [])} 条\n"
                f"回复「审批通过」完成 R8 激活。")
        yield self._sse("delta", content=text)
        try:
            mid = db.add_message(self.task_id, "assistant", text, meta={"module_blueprint": True}, tokens=0)
        except Exception:
            mid = 0
        yield self._sse("assistant_done", message_id=mid)
        yield self._sse("done", task_id=self.task_id)

    def _run_module_approval(self):
        """R8 审批激活蓝图（对话确认）。"""
        ok = False
        try:
            from src.gateway import bridge_compat as v2_bridge
            r = v2_bridge.pipeline_approve()
            ok = bool(r.get("ok"))
            text = (f"[R8 审批] 通过（{r.get('status')}）" if ok
                    else f"[R8 审批] 未通过：{r.get('error')}")
        except Exception as e:
            text = f"[R8 审批] 失败：{e}"
        yield self._sse("tool_start", id="m15a", name="R8 审批", args="blueprint")
        yield self._sse("tool_end", id="m15a", name="R8 审批", ok=ok, output=text[:200])
        yield self._sse("delta", content="\n" + text + "\n")
        try:
            mid = db.add_message(self.task_id, "assistant", text, meta={"m15_approve": True}, tokens=0)
        except Exception:
            mid = 0
        yield self._sse("assistant_done", message_id=mid)
        yield self._sse("done", task_id=self.task_id)

    def _loop(self, user_content):
        sys_prompt = build_system_prompt(self.task, self.mode)
        window = self._load_window()
        # 按当前模型上下文窗口计算预算(如 DS V4 为 1M;Provider 可手动覆盖窗口)
        model_name = self.provider.get("model", "") if isinstance(self.provider, dict) else ""
        ctx_manual = int(self.provider.get("context_length") or 0) if isinstance(self.provider, dict) else 0
        budget = context_mgr.budget_info(
            [{"role": "system", "content": sys_prompt}] + window, model=model_name, context_length=ctx_manual)
        # P7：相似任务自动复用 OERCR 已学技能（best_match，仅 active；仅提示不改变执行）
        try:
            from src.gateway import bridge_compat as v2_bridge
            _oercr_hit = v2_bridge.oercr_reuse(user_content, self.mode)
            if _oercr_hit.get('hit'):
                _h = _oercr_hit['hit']
                yield self._sse("tool_start", id="oercr-reuse", name="OERCR 技能复用",
                                args=_h.get('name', ''))
                yield self._sse("tool_end", id="oercr-reuse", name="OERCR 技能复用", ok=True,
                                output=(_h.get('definition') or '')[:180])
        except Exception:
            pass
        # P8：M03 自动路由 + M07 技能执行链（auto 档直接执行；interactive/manual 输出路由参考供确认）
        try:
            from src.gateway import bridge_compat as v2_bridge
            _auto = v2_bridge.auto_route_execute(user_content, self.mode,
                                                 execute=(self.mode == 'auto'))
            _r = _auto.get('route') or {}
            if _r.get('domain') or _r.get('mode'):
                yield self._sse("tool_start", id="intent-route", name="意图路由（M03）",
                                args=f"D{_r.get('domain') or '-'} | {_r.get('mode')} | conf={_r.get('confidence')}")
                yield self._sse("tool_end", id="intent-route", name="意图路由（M03）", ok=True,
                                output=f"领域 {_r.get('domain') or '未识别'}，模式 {_r.get('mode')}，"
                                       f"置信 {_r.get('confidence')}，技能 "
                                       f"{', '.join(_r.get('skill_ids') or []) or '无'}")
            for res in _auto.get('results') or []:
                _o = res.get('outputs') or {}
                # G3：技能执行 span
                _sk_cm, _sk_rec = self._trace_span('skill', _o.get('name', '技能'),
                                                   skill_id=_o.get('skill_id', ''))
                yield self._sse("tool_start", id=f"skill-{_o.get('skill_id', '')}",
                                name="技能执行（M07）", args=_o.get('name', '技能'))
                yield self._sse("tool_end", id=f"skill-{_o.get('skill_id', '')}",
                                name="技能执行（M07）", ok=res.get('ok'),
                                output=str(_o.get('error') or f"执行完成，步骤 {len(_o.get('steps') or [])} 个")[:180])
                self._trace_end(_sk_cm, _sk_rec, status='ok' if res.get('ok') else 'error')
        except Exception:
            pass
        summary, window = context_mgr.compress_window(window, model=model_name, context_length=ctx_manual)
        messages = [{"role": "system", "content": sys_prompt}]
        if summary:
            messages.append({"role": "system", "content": summary})
        messages.extend(window)
        # G4：恢复上下文注入（用户点击"继续"后，从断点接着干）
        if getattr(self, '_resume_ctx', None):
            try:
                from src.agents.checkpoint import CheckpointManager
                resume_text = CheckpointManager().build_resume_context(self._resume_ctx)
                messages.insert(1, {"role": "system", "content": resume_text})
                # 强执行指令：紧贴当前用户消息，确保模型立即调用工具继续执行，而非复述进度
                _cmd = ('\n\n[继续任务指令] 用户已发出「继续任务」，这是执行命令而非提问：'
                        '请立即继续调用工具，完成断点处尚未完成的任务步骤；'
                        '执行完毕后直接把最终成果输出给用户，不要复述进度、不要询问确认。')
                if messages and messages[-1].get("role") == "user":
                    messages[-1]["content"] = (messages[-1]["content"] or "") + _cmd
                else:
                    messages.append({"role": "system", "content": _cmd})
                self._resume_ctx = None  # 仅注入一次
                # 断点已被本次消息消费：立即清除（对应 finally 不再负责清除，避免竞态）
                CheckpointManager().clear(self.task_id)
            except Exception:
                pass
        # D3 跨会话引用注入（对齐 Harness session-reference）：`@任务N` 已解析，
        # 将引用块作为 system 片段注入到 user 消息之前
        if getattr(self, '_session_refs', None):
            try:
                ref_text = ('以下是用户引用的历史任务上下文，供当前任务参考（不需要主动提及），'
                            '引用任务的关键信息：\n' + '\n\n'.join(self._session_refs))
                messages.insert(1, {"role": "system", "content": ref_text[:2000]})
                self._session_refs = None  # 仅注入一次
            except Exception:
                pass
        # V3 自动记忆召回（对标 Mem0 SEARCH / Harness session-reference）：首轮自动检索
        # 画像/情景/摘要/kb 四源并注入 system，无需用户显式触发 → 全自动知识沉淀·召回侧闭环
        try:
            from src.gateway import bridge_compat as v2_bridge
            _recall = v2_bridge.memory_route_search(user_content or '', top_k=3)
            _srcs = [s for s in _recall.get('sources', []) if s.get('items')]
            if _srcs:
                _parts = []
                for s in _srcs:
                    _items = s['items']
                    if s['source'] == 'profile':
                        _txt = '；'.join(f"{i.get('attr')}={i.get('value')}" for i in _items[:5])
                    elif s['source'] == 'episodic':
                        _txt = '；'.join(f"[{i.get('entity', '')}] {i.get('event', '')[:60]}"
                                         for i in _items[:3])
                    elif s['source'] == 'summary':
                        _txt = '；'.join(f"{i.get('title', '')}: {i.get('abstract', '')[:50]}"
                                         for i in _items[:3])
                    else:  # kb
                        _txt = '；'.join(f"{i.get('title', '')}({i.get('domain', '')})"
                                         for i in _items[:3])
                    _parts.append(f"· {s['desc']}: {_txt}")
                _recall_text = ('以下是系统自动召回的与当前任务相关的历史记忆，供参考（无需主动提及）：\n'
                                + '\n'.join(_parts))
                messages.insert(1, {"role": "system", "content": _recall_text[:1800]})
                yield self._sse("tool_start", id="mem-recall", name="自动记忆召回",
                                args=f"{len(_srcs)} 类记忆源")
                yield self._sse("tool_end", id="mem-recall", name="自动记忆召回", ok=True,
                                output=_recall_text[:180])
        except Exception:
            pass
        yield self._sse("budget", **budget)

        # V2 M15 模块流水线（对话驱动）：模块创建意图 -> 自动生成蓝图；"审批通过" -> R8 激活
        if self._should_approve_module(user_content):
            yield from self._run_module_approval()
            return
        if self._should_orchestrate_module(user_content):
            yield from self._run_module_orchestration(user_content)
            return

        # V2 专家团报告流水线（对话驱动内部实现）：报告任务直接编排多角色，不走通用 LLM 循环。
        # P2 资料缺口检测：报告任务或已处于资料缺失阻塞态（等待用户补充）均进入校验流程
        try:
            from src.gateway import bridge_compat as v2_bridge
            _blocked = v2_bridge.materials_blocked(self.task_id)
        except Exception:
            _blocked = False
        # G1 显式规划器：plan 模式且非资料阻塞 -> 输出结构化执行计划（不执行，等确认后 craft 执行）
        if self.mode == 'plan' and not _blocked:
            try:
                yield from self._run_planning(user_content)
            except Exception:
                pass
            return
        if self._should_orchestrate(user_content) or _blocked:
            # G3：专家团流水线 span
            _orch_cm, _orch_rec = self._trace_span('orchestrate', 'report-pipeline',
                                                   intent=(user_content or '')[:60])
            yield from self._run_report_orchestration(user_content)
            self._trace_end(_orch_cm, _orch_rec)
            return

        provider = providers.build_provider(self.provider)
        tool_schemas = tools.TOOL_SCHEMAS if self.mode != "ask" else []
        usage_total = {"prompt": 0, "completion": 0, "hit": 0, "miss": 0, "cache_creation": 0, "thinking": 0}
        tool_trace = []
        reasoning_parts = []
        _t0 = time.time()

        for round_i in range(8):
            if _stopped(self.task_id):
                yield self._sse("error", message="已由用户手动停止")
                return
            yield self._sse("round", round=round_i + 1)
            # G3：LLM 调用 span（流式结束后补 tokens/成本）
            _llm_cm, _llm_rec = self._trace_span(
                'llm', f'round {round_i + 1}',
                model=self.provider.get('model', '') if isinstance(self.provider, dict) else '')

            assistant_content_parts = []
            calls = []
            last_usage = None
            _live_ts = 0.0
            _live_chars = 0
            # 实时上下文守卫（对齐 TencentDB beforePromptBuild）：每次 LLM 请求前自动压缩
            try:
                from src.memory import offload
                offload.ensure_live_budget(self.task_id, messages,
                                           model=model_name, context_length=ctx_manual)
            except Exception:
                pass
            for chunk in provider.stream(messages, tools=tool_schemas):
                if _stopped(self.task_id):
                    break
                if "error" in chunk:
                    yield self._sse("error", message=chunk["error"])
                    return
                if chunk.get("delta", {}).get("content"):
                    piece = chunk["delta"]["content"]
                    assistant_content_parts.append(piece)
                    _live_chars += len(piece)
                    yield self._sse("delta", content=piece)
                    # 实时 token 预估(节流 0.25s+24字符): 已完成轮次精确值 + 当前轮估算,
                    # 让前端 Token 按钮随流式输出实时增长(live 标记, 最终会被精确值覆盖)
                    now = time.monotonic()
                    if now - _live_ts >= 0.25 and _live_chars >= 24:
                        _live_ts = now
                        _live_chars = 0
                        yield self._sse(
                            "usage", live=True,
                            prompt=usage_total["prompt"] + context_mgr.estimate_messages(messages),
                            completion=usage_total["completion"]
                            + context_mgr.estimate_tokens("".join(assistant_content_parts)),
                            thinking=usage_total["thinking"]
                            + context_mgr.estimate_tokens("".join(reasoning_parts)),
                            hit=usage_total["hit"], miss=usage_total["miss"],
                        )
                if chunk.get("delta", {}).get("reasoning"):
                    reasoning_parts.append(chunk["delta"]["reasoning"])
                    yield self._sse("reasoning", content=chunk["delta"]["reasoning"])
                # DeepSeek 内置 web_search 状态事件(服务端搜索进度)
                wss = chunk.get("delta", {}).get("web_search_status")
                if wss:
                    yield self._sse("web_search_status", status=wss)
                if chunk.get("tool_calls"):
                    calls = chunk["tool_calls"]
                if chunk.get("usage"):
                    last_usage = chunk["usage"]
            if _stopped(self.task_id):
                yield self._sse("error", message="已由用户手动停止")
                return

            # 累计 usage(缓存记账)
            if last_usage:
                for k in usage_total:
                    usage_total[k] += last_usage.get(k, 0)
            # G3：LLM span 收尾（补 tokens/成本）
            self._trace_end(
                _llm_cm, _llm_rec,
                status='ok' if (last_usage or not _llm_rec) else 'no_usage',
                in_tokens=usage_total.get('prompt', 0),
                out_tokens=usage_total.get('completion', 0),
                model=self.provider.get('model', '') if isinstance(self.provider, dict) else '')

            full_content = "".join(assistant_content_parts)
            finish_reason = None
            # 从 chunk 中带出 finish_reason(由 provider 最后一帧给出)
            # 若无工具调用即结束
            if not calls:
                mid = db.add_message(
                    self.task_id, "assistant", full_content,
                    meta={"tool_trace": tool_trace, "reasoning": "".join(reasoning_parts)},
                    tokens=usage_total["completion"],
                )
                yield self._sse("assistant_done", message_id=mid)
                # D1 自动会话标题（对齐 Harness session-title）：首轮回复后自动生成标题
                try:
                    if round_i == 0:
                        from src.gateway import bridge_compat as v2_bridge
                        v2_bridge.auto_title(self.task_id, first_user=user_content,
                                             reply=full_content)
                        # 刷新本进程内标题缓存，后续报告联动判断可用
                        self.task["title"] = (db.get_task(self.task_id) or {}).get("title") or self.task.get("title") or ""
                except Exception:
                    pass
                # V2 报告联动：任务标题含"报告"时，Agent 完成起草 -> 自动启动报告状态机并 submit
                try:
                    if "报告" in (self.task.get("title") or ""):
                        from src.gateway import bridge_compat as v2_bridge
                        v2_bridge.agent_report_submit(self.task_id, self.task.get("title", ""))
                except Exception:
                    pass
                break

            # 有工具调用:先落一条 assistant 消息(含工具轨迹),再执行工具
            meta = {"tool_calls": [{"name": c["name"], "args": c["arguments"]} for c in calls], "tool_trace": tool_trace, "reasoning": "".join(reasoning_parts)}
            mid = db.add_message(self.task_id, "assistant", full_content, meta=meta)
            messages.append({
                "role": "assistant",
                "content": full_content,
                "tool_calls": [{
                    "id": c["id"],
                    "type": "function",
                    "function": {"name": c["name"], "arguments": json.dumps(c.get("arguments") or {}, ensure_ascii=False)},
                } for c in calls],
            })
            for c in calls:
                if _stopped(self.task_id):
                    break
                name = c["name"]
                args = c.get("arguments") or {}
                args_display = json.dumps(args, ensure_ascii=False)[:300]
                yield self._sse("tool_start", id=c.get("id", ""), name=name, args=args_display)
                # G3：工具调用 span
                _t_cm, _t_rec = self._trace_span('tool', name)
                ok, output = tools.execute_tool(name, args, self.task_id)
                self._trace_end(_t_cm, _t_rec, status='ok' if ok else 'error')
                tool_trace.append({"name": name, "ok": ok, "output": output[:400], "args": args_display})
                yield self._sse("tool_end", id=c.get("id", ""), name=name, ok=ok, output=output[:400])
                # 知识库写库工具执行成功后, 推送 kb_changed 事件让前端实时刷新知识库面板
                if ok and name in self.KB_WRITE_TOOLS:
                    yield self._sse("kb_changed", tool=name)
                messages.append({
                    "role": "tool",
                    "content": output[:4000],
                    "tool_call_id": c.get("id", ""),
                })
                db.add_message(self.task_id, "tool", output[:4000], meta={"name": name, "args": args})
                # 实时 offload（对齐 TencentDB afterToolCall）：长工具输出即时卸载
                try:
                    from src.memory import offload
                    offload.ensure_live_budget(self.task_id, messages,
                                               model=model_name, context_length=ctx_manual)
                except Exception:
                    pass
                # 工具输出落盘到任务输出文件夹: 保留完整结果(web_fetch 全文等), 便于后续查阅
                try:
                    _fname = f"outputs/{int(time.time())}_{name}.md"
                    _txt = f"## 工具调用: {name}\n\n参数: {args_display}\n\n结果:\n{output}"
                    db.task_output_save(self.task_id, _fname, _txt[:20000])
                except Exception:
                    pass
            if _stopped(self.task_id):
                yield self._sse("error", message="已由用户手动停止")
                return
            continue

        # 落账
        latency_ms = int((time.time() - _t0) * 1000)
        db.log_usage(
            self.task_id, self.provider.get("id"), self.provider.get("model"),
            usage_total["prompt"], usage_total["completion"], usage_total["hit"], usage_total["miss"],
            cache_creation=usage_total.get("cache_creation", 0),
            thinking_tokens=usage_total.get("thinking", 0),
            latency_ms=latency_ms,
            mode=self.mode,
            domain=infer_domain(self.task.get("title", "")),
        )
        yield self._sse("usage", **usage_total)
        yield self._sse("done", task_id=self.task_id)
