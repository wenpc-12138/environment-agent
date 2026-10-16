# -*- coding: utf-8 -*-
"""v1.2 Flask 界面 -> v2.0 模块桥接层（M16 增量集成方案）。

> DEPRECATED（S2-M5, 2026-08-20）：桥接层已迁入本文件（src/gateway/bridge_compat.py），
> 根 `v2_bridge.py` 转为兼容重导出。前端 /api/v2 全部迁移到 `src/gateway/api` 后本文件删除。


v1.2 主进程与 v2 `src/*` 同进程，此处封装纯 dict 接口供 app.py 路由序列化。
惰性导入 + 模块级单例：不破坏 v1.2 主链路，跨请求保持状态。

报告状态机自动流转（后台驱动）：
- 报告 generate -> 自动 start 工作流 + submit(drafting->review)
- 报告 review   -> 无 P0/P1 自动 approve(review->compliance)，否则 fix(review->auto_fix)
- 报告 compliance -> passed 自动 pass(compliance->signoff)，否则 fail(->review)
- 报告 sign(签发) -> sign(signoff->learn) + done(learn->done)
- Agent 对话完成报告起草（任务标题含"报告"）-> 自动 submit
- workflow/auto -> 演示实例后台自动走完全流程，SSE 实时推送
"""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any

_ROLE_REGISTRY: Any = None
_WF_ENGINE: Any = None
_REPORT_SVC: Any = None

# key(report_id / task-xxx / demo) -> 工作流实例 id；实例 id -> 最近事件
_WF_KEYS: dict[str, str] = {}
_WF_EVENTS: dict[str, dict] = {}


def _registry() -> Any:
    global _ROLE_REGISTRY
    if _ROLE_REGISTRY is None:
        from src.roles.registry import RoleRegistry
        _ROLE_REGISTRY = RoleRegistry()
    return _ROLE_REGISTRY


def _workflow() -> Any:
    global _WF_ENGINE
    if _WF_ENGINE is None:
        from src.workflow.engine import WorkflowEngine
        # S1-W1：生产单例启用 db 持久化（实例落 workflow_instances 表，重启可恢复）
        _WF_ENGINE = WorkflowEngine(storage='db')
    return _WF_ENGINE


def _report_svc() -> Any:
    global _REPORT_SVC
    if _REPORT_SVC is None:
        from src.report.service import ReportService
        _REPORT_SVC = ReportService()
    return _REPORT_SVC


# ---------------- 角色（M08） ----------------
def roles_list() -> list[dict]:
    return [r.model_dump() for r in _registry().list()]


def roles_define(name: str, domain: str = 'D1', responsibilities: list[str] | None = None,
                 permissions: list[str] | None = None) -> dict:
    from src.models.core import RoleBlueprint
    rid = f'RX-{int(time.time() * 1000) % 100000}'
    bp = RoleBlueprint(
        id=rid, name=name or '新角色', domain=domain,
        responsibilities=responsibilities or ['待补充'],
        required_skills=[],
        permissions=permissions or ['read_data'],
        compliance=[], status='pending_r8_review',
    )
    _registry().define(bp)
    return bp.model_dump()


def roles_delete(role_id: str) -> dict:
    """删除角色。R1-R8 内置角色不可删除，返回错误。"""
    if role_id in ('R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8'):
        return {"ok": False, "error": "系统内置角色不可删除"}
    ok = _registry().remove(role_id)
    return {"ok": ok} if ok else {"ok": False, "error": "角色不存在"}


def roles_activate(role_id: str, approved_by: str = 'R8') -> dict:
    ok = _registry().activate(role_id, approved_by)
    r = _registry().get(role_id)
    return {'ok': ok, 'role': r.model_dump() if r else None}


# ---------------- 工作流（M09）+ 报告自动驱动 ----------------
def _wf_transition_key(key: str, event: str) -> dict:
    """按 key（报告 id / 任务 id / 演示名）驱动状态机；不存在则先 start。"""
    eng = _workflow()
    iid = _WF_KEYS.get(key)
    if iid is None:
        iid = eng.start('report_pipeline', {key: key})
        _WF_KEYS[key] = iid
    res = eng.transition(iid, {'type': event})
    st = eng.get_state(iid)
    _WF_EVENTS[iid] = {
        'key': key, 'event': event, 'from': res.from_state, 'to': res.to_state,
        'state': st, 'retry': res.retry_count, 'escalated': res.escalated,
        'ts': datetime.now(UTC).isoformat(),
    }
    return {'key': key, 'instance_id': iid, 'state': st, 'last': _WF_EVENTS[iid]}


def workflow_state(key: str) -> dict:
    iid = _WF_KEYS.get(key)
    if iid is None:
        return {'key': key, 'instance_id': None, 'state': 'idle', 'last': None}
    return {'key': key, 'instance_id': iid, 'state': _workflow().get_state(iid),
            'last': _WF_EVENTS.get(iid)}


def workflow_states() -> dict:
    from src.workflow.engine import BUILTIN_REPORT_SM
    return BUILTIN_REPORT_SM


def workflow_transition(instance_id: str, event: str) -> dict:
    eng = _workflow()
    res = eng.transition(instance_id, {'type': event})
    return {'result': res.model_dump(), 'state': eng.get_state(instance_id)}


def workflow_auto() -> dict:
    """演示实例：启动后后台线程自动走完 approve->pass->sign->done。"""
    key = 'demo'
    if _WF_KEYS.get(key) is not None:
        return workflow_state(key)
    _wf_transition_key(key, 'submit')  # drafting -> review

    def _run() -> None:
        for ev in ('approve', 'pass', 'sign', 'done'):
            time.sleep(1.2)
            try:
                _wf_transition_key(key, ev)
            except Exception:
                pass
    threading.Thread(target=_run, daemon=True).start()
    return workflow_state(key)


# ---------------- 报告（M10/M11/M12 + grounding M03） ----------------
def report_generate(report_type: str, project_id: str = 'P-DEMO') -> dict:
    svc = _report_svc()
    r = svc.generate(report_type, project_id)
    sections = svc._sections.get(r.id, [])
    wf = _wf_transition_key(r.id, 'submit')  # 自动：drafting -> review
    # 状态同步：generate 后自动提交审核，report.status 跟随 workflow
    st = wf.get('state')
    if st and st != r.status and st in _REPORT_STATUS_NAMES:
        try:
            r.status = st  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        svc.save(r)  # 状态同步后落库，重启后仍保持 review
    except Exception:
        pass  # 持久化失败不阻断生成
    return {
        'report': _report_view(r),
        'sections': [s.model_dump() for s in sections],
        'workflow': wf,
    }


def _dump(obj: Any) -> Any:
    """通用序列化：Pydantic model_dump / dataclass asdict / list / 原样。"""
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    if hasattr(obj, '__dataclass_fields__'):
        import dataclasses
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [_dump(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _dump(v) for k, v in obj.items()}
    return obj


def report_review(text: str, report_id: str = '') -> dict:
    from src.review.engine import ReviewEngine
    fb = ReviewEngine().review(text)
    data = fb.model_dump()
    if report_id:
        hard = any(i.get('severity') in ('P0', 'P1') for i in data.get('issues', []))
        data['workflow'] = _wf_transition_key(report_id, 'fix' if hard else 'approve')
    return data


def report_compliance(text: str, report_id: str = '') -> dict:
    from src.compliance.engine import ComplianceEngine
    res = ComplianceEngine().check(report=text)
    data = res.model_dump()
    if report_id:
        data['workflow'] = _wf_transition_key(report_id, 'pass' if res.passed else 'fail')
    return data


def report_sign(report_id: str) -> dict:
    """P4 学习归档：签发（signoff→learn→done）+ 自动归档知识库 + 语料学习 + 技能迭代。"""
    svc = _report_svc()
    r = svc.get(report_id)
    learn = _report_learning_auto(report_id, r)
    sign = _wf_transition_key(report_id, 'sign')  # signoff -> learn
    done = _wf_transition_key(report_id, 'done')  # learn -> done
    return {'sign': sign, 'done': done, 'learn': learn}


def _report_learning_auto(report_id: str, r: Any = None) -> dict:
    """报告归档自动学习：分章节入库知识库 + 语料模式学习 + 技能迭代提案（R8 审核）。"""
    out: dict[str, Any] = {'archived': 0, 'learned': False, 'proposal': None}
    if r is None:
        svc = _report_svc()
        r = svc.get(report_id)
    if r is None:
        return {**out, 'error': '报告不存在'}
    sections = _report_svc()._sections.get(report_id, [])
    if not sections:
        return {**out, 'error': '无章节内容'}
    # 1) 分章节入库知识库（category=领域报告，tag 含报告 id/type）
    import json as _json
    import tools as _tools
    archived = 0
    for sec in sections:
        try:
            title = getattr(sec, 'name', '') or ''
            content = getattr(sec, 'content', '') or ''
            if not title or not content:
                continue
            _tools.kb_save(
                title=f"{r.type}报告-{title}",
                url=f"report://{report_id}/{title}",
                category='standard',
                content=f"（来源：报告 {report_id}，类型 {r.type}，版本 v{r.version}）\n{content}",
                task_id=None,
            )
            archived += 1
        except Exception:
            pass
    out['archived'] = archived
    # 2) 语料模式学习（report_learning）
    try:
        import report_learning
        full = '\n\n'.join(f"## {getattr(s, 'name', '')}\n{getattr(s, 'content', '')}" for s in sections)
        rl = report_learning.learn(str(r.type), full, source=f"report:{report_id}")
        # learn 返回 {report_type, samples, learned_sections, total_sections}
        out['learned'] = bool(rl.get('learned_sections')) or bool(rl.get('samples'))
        out['learning'] = {k: rl.get(k) for k in ('samples', 'learned_sections', 'total_sections')}
    except Exception:
        pass
    # 3) 技能迭代提案（复用 H1 propose_update：对 active 报告技能生成待审提案）
    try:
        from src.learn.engine import OercrEngine
        from src.memory.procedural import ProceduralMemory
        from src.models.core import Reflection
        mem = ProceduralMemory()
        active_skills = mem.list_skills(status='active')
        rep_skills = [s for s in active_skills if 'report' in (s.definition or '').lower()
                      or '报告' in (s.definition or '')]
        eng = OercrEngine()
        for s in rep_skills[:3]:
            ref = Reflection(
                domain=str(r.type), context=f"报告 {report_id} 归档",
                lesson=f"报告 {report_id}（类型 {r.type}）完成评审归档，建议根据该报告实际编制经验优化报告类技能",
                gap='报告编制流程优化', severity='P2', expectation='',
            )
            pid = eng.propose_update(s.id, ref)
            out['proposal'] = {'skill_id': s.id, 'proposal_id': pid}
            break
    except Exception:
        pass
    return out


def report_ground(text: str) -> dict:
    from src.llm.grounding import ground_spans, label_claims
    claims = label_claims(text)
    spans = ground_spans(text)
    return {
        'claims': [_dump(c) for c in claims],
        'spans': [_dump(s) for s in spans],
    }


# ---------------- Agent 联动（任务对话结束 -> 自动生成报告并保存到报告中心） ----------------
def _report_type_from_title(title: str) -> str:
    """从任务标题推断报告类型：验收 / 环评（环境影响）/ 默认监测。"""
    t = title or ''
    if '验收' in t:
        return 'acceptance'
    if '环评' in t or '环境影响' in t:
        return 'eia'
    return 'monitoring'


def agent_report_submit(task_id: int, title: str = '') -> dict | None:
    """任务对话结束自动生成报告并保存到报告中心（知识库沉淀）。

    报告中心不依赖人工"从任务生成"：任务列表对话完成后自动创建 Report 实例
    -> 应用语料学习增强 -> 落库 -> 自动 submit（drafting->review）。
    同任务幂等：已存在报告（含专家团流水线生成）则复用，不重复生成/提交。
    """
    try:
        # 与 report_orchestrator.run 保持一致：project_id = P-{task_id}（无补零）
        project_id = f'P-{task_id}'
        svc = _report_svc()
        # 幂等：兼容 P-121 与 P-0121 两种历史格式
        r = next((x for x in svc._reports.values()
                  if x.project_id == project_id or x.project_id == f'P-{task_id:03d}'), None)
        if r is not None:
            # 已有报告（可能是专家团流水线产物）：不重复生成，也不回退状态
            return {
                'report': _report_view(r),
                'sections': [s.model_dump() for s in svc._sections.get(r.id, [])],
                'workflow': workflow_state(r.id),
            }
        r = svc.generate(_report_type_from_title(title), project_id)
        wf = _wf_transition_key(r.id, 'submit')
        st = wf.get('state')
        if st and st != r.status and st in _REPORT_STATUS_NAMES:
            try:
                r.status = st  # type: ignore[attr-defined]
            except Exception:
                pass
        try:
            svc.save(r)  # 落库：重启后报告中心仍保留自动沉淀的报告
        except Exception:
            pass
        return {
            'report': _report_view(r),
            'sections': [s.model_dump() for s in svc._sections.get(r.id, [])],
            'workflow': wf,
        }
    except Exception:
        return None


def report_learning_stats() -> dict:
    """报告中心知识库面板：语料学习模式（monitoring/acceptance/eia）+ 知识库沉淀统计。"""
    try:
        from src.report.service import ReportService
        return ReportService.learning_stats()
    except Exception:
        return {'patterns': {}, 'kb': {}}


# ================= V2 全模块接入（M13/M15/M14/M05/M07/M03/M04/M10-get） =================
_LEARN: Any = None
_PIPELINE: Any = None
_AUDIT: Any = None
_WM: Any = None
_EPI: Any = None
_INTENT: Any = None
_TOOLS: Any = None
_SKILLEXEC: Any = None
_BLUEPRINT: Any = None
_LAST_OBS: Any = None
_LAST_REFLECTIONS: list[Any] = []
_OERC_COUNTER: list[int] = [0]


def _learn() -> Any:
    global _LEARN
    if _LEARN is None:
        from src.learn.engine import OercrEngine
        _LEARN = OercrEngine()
    return _LEARN


def _pipeline() -> Any:
    global _PIPELINE
    if _PIPELINE is None:
        from src.learn.module_pipeline import ModulePipeline
        _PIPELINE = ModulePipeline()
    return _PIPELINE


def _audit() -> Any:
    global _AUDIT
    if _AUDIT is None:
        from src.security.audit import AuditLogger
        _AUDIT = AuditLogger()
    return _AUDIT


def _wm() -> Any:
    global _WM
    if _WM is None:
        from src.memory.working import WorkingMemory
        _WM = WorkingMemory()
    return _WM


def _epi() -> Any:
    global _EPI
    if _EPI is None:
        from src.memory.episodic import EpisodicMemory
        _EPI = EpisodicMemory()
    return _EPI


def _intent() -> Any:
    global _INTENT
    if _INTENT is None:
        from src.llm.intent import IntentRouter
        _INTENT = IntentRouter()
    return _INTENT


def _tools() -> Any:
    global _TOOLS
    if _TOOLS is None:
        from src.tools.registry import ToolRegistry
        _TOOLS = ToolRegistry(load_v12=True)
    return _TOOLS


def _skill_exec() -> Any:
    global _SKILLEXEC
    if _SKILLEXEC is None:
        from src.skills.executor import SkillExecutor
        _SKILLEXEC = SkillExecutor()
    return _SKILLEXEC


def _procedural() -> Any:
    from src.memory.procedural import ProceduralMemory
    return ProceduralMemory()


# ---------------- M13 OERCR 学习闭环 ----------------
def oercr_observe(task: str, domain: str = '', outcome: str = 'partial', feedback: str = '') -> dict:
    global _LAST_OBS
    _LAST_OBS = _learn().observe({
        'task': task, 'domain': domain, 'outcome': outcome, 'user_feedback': feedback,
    })
    return _LAST_OBS.model_dump()


def oercr_reflect(domain: str = '', gap: str = '', severity: str = 'P2', pattern_hint: str = '') -> dict:
    global _LAST_REFLECTIONS
    from src.models.core import Observation
    obs = _LAST_OBS if _LAST_OBS is not None else Observation(
        obs_id='', task='手动反思', domain=domain, outcome='partial')
    _LAST_REFLECTIONS = _learn().reflect(obs)
    return {'count': len(_LAST_REFLECTIONS),
            'reflections': [r.model_dump() for r in _LAST_REFLECTIONS]}


def oercr_crystallize(level: int = 2, role: str = 'R4', domain: str = '',
                      definition: str = '') -> dict:
    global _LAST_REFLECTIONS
    if not _LAST_REFLECTIONS:
        return {'created': 0, 'skills': [], 'error': '无反思结果，请先 reflect'}
    from src.models.core import SkillDef
    from src.memory.procedural import ProceduralMemory
    mem = ProceduralMemory()
    created = []
    errs = []
    for ref in _LAST_REFLECTIONS:
        key = f"ref-{ref.ref_id or ref.gap}"
        try:
            _OERC_COUNTER[0] = (_OERC_COUNTER[0] + 1) % 900
            skill = SkillDef(
                id=f"sk-oer-{100 + _OERC_COUNTER[0]:03d}",
                name=ref.pattern_hint or ref.gap[:20] or '学习沉淀',
                level=level, role=role,
                domain=ref.domain or domain or 'D1',
                definition=definition or f"# {ref.gap}\npattern: {ref.pattern_hint}",
                status='pending_review', created_by='agent_oercr',
            )
            mem.create_skill(skill)
            created.append(skill.model_dump())
        except Exception as e:  # noqa: BLE001
            errs.append(str(e))
    _LAST_REFLECTIONS = []
    return {'created': len(created), 'skills': created, 'errors': errs}


def oercr_pending() -> dict:
    return {'skills': [s.model_dump() for s in _procedural().list_skills('pending_review')]}


def oercr_approve_all() -> dict:
    skills = _learn().approve_pending('R8')
    return {'activated': [s.model_dump() for s in skills]}


def oercr_reuse(task: str, domain: str = '') -> dict:
    s = _learn().reuse(task, domain or None)
    return {'hit': s.model_dump() if s else None}


# ---------------- P8 M03 自动路由 + M07 技能执行链 ----------------
def auto_route_execute(text: str, mode_hint: str = '', execute: bool = True) -> dict:
    """P8：意图路由（M03）→ 技能执行链（M07）。

    - 路由：IntentRouter.analyze -> {domain, mode, confidence, skill_ids}
    - 补充：skill_ids 为空时 best_match 自动匹配 active 技能（M05）
    - 执行：mode=='auto' 且 execute 时 SkillExecutor.run_dag 串行（硬闸门把关，
      pending/rejected/deprecated 拒绝执行），结果按 ok 聚合
    - 返回 {route, results, executed}
    """
    from src.llm.intent import IntentRouter
    route = IntentRouter().analyze(text, {'mode_hint': mode_hint} if mode_hint else None)
    if not route.skill_ids:
        try:
            s = _learn()._memory.best_match(text, route.domain or None)
            if s is not None:
                route.skill_ids = [s.id]
        except Exception:  # noqa: BLE001
            pass
    results = []
    executed = False
    if execute and route.mode == 'auto' and route.skill_ids:
        try:
            from src.skills.executor import SkillExecutor
            rs = SkillExecutor().run_dag(route.skill_ids,
                                         {'domain': route.domain, 'task': text})
            results = [r.model_dump() for r in rs]
            executed = any(r.get('ok') for r in results)
        except Exception as e:  # noqa: BLE001
            results = [{'ok': False, 'outputs': {'error': str(e)}}]
    return {'route': route.model_dump(), 'results': results, 'executed': executed}


# ---------------- P7 OERCR 自动学习闭环 ----------------
_AUTO_ENGINE: Any = None


def _auto_engine():
    """自动学习专用 OercrEngine 单例（与手动接口 _learn() 分离，防循环去重共享）。"""
    global _AUTO_ENGINE
    if _AUTO_ENGINE is None:
        from src.learn.engine import OercrEngine
        _AUTO_ENGINE = OercrEngine()
    return _AUTO_ENGINE


def oercr_auto_learn(task: str = '', task_id=None, outcome: str = 'success',
                     feedback: str = '') -> dict:
    """P7：任务结束自动学习闭环——observe → reflect → 高置信自动 crystallize（pending_review，R8 审批）。

    outcome 默认 success（无负面反馈时仅高置信模式沉淀，低噪音防打扰）；
    有负面反馈传 'failed'/'partial' 触发 P0/P1 首要差距结晶。
    """
    try:
        engine = _auto_engine()
        obs = engine.observe({
            'episode_id': str(task_id) if task_id else '',
            'task': task or '通用任务', 'domain': '',
            'outcome': outcome, 'user_feedback': feedback or '',
        })
        refls = engine.reflect(obs, {'threshold': 0.7})
        skills = engine.crystallize(refls)
        # H1：返回同 gap 迭代提案数（_last_proposals 由 crystallize 写入）
        proposals = getattr(engine, '_last_proposals', []) or []
        return {'observed': obs.obs_id, 'reflections': len(refls),
                'crystallized': [s.id for s in skills],
                'proposals': len(proposals)}
    except Exception as e:  # noqa: BLE001
        return {'error': str(e)}


def oercr_learn_from_review(issues) -> dict:
    """P7：审核反馈自动沉淀——Learner 从审核问题提取高置信（P0/P1）模式结晶 pending_review。"""
    try:
        engine = _auto_engine()
        # learn_from_review 接收 ReviewFeedback/dict 包装；issue 列表需包成 dict
        patterns = engine._learner.learn_from_review(
            [{'issues': list(issues) if issues else [], 'domain': '',
              'summary': '自动审核反馈沉淀'}] if issues else [])
        from src.models.core import Reflection
        refls = []
        for p in patterns:
            if p.confidence >= 0.7:
                refls.append(Reflection(
                    ref_id=f"rev-{len(refls) + 1}", obs_id='review', domain=p.domain or '',
                    gap=p.rule or '审核问题', pattern_hint=p.rule,
                    severity='P2', confidence=p.confidence))
        skills = engine.crystallize(refls)
        return {'patterns': len(patterns), 'crystallized': [s.id for s in skills]}
    except Exception as e:  # noqa: BLE001
        return {'error': str(e)}


def skills2_list(status: str = '') -> dict:
    return {'skills': [s.model_dump() for s in _procedural().list_skills(status or None)]}


def skills2_approve(sid: str) -> dict:
    return {'ok': _procedural().approve_skill(sid, 'R8')}


def skills2_reject(sid: str) -> dict:
    return {'ok': _procedural().reject_skill(sid, 'R8')}


# ---------------- M15 模块流水线 ----------------
def pipeline_run(conversation: Any) -> dict:
    global _BLUEPRINT
    conv = conversation if isinstance(conversation, list) else \
        [{'role': 'user', 'content': str(conversation)}]
    bp = _pipeline().run(conv, [])
    _BLUEPRINT = bp
    return bp.model_dump()


def pipeline_approve() -> dict:
    global _BLUEPRINT
    if _BLUEPRINT is None:
        return {'ok': False, 'error': '无待审蓝图，请先 run'}
    ok = _pipeline().approve_blueprint(_BLUEPRINT, 'R8')
    return {'ok': ok, 'status': _BLUEPRINT.status}


def pipeline_has_pending() -> bool:
    return _BLUEPRINT is not None and _BLUEPRINT.status == 'pending_r8_review'


# ---------------- P9 统一待审核中心（唯一人工闸门） ----------------
def pending_review_list(status: str = '', type_filter: str = '') -> dict:
    """合并待审核项：事实审批 + pending_review 技能 + pending_r8_review 模块蓝图 + 技能迭代提案。

    统一收口：记忆中心事实审批、技能市场结晶待审全部移入审核中心。
    """
    items: list[dict] = []
    # 1) 事实审批（原记忆中心 facts tab 审批队列）
    try:
        fp = facts_pending()
        for f in (fp.get('facts') or []):
            items.append({
                'type': 'fact', 'id': str(f.get('id', '')),
                'name': f"{f.get('entity', '')} {f.get('attr', '→')} {f.get('value', '')}",
                'status': 'pending_review', 'created_by': f.get('source', 'memory'),
                'domain': f.get('entity', '') or f.get('ftype', ''),
                'summary': f"事实审批：{f.get('entity', '')} {f.get('attr', '→')} {f.get('value', '')}",
            })
    except Exception:  # noqa: BLE001
        pass
    # 2) OERCR 技能结晶待审
    for s in _procedural().list_skills('pending_review'):
        items.append({
            'type': 'skill', 'id': s.id, 'name': s.name, 'status': s.status,
            'created_by': s.created_by, 'domain': s.domain,
            'summary': (s.definition or '')[:80],
        })
    if _BLUEPRINT is not None and _BLUEPRINT.status == 'pending_r8_review':
        items.append({
            'type': 'blueprint', 'id': 'blueprint',
            'name': f"模块蓝图（领域 {_BLUEPRINT.domain}）",
            'status': 'pending_r8_review', 'created_by': 'agent_pipeline',
            'domain': _BLUEPRINT.domain,
            'summary': (f"角色 {len(_BLUEPRINT.roles)} · 技能 {len(_BLUEPRINT.skills)} · "
                        f"知识库 {len(_BLUEPRINT.knowledge_base)} 条"),
        })
    # H1：技能迭代提案（同 gap 已存在技能时的升级建议）
    try:
        for p in _auto_engine().pending_updates():
            items.append({
                'type': 'skill_update', 'id': str(p['id']), 'name': f"技能迭代：{p['skill_id']}",
                'status': 'pending_review', 'created_by': 'agent_oercr',
                'domain': '', 'summary': (f"建议升级 {p['base_version']} → 下一版本："
                                          f"{p['reason']}"),
            })
    except Exception:  # noqa: BLE001
        pass
    if status:
        items = [i for i in items if i['status'] == status]
    if type_filter:
        items = [i for i in items if i['type'] == type_filter]
    return {'items': items, 'count': len(items)}


def pending_review_approve(item_type: str = '', item_id: str = '') -> dict:
    """批准：fact → approve_fact；skill → approve_skill（R8）；blueprint → approve_blueprint（R8）。"""
    if item_type == 'fact':
        try:
            from src.memory import facts
            f = facts.approve_fact(int(item_id), 'R8')
            return {'ok': bool(f), 'type': 'fact'}
        except Exception as e:  # noqa: BLE001
            return {'ok': False, 'error': str(e)}
    if item_type == 'skill':
        if not item_id:
            return {'ok': False, 'error': '缺少技能 ID'}
        return {'ok': bool(_procedural().approve_skill(item_id, 'R8')), 'type': 'skill'}
    if item_type == 'blueprint':
        if _BLUEPRINT is None or _BLUEPRINT.status != 'pending_r8_review':
            return {'ok': False, 'error': '无待审蓝图'}
        return {'ok': bool(_pipeline().approve_blueprint(_BLUEPRINT, 'R8')), 'type': 'blueprint'}
    if item_type == 'skill_update':
        return {'ok': skills_update_approve(item_id), 'type': 'skill_update'}
    return {'ok': False, 'error': '未知类型'}


def pending_review_reject(item_type: str = '', item_id: str = '') -> dict:
    """拒绝：fact → reject_fact；skill → reject_skill（R8）；blueprint → 丢弃蓝图。"""
    if item_type == 'fact':
        try:
            from src.memory import facts
            f = facts.reject_fact(int(item_id), 'R8')
            return {'ok': bool(f), 'type': 'fact'}
        except Exception as e:  # noqa: BLE001
            return {'ok': False, 'error': str(e)}
    if item_type == 'skill':
        if not item_id:
            return {'ok': False, 'error': '缺少技能 ID'}
        return {'ok': bool(_procedural().reject_skill(item_id, 'R8')), 'type': 'skill'}
    if item_type == 'blueprint':
        global _BLUEPRINT
        _BLUEPRINT = None
        return {'ok': True, 'type': 'blueprint'}
    if item_type == 'skill_update':
        return {'ok': skills_update_reject(item_id), 'type': 'skill_update'}
    return {'ok': False, 'error': '未知类型'}


def pending_review_approve_all() -> dict:
    """一键批量批准：待审蓝图（先，含其技能）+ 其余 OERCR 待审技能（后，仅 R8）。

    顺序关键：approve_pending 会激活全部 pending 技能（含蓝图技能），
    若先跑会把蓝图技能提前激活导致 approve_blueprint 找不到 pending 而失败。
    """
    bp_ok = False
    if _BLUEPRINT is not None and _BLUEPRINT.status == 'pending_r8_review':
        try:
            bp_ok = bool(_pipeline().approve_blueprint(_BLUEPRINT, 'R8'))
        except Exception:  # noqa: BLE001
            bp_ok = False
    try:
        skills = _learn().approve_pending('R8')
    except Exception:  # noqa: BLE001
        skills = []
    return {'skills': len(skills), 'blueprint': bp_ok}


# ---------------- H1 技能迭代提案（对齐 Hermes 自进化闭环） ----------------
def skills_update_pending() -> dict:
    """待审技能迭代提案。"""
    from src.learn.engine import OercrEngine
    props = OercrEngine().pending_updates()
    return {'proposals': props, 'count': len(props)}


def skills_update_approve(pid: int) -> dict:
    """R8 审批迭代提案：技能版本递增（v+patch）。"""
    from src.learn.engine import OercrEngine
    return {'ok': OercrEngine().approve_update(int(pid), 'R8')}


def skills_update_reject(pid: int) -> dict:
    from src.learn.engine import OercrEngine
    return {'ok': OercrEngine().reject_update(int(pid), 'R8')}


# ---------------- H2 自然语言定时任务（对齐 Hermes 内置调度器） ----------------
def schedule_list() -> dict:
    """定时任务列表（enabled_only=1 仅启用项）。"""
    from src.scheduler import ScheduleManager
    rows = ScheduleManager().list()
    return {'schedules': rows, 'count': len(rows)}


def schedule_parse(text: str) -> dict:
    """自然语言 -> cron_desc 预览（不落库）。"""
    from src.scheduler import parse_nl
    ok, desc, human = parse_nl(text or '')
    return {'ok': ok, 'cron_desc': desc, 'human': human, 'error': '' if ok else human}


def schedule_add(title: str, prompt: str = '', mode: str = 'craft') -> dict:
    from src.scheduler import ScheduleManager
    return ScheduleManager().add(title or '', '', prompt or '', mode or 'craft')


def schedule_pause(sid: int) -> dict:
    from src.scheduler import ScheduleManager
    return ScheduleManager().pause(int(sid))


def schedule_resume(sid: int) -> dict:
    from src.scheduler import ScheduleManager
    return ScheduleManager().resume(int(sid))


def schedule_remove(sid: int) -> dict:
    from src.scheduler import ScheduleManager
    return ScheduleManager().remove(int(sid))


# ---- H3 Cron 记忆（对齐 Hermes cron memory） ----
def schedule_notepad(sid: int, text: str = '') -> dict:
    """读（text 空）或写（text 非空）job 级草稿本。"""
    from src.scheduler import ScheduleManager
    mgr = ScheduleManager()
    if (text or '').strip():
        return mgr.set_notepad(int(sid), text)
    return mgr.get_notepad(int(sid))


def schedule_continuity(sid: int, on: bool) -> dict:
    """开启/关闭 continuity（上次运行摘要注入下次）。"""
    from src.scheduler import ScheduleManager
    return ScheduleManager().set_continuity(int(sid), bool(on))


def schedule_tick() -> dict:
    """手动触发一次到期扫描（测试/运维用）。"""
    from src.scheduler import ScheduleManager
    fired = ScheduleManager().tick()
    return {'fired': fired, 'count': len(fired)}


# ---------------- G4 会话断点续传（Checkpoint） ----------------
def checkpoint_save(task_id: int, round_no: int = 0, window_summary: str = '',
                    done_steps: list | None = None, partial_outputs: dict | None = None) -> dict:
    """暂停任务：落断点（round/窗口摘要/已完成步骤/中间产物）。"""
    from src.agents.checkpoint import CheckpointManager
    return CheckpointManager().save(int(task_id), int(round_no), window_summary or '',
                                    done_steps, partial_outputs)


def checkpoint_peek(task_id: int) -> dict | None:
    """读取任务断点（无则 None）。"""
    from src.agents.checkpoint import CheckpointManager
    return CheckpointManager().get(int(task_id))


def checkpoint_resume(task_id: int) -> dict | None:
    """继续任务：断点置 resumed（run() 入口据此注入恢复上下文）。"""
    from src.agents.checkpoint import CheckpointManager
    return CheckpointManager().resume(int(task_id))


def checkpoint_clear(task_id: int) -> dict:
    from src.agents.checkpoint import CheckpointManager
    return CheckpointManager().clear(int(task_id))


# ---------------- G3 LLM 链路追踪（Trace） ----------------
def trace_query(trace_id: str, days: int = 7) -> dict:
    """按 trace_id 还原 span 树。"""
    from src.obs.trace import query_trace
    hit = query_trace(trace_id or '', int(days))
    return hit or {'trace': None, 'spans': [], 'roots': [], 'count': 0}


def trace_task(task_id: int, days: int = 7) -> dict:
    """按任务查全部 trace 摘要。"""
    from src.obs.trace import query_task
    return {'traces': query_task(int(task_id), int(days))}


def trace_aggregate(days: int = 7, span_type: str = '') -> dict:
    """聚合统计：span 数 / 耗时 / 成本 / 类型分布 / 慢调用 Top。"""
    from src.obs.trace import aggregate
    return aggregate(int(days), span_type or '')


# ---------------- G1 显式规划器（Plan-Execute） ----------------
def plan_run(text: str, mode_hint: str = 'interactive', execute: bool = False) -> dict:
    """规划任务：意图路由 -> 步骤列表 -> 可选执行。

    - execute=False：只返回计划（plan 模式语义，不执行）。
    - execute=True：interactive/craft 手动执行计划（tool/skill/llm 逐布）。
    """
    from src.llm.planner import PlanAgent
    from src.llm.intent import IntentRouter
    route = IntentRouter().analyze(text or '', {'mode_hint': mode_hint})
    steps = PlanAgent().plan(text or '', route.domain, mode_hint)
    out: dict = {'ok': bool(steps), 'route': route.model_dump(),
                 'steps': [s.model_dump() for s in steps]}
    if execute and steps:
        exec_out = PlanAgent().execute_plan(steps, text or '')
        out.update(exec_out)
    return out


def plan_execute(steps: list[dict] | None, text: str = '', continue_on_error: bool = False) -> dict:
    """直接执行给定计划步骤（供前端"一键执行"复用）。"""
    from src.llm.planner import PlanAgent
    from src.models.core import PlanStep
    step_objs = [PlanStep(**s) for s in (steps or [])]
    return PlanAgent().execute_plan(step_objs, text or '',
                                    continue_on_error=bool(continue_on_error))


# ---------------- DeepSeek Harness 对标补缺 ----------------
# D1 session-title：自动会话标题；D2 feedback：逐消息反馈；D3 session-reference：跨会话引用

def auto_title(task_id: int, first_user: str = '', reply: str = '') -> dict:
    """D1 自动会话标题（对齐 Harness session-title）。

    任务首轮 LLM 回复完成后调用：若任务标题仍为默认"新任务"，
    用「首条用户消息 + 首轮回复」生成简洁标题（≤14 字）。
    LLM 失败时回退截取用户消息前 14 字。
    返回 {'ok', 'title', 'generated'}；标题未变时 generated=False。
    """
    try:
        from src.core import db_v12 as db
        t = db.get_task(int(task_id))
        if not t:
            return {'ok': False, 'error': '任务不存在'}
        cur = (t.get('title') or '').strip()
        # 用户已自定义标题则不动
        if cur and cur != '新任务':
            return {'ok': True, 'title': cur, 'generated': False}
        source = (first_user or '').strip()
        title = ''
        # 优先 LLM 生成（非流式，失败静默回退）
        try:
            from ..llm import providers
            prov = db.get_active_provider()
            if prov:
                sys = ('你是标题生成器。根据用户任务和已完成的回复，用中文生成 8-14 字以内的简洁任务标题'
                       '（不含引号、标点、"报告"等冗余词）。只输出标题本身。')
                usr = '用户任务：%s\n\nAgent 回复开头：%s' % (source[:300], (reply or '')[:300])
                txt, _usage = providers.chat_text(prov, [
                    {'role': 'system', 'content': sys},
                    {'role': 'user', 'content': usr},
                ], temperature=0.2, timeout=30)
                title = (txt or '').strip().strip('"\'“”').strip()
                # 过长则截断
                if len(title) > 14:
                    title = title[:14]
        except Exception:
            title = ''
        if not title:
            # 回退：首条用户消息前 14 字
            title = source[:14]
        if not title:
            return {'ok': False, 'error': '无可生成标题的输入'}
        db.update_task(int(task_id), title=title)
        return {'ok': True, 'title': title, 'generated': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def session_ref(task_id: int, top: int = 3) -> dict:
    """D3 跨会话引用（对齐 Harness session-reference）。

    读取目标任务标题/摘要/关键输出，供当前会话 `@任务N` 语法注入。
    返回 {'ok', 'ref': {task_id, title, status, summary, key_output, ts}}。
    """
    try:
        from src.core import db_v12 as db
        t = db.get_task(int(task_id))
        if not t:
            return {'ok': False, 'error': '任务不存在'}
        msgs = db.get_messages(int(task_id)) or []
        user_msgs = [m for m in msgs if m.get('role') == 'user']
        asst_msgs = [m for m in msgs if m.get('role') == 'assistant' and (m.get('content') or '').strip()]
        summary = ''
        key_output = ''
        # 摘要：首条 user + 最新 assistant 开头
        if user_msgs:
            summary = (user_msgs[0].get('content') or '')[:300]
        if asst_msgs:
            key_output = (asst_msgs[-1].get('content') or '')[:600]
        meta_extra = ''
        # 尝试读取任务输出目录中的关键文件（offload 全文引用）
        try:
            from pathlib import Path

            # 读取任务输出模块持有的目录常量（尊重配置，不硬编码 data/task_outputs）
            from src.core.db_v12 import tasks as _tasks

            outdir = Path(_tasks.TASK_OUTPUT_DIR) / str(task_id)
            refs = sorted(outdir.glob('refs/*.md')) if outdir.exists() else []
            if refs:
                meta_extra = (refs[-1].read_text(encoding='utf-8', errors='ignore') or '')[:500]
        except Exception:
            meta_extra = ''
        return {
            'ok': True,
            'ref': {
                'task_id': int(task_id),
                'title': (t.get('title') or ''),
                'status': (t.get('status') or ''),
                'mode': (t.get('mode') or ''),
                'summary': summary,
                'key_output': key_output,
                'refs_tail': meta_extra,
            },
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def message_feedback(message_id: int, value: str = '', comment: str = '') -> dict:
    """D2 逐消息反馈（对齐 Harness feedback）。

    对单条消息记录 有用(good)/无用(bad) + 理由，写入 messages.meta.feedback；
    写入待审队列（bad 进入 R8 复核），返回 {'ok', 'message_id'}。
    """
    try:
        import json
        from src.core import db_v12 as db
        value = (value or '').strip().lower()
        if value not in ('good', 'bad', ''):
            return {'ok': False, 'error': 'value 仅支持 good/bad/空'}
        row = db.q("SELECT * FROM messages WHERE id=?", (int(message_id),), one=True)
        if not row:
            return {'ok': False, 'error': '消息不存在'}
        meta = row.get('meta') or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta or '{}')
            except Exception:
                meta = {}
        meta['feedback'] = value
        meta['feedback_ts'] = __import__('time').strftime('%Y-%m-%d %H:%M:%S')
        if comment:
            meta['feedback_comment'] = str(comment)[:500]
        db.w("UPDATE messages SET meta=? WHERE id=?",
             (json.dumps(meta, ensure_ascii=False), int(message_id)))
        return {'ok': True, 'message_id': int(message_id), 'feedback': value}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def feedback_list(task_id: int = 0, limit: int = 50) -> dict:
    """D2 反馈查询：列出带反馈的消息（可按任务过滤），供前端统计/复核。"""
    try:
        import json
        from src.core import db_v12 as db
        sql = "SELECT id, task_id, role, substr(content,1,200) AS content, meta, created_at FROM messages WHERE meta LIKE '%feedback%'"
        args = ()
        if task_id:
            sql += " AND task_id=?"
            args = (int(task_id),)
        sql += " ORDER BY id DESC LIMIT ?"
        rows = db.q(sql, args + (int(limit),)) or []
        out = []
        for r in rows:
            meta = r.get('meta') or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta or '{}')
                except Exception:
                    meta = {}
            if 'feedback' not in meta:
                continue
            out.append({
                'id': r.get('id'),
                'task_id': r.get('task_id'),
                'role': r.get('role'),
                'content': r.get('content'),
                'feedback': meta.get('feedback'),
                'comment': meta.get('feedback_comment', ''),
                'ts': meta.get('feedback_ts', ''),
            })
        return {'ok': True, 'items': out, 'total': len(out)}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ---------------- G5 记忆知识图谱（对齐 Neo4j Agent Memory） ----------------
def memory_graph_query(entity: str, top_k: int = 10) -> dict:
    """实体图谱展开：关系/决策痕迹/事实/知识库/画像/技能。"""
    from src.memory import graph
    return graph.query(entity or '', int(top_k))


def memory_graph_add(entity_a: str, rel: str, entity_b: str,
                     source: str = '', note: str = '') -> dict:
    from src.memory import graph
    return graph.add_relation(entity_a or '', rel or 'related', entity_b or '',
                              source or '', note or '')


def memory_graph_extract(text: str) -> dict:
    """抽取文本中的实体。"""
    from src.memory import graph
    return {'entities': graph.extract_entities(text or '')}


def memory_graph_link_facts() -> dict:
    """从 memory_facts 自动建图。"""
    from src.memory import graph
    n = graph.link_from_facts()
    return {'linked': n}


def memory_graph_neighbors(entity: str, depth: int = 1) -> dict:
    from src.memory import graph
    return graph.neighbors(entity or '', int(depth))


# ---------------- G2 动态子代理（SubAgent as Tool） ----------------
def subagent_spawn(task: str, role_id: str = 'R4', name: str = 'subagent') -> dict:
    """派生子代理（后台执行）；返回 sub_id。"""
    from src.agents.subagent import SubAgentRunner, SubAgentSpec, get_runner
    spec = SubAgentSpec(name=name or 'subagent', role_id=(role_id or 'R4').upper())
    sub_id = get_runner().spawn(spec, task or '')
    return {'ok': True, 'sub_id': sub_id, 'name': spec.name, 'role': spec.role_id}


def subagent_collect(sub_id: str, timeout: float = 60.0) -> dict:
    """回收子代理结果。"""
    from src.agents.subagent import get_runner
    r = get_runner().collect(sub_id or '', float(timeout))
    if not r:
        return {'ok': False, 'error': f'子代理不存在: {sub_id}'}
    res = r.get('result') or {}
    return {'ok': True, 'id': sub_id, 'status': r.get('status'),
            'result': res.get('result', ''), 'role': res.get('role'),
            'tool_calls': res.get('tool_calls', 0), 'errors': res.get('errors', 0),
            'steps': res.get('steps', [])}


def subagent_list() -> dict:
    from src.agents.subagent import get_runner
    return {'subagents': get_runner().list()}


# ---- H4 子代理实时操控（对齐 Hermes subagent steering） ----
def subagent_running() -> dict:
    """运行中子代理状态快照（state/round/partial 预览）。"""
    from src.agents.subagent import get_runner
    return {'running': get_runner().running()}


def subagent_steer(sub_id: str, instruction: str) -> dict:
    """向运行中子代理追加纠偏指令（下一轮生效）。"""
    from src.agents.subagent import get_runner
    return get_runner().steer(sub_id, instruction or '')


def subagent_stop(sub_id: str) -> dict:
    """停止运行中子代理，保留部分结果（collect 可回收）。"""
    from src.agents.subagent import get_runner
    return get_runner().stop_partial(sub_id)


def subagent_run_parallel(tasks: list[str], role_id: str = 'R4',
                          timeout: float = 60.0) -> dict:
    """多子代理并行执行（报告章节并行起草）。"""
    from src.agents.subagent import SubAgentRunner, SubAgentSpec, get_runner
    specs = [SubAgentSpec(name=f'{role_id}-{i + 1}', role_id=(role_id or 'R4').upper())
             for i in range(len(tasks or []))]
    results = get_runner().run_parallel(specs, tasks or [], timeout=float(timeout))
    return {'results': [
        {'status': r.get('status') if r else 'missing',
         'ok': (r.get('result') or {}).get('ok') if r else False,
         'result': ((r.get('result') or {}).get('result') or '')[:800] if r else ''}
        for r in results]}


# ---------------- G7 MCP 双向（EA 作为 MCP server） ----------------
def mcp_handle(body: dict) -> dict:
    """JSON-RPC 请求分发（initialize/tools/list/tools/call）。"""
    from src.gateway.mcp_server import handle_jsonrpc
    return handle_jsonrpc(body or {})


def mcp_tools() -> dict:
    """EA 暴露的 MCP 工具清单。"""
    from src.gateway.mcp_server import tools_list
    return tools_list()


# ---------------- G6 多模态输入（图片视觉理解） ----------------
def vision_analyze(path: str, question: str = '') -> dict:
    """图片视觉理解：VLM 直读（带问题）优先，RapidOCR 文字提取兜底。"""
    from src.vision.analyze import analyze_image
    return analyze_image(path or '', question or '')


def vision_supported() -> dict:
    """当前 Provider 是否支持多模态视觉。"""
    try:
        import vlm_convert
        return {'supported': bool(vlm_convert.supports_vlm())}
    except Exception:
        return {'supported': False}


# ---------------- G8 技能打包/市场 ----------------
def market_list(status: str = '', source: str = '') -> dict:
    """技能目录（v2 + file 双源，附关联公式/标准引用）。"""
    from src.skills.market import list_market
    return list_market(status or '', source or '')


def market_browse(key: str) -> dict:
    from src.skills.market import browse_skill
    return browse_skill(key or '')


def market_export(key: str, include_related: bool = True) -> dict:
    """技能 -> zip（SKILL.md + manifest + 关联公式）。"""
    from src.skills.market import export_skill
    return export_skill(key or '', bool(include_related))


def market_import(zip_path: str) -> dict:
    """zip 导入 -> v2 技能库 pending_review（进 P9 待审，R8 审批激活）。"""
    from src.skills.market import import_skill_zip
    return import_skill_zip(zip_path or '')


def market_stats() -> dict:
    from src.skills.market import market_stats
    return market_stats()


# ---------------- M14 审计（哈希链） ----------------
def audit_log(who: str, action: str, note: str = '') -> dict:
    e = _audit().log(who, action, note)
    return e.model_dump()


def audit_query(who: str = '', action: str = '', limit: int = 20) -> list[dict]:
    filters: dict = {}
    if who:
        filters['who'] = who
    if action:
        filters['action'] = action
    return [e.model_dump() for e in _audit().query(filters)[-limit:]]


def audit_verify() -> dict:
    return {'ok': _audit().verify_chain(), 'size': _audit().size}


# ---------------- M05 三层记忆 ----------------
def wm_set(key: str, value: str, ttl: int = 3600) -> dict:
    _wm().set(key, value, ttl)
    return {'ok': True}


def wm_get(key: str) -> dict:
    return {'value': _wm().get(key)}


def wm_keys() -> dict:
    return {'keys': _wm().keys()}


def epi_add(entity: str, event: str, payload: dict | None = None) -> dict:
    return {'event_id': _epi().add(entity, event, payload or {})}


def epi_query(q: str, top_k: int = 5) -> dict:
    return {'hits': [h.model_dump() for h in _epi().query(q, top_k=top_k)]}


def epi_summarize(entity: str) -> dict:
    return {'summary': _epi().summarize(entity)}


# ---------------- M2/M4 事实记忆（结构化 + 冲突消解） ----------------
def facts_add(entity: str, attr: str, value: str, ftype: str = 'fact',
              source: str = '', approved: bool = False) -> dict:
    from src.memory import facts
    return {'ok': True, 'fact': facts.add_fact(entity, attr, value, ftype, source, approved).model_dump()}


def facts_pending() -> dict:
    from src.memory import facts
    f = facts.pending_facts()
    return {'facts': [x.model_dump() for x in f], 'count': len(f)}


def facts_approve(fid: int) -> dict:
    from src.memory import facts
    return {'ok': True, 'fact': facts.approve_fact(int(fid), 'R8').model_dump()}


def facts_reject(fid: int) -> dict:
    from src.memory import facts
    return {'ok': True, 'fact': facts.reject_fact(int(fid), 'R8').model_dump()}


def facts_approve_all() -> dict:
    """V3 批量审批：一键通过全部 pending 事实（conclusion 类除外，需人工核对）。"""
    from src.memory import facts
    return {'ok': True, **facts.approve_all_pending('R8')}


def facts_query(entity: str = '', ftype: str = '', q: str = '', active_only: bool = True) -> dict:
    from src.memory import facts
    f = facts.query_facts(entity, ftype, q, active_only)
    return {'facts': [x.model_dump() for x in f], 'count': len(f)}


def facts_extract(text: str, source: str = 'agent') -> dict:
    """规则抽取事实落库（pending，过 R8 审核）；LLM 版由工具/端点按需触发。"""
    from src.memory import facts
    extracted = facts.extract_facts(text, caller=None, source=source)
    return {'facts': [x.model_dump() for x in extracted], 'count': len(extracted)}


# ---------------- M3 用户画像层（跨会话蒸馏稳定偏好） ----------------
def profile_get(user_key: str = 'local') -> dict:
    from src.memory import profile
    return {'profile': [p.model_dump() for p in profile.get_profile(user_key)],
            'count': len(profile.get_profile(user_key))}


def profile_distill(user_key: str = 'local') -> dict:
    from src.memory import profile
    return profile.distill(user_key)


def profile_upsert(user_key: str, attr: str, value: str) -> dict:
    from src.memory import profile
    return {'ok': True, 'item': profile.upsert(user_key, attr, value).model_dump()}


def profile_remove(user_key: str = 'local', pid: int | None = None, attr: str = '') -> dict:
    from src.memory import profile
    return {'ok': True, 'removed': profile.remove(user_key, pid, attr)}


def profile_render(user_key: str = 'local') -> str:
    from src.memory import profile
    return profile.render_profile(user_key)


# ---------------- M5 三层摘要（L1 精要 / L2 概览） ----------------
def task_summary(tid: int, caller=None) -> dict:
    """任务消息生成两级摘要（默认离线规则）。"""
    from src.memory import summary
    from src.core import db_v12 as db
    msgs = db.get_messages(int(tid))
    return summary.summarize_task_messages(msgs, caller)


def task_summary_save(tid: int, caller=None) -> dict:
    from src.memory import summary
    from src.core import db_v12 as db
    return summary.save_task_summaries(int(tid), db.get_messages(int(tid)), caller)


# ---------------- M6 检索意图路由（对齐 OpenViking Intent-Aware Query Planning） ----------------
# 意图 -> 检索源映射：操作型→技能；知识型→kb；个性化→画像/情景
_QUERY_PLAN = {
    'plan': {'source': 'kb', 'desc': '操作方案 → 知识库检索（标准/模板）'},
    'ask': {'source': 'episodic', 'desc': '提问 → 情景记忆检索'},
    'craft': {'source': 'kb', 'desc': '生成 → 知识库检索'},
}
# 个性化关键词：触发画像/情景
_PERSONA_KW = ('喜欢', '偏好', '习惯', '用过', '上次', '我记得', '用户')


def memory_route_search(text: str, top_k: int = 5) -> dict:
    """M6：意图路由 + 检索源分发（对齐 Intent-Aware Query Planning）。

    - 用 IntentRouter 判定 domain/intent；按 intent 映射检索源
    - 个性化关键词 → 画像 + 情景（含向量 hybrid）
    - 返回 {route, sources: [{source, desc, items}]}
    """
    from src.llm.intent import IntentRouter
    route = IntentRouter().analyze(text)
    plan = _QUERY_PLAN.get(route.intent, _QUERY_PLAN['craft'])
    sources = []
    low = (text or '').lower()

    # 个性化 → 画像 + 情景
    if any(k in low for k in _PERSONA_KW):
        from src.memory import profile
        prof = [p.model_dump() for p in profile.get_profile()][:5]
        if prof:
            sources.append({'source': 'profile', 'desc': '用户画像', 'items': prof})
        epi = _epi().query(text, top_k=top_k)
        if epi:
            sources.append({'source': 'episodic', 'desc': '情景记忆（向量+关键词）',
                            'items': [h.model_dump() for h in epi]})
        # L2 场景记忆：混入历史任务摘要（"上次怎么做的"）
        su = _task_summary_search(text, top_k=min(3, top_k))
        if su:
            sources.append({'source': 'summary', 'desc': '场景记忆（历史任务摘要）', 'items': su})
        return {'route': route.model_dump(), 'sources': sources, 'plan': 'personalized'}

    # 按意图分发
    if plan['source'] == 'kb':
        from src.core import db_v12 as db
        try:
            items = db.kb_hybrid_search(text, top_n=top_k)
        except Exception:  # kb 表未初始化/检索失败 → 降级空结果
            items = []
        sources.append({'source': 'kb', 'desc': plan['desc'],
                        'items': [{'title': r.get('title') or r.get('content', '')[:60],
                                   'score': r.get('score') or 0, 'domain': r.get('domain', '')}
                                  for r in items][:top_k]})
    else:  # episodic
        epi = _epi().query(text, top_k=top_k)
        sources.append({'source': 'episodic', 'desc': plan['desc'],
                        'items': [h.model_dump() for h in epi]})

    # L2 场景记忆：plan/ask 意图混入历史任务摘要，让跨任务经验可复用
    if route.intent in ('plan', 'ask'):
        su = _task_summary_search(text, top_k=min(3, top_k))
        if su:
            sources.append({'source': 'summary', 'desc': '场景记忆（历史任务摘要）', 'items': su})

    return {'route': route.model_dump(), 'sources': sources, 'plan': route.intent}


def _task_summary_search(text: str, top_k: int = 3) -> list[dict]:
    """L2 场景记忆检索：按关键词匹配历史任务摘要（标题/abstract/overview 的轻量词频打分）。"""
    from src.core.db import get_conn
    try:
        rows = get_conn().execute(
            'SELECT task_id, title, abstract, overview FROM task_summaries').fetchall()
    except Exception:  # 表未迁移/初始化
        return []
    if not rows:
        return []
    from src.llm.intent import IntentRouter
    tokens = set(_tokenize_lite(text or ''))
    if not tokens:
        return []
    scored = []
    for r in rows:
        hay = ' '.join([r['title'] or '', r['abstract'] or '', r['overview'] or '']).lower()
        score = sum(1 for t in tokens if t in hay)
        if score > 0:
            scored.append({'score': score, 'task_id': r['task_id'],
                           'title': r['title'] or f'任务#{r["task_id"]}',
                           'abstract': (r['abstract'] or '')[:120]})
    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:top_k]


def _tokenize_lite(text: str) -> list[str]:
    """轻量分词：英文词 + 中文字符 n-gram（1-2 字），无需 jieba 依赖。"""
    import re
    en = re.findall(r'[a-zA-Z0-9]+', text.lower())
    zh = [ch for ch in text if '\u4e00' <= ch <= '\u9fff']
    zh_bigram = [zh[i] + zh[i + 1] for i in range(len(zh) - 1)]
    return en + zh + zh_bigram


# ---------------- M07 技能执行器（含硬闸门演示） ----------------
def skill_execute(skill_id: str, params: dict | None = None, context: dict | None = None) -> dict:
    r = _skill_exec().run(skill_id, params or {}, context or {})
    return r.model_dump()


# ---------------- M03 意图路由 ----------------
def intent_analyze(text: str) -> dict:
    return _intent().analyze(text).model_dump()


# ---------------- M04 工具注册表 ----------------
def tools_list(capability: str = '') -> list[dict]:
    return [t.model_dump(exclude={'handler'}) for t in _tools().list(capability or None)]


def tools_execute(tool_id: str, params: dict | None = None) -> dict:
    r = _tools().execute(tool_id, params or {})
    return r.model_dump()


# ---------------- M10 报告查询 ----------------
# 报告类型 -> 中文名（列表/编辑器展示）
_REPORT_TYPE_NAMES = {
    'monitoring': '监测报告', 'acceptance': '验收报告', 'eia': '环评报告', 'blank': '空白报告',
}
# 报告状态 -> 中文名
_REPORT_STATUS_NAMES = {
    'drafting': '草稿', 'review': '审核中', 'auto_fix': '修订中',
    'compliance': '合规审核', 'signoff': '已签收', 'learn': '归档学习',
    'done': '已归档', 'escalate': '已升级',
}
# 报告状态 -> 前端 tab 分组（draft 草稿 / review 审核中 / done 已归档）
_REPORT_STATUS_GROUP = {
    'drafting': 'draft',
    'review': 'review', 'auto_fix': 'review', 'compliance': 'review', 'escalate': 'review',
    'signoff': 'done', 'learn': 'done', 'done': 'done',
}


def _report_view(r: Any) -> dict:
    """报告统一视图：workflow 状态回写 report.status，并补齐前端展示字段。

    Report.status 在 generate 后固定为 drafting，而状态机状态在 _WF_KEYS 单独维护，
    这里在每次出参时做一次同步，保证列表/详情/编辑器拿到真实状态。
    """
    d = r.model_dump()
    # 1) workflow 状态回写 status（状态机已流转到哪一步就以哪一步为准）
    st = workflow_state(r.id).get('state') or ''
    if st and st != 'idle' and st in _REPORT_STATUS_NAMES:
        d['status'] = st
    cur = d['status']
    # 2) 补齐展示字段
    pid = r.project_id or ''
    d['report_id'] = d.get('report_id') or d.get('id')  # 前端统一用 report_id
    d['title'] = f"{_REPORT_TYPE_NAMES.get(r.type, str(r.type))} {pid}".strip()
    d['task_id'] = int(pid[2:]) if pid.startswith('P-') and pid[2:].isdigit() else None
    d['updated_at'] = _report_svc().updated_at(r.id) or d.get('created_at') or ''
    d['status_name'] = _REPORT_STATUS_NAMES.get(cur, str(cur) or '草稿')
    d['workflow_node'] = d['status_name']
    d['group'] = _REPORT_STATUS_GROUP.get(cur, 'draft')
    d['exported'] = bool(r.docx_path)
    return d


def report_get(report_id: str) -> dict | None:
    svc = _report_svc()
    r = svc.get(report_id)
    if r is None:
        return None
    sections = svc._sections.get(report_id, [])
    view = _report_view(r)
    # 正文快照：Report.content 为空时由章节拼装，编辑器打开即可见内容
    if not (view.get('content') or '').strip() and sections:
        view['content'] = '\n\n'.join(f"## {s.name or ''}\n{s.content or ''}" for s in sections)
    return {'report': view, 'sections': [s.model_dump() for s in sections]}


def reports_list() -> list[dict]:
    return [_report_view(r) for r in _report_svc()._reports.values()]


def report_export(report_id: str, fmt: str = 'md') -> dict | None:
    """导出报告文件：fmt=md 返回内容；fmt=docx 渲染写盘返回路径。"""
    svc = _report_svc()
    r = svc.get(report_id)
    if r is None:
        return None
    sections = svc._sections.get(report_id, [])

    if fmt == 'docx':
        from src.report.exporter import docx as render_docx
        path = f'data/reports/{report_id}.docx'
        render_docx(sections, path)
        # 记录导出标记，列表据此展示"已导出"；落库保证重启后 exported 仍为 true
        if not r.docx_path:
            r.docx_path = path  # type: ignore[attr-defined]
        try:
            svc.save(r)
        except Exception:
            pass  # 持久化失败不阻断导出
        return {'path': path, 'fmt': 'docx'}
    md = '\n\n'.join(f"## {s.name or ''}\n{s.content or ''}" for s in sections)
    return {'content': md, 'fmt': 'md'}


def report_expert_opinion(report_id: str, opinion: str) -> dict:
    """P3 专家意见回流：意见写入原任务对话（无原任务则建修改任务），返回 task_id。

    对话工作台打开该任务 → Agent 检测"专家意见"消息 → 按意见修改报告 → 复审。
    """
    from src.core import db_v12 as db
    svc = _report_svc()
    r = svc.get(report_id)
    if r is None:
        return {'ok': False, 'error': '报告不存在'}
    if not opinion or not opinion.strip():
        return {'ok': False, 'error': '专家意见不能为空'}
    # 解析原任务（orchestrator 用 project_id=P-{task_id}）
    tid = None
    pid = r.project_id or ''
    if pid.startswith('P-') and pid[2:].isdigit():
        tid = int(pid[2:])
        try:
            t = db.get_task(tid)
            if t is None:
                tid = None
        except Exception:
            tid = None
    if tid is None:
        t = db.create_task(f"报告{report_id}专家意见修改", 'craft')
        tid = t['id']
    db.add_message(tid, 'user', f"[专家意见] {opinion}\n（请针对报告 {report_id} 按上述专家意见逐条修改，并说明修改结果）")
    return {'ok': True, 'task_id': tid, 'report_id': report_id}


# ---------------- P2 资料缺口检测（对话索要阻塞） ----------------
# task_id -> {report_type, missing, total, have_n, attempts, ts}
_MATERIALS_BLOCK: dict[int, dict] = {}


def materials_check(report_type: str = '', conversation: str = '', task_id: int | None = None) -> dict:
    """资料校验：缺失时按 task_id 记录阻塞，完整时解除阻塞。"""
    import materials_check as mc
    res = mc.check(report_type, conversation, task_id)
    if task_id is not None:
        tid = int(task_id)
        if not res.get('complete'):
            prev = _MATERIALS_BLOCK.get(tid, {})
            _MATERIALS_BLOCK[tid] = {
                **res, 'attempts': prev.get('attempts', 0) + 1,
                'ts': datetime.now(UTC).isoformat(),
            }
        else:
            _MATERIALS_BLOCK.pop(tid, None)
    return res


def materials_blocked(task_id: int | None) -> bool:
    """该任务是否处于资料缺失阻塞态（等待用户补充）。"""
    return task_id is not None and int(task_id) in _MATERIALS_BLOCK


def materials_status(task_id: int | None = None) -> dict:
    if task_id is None:
        return {'blocked': {str(k): v for k, v in _MATERIALS_BLOCK.items()}}
    d = _MATERIALS_BLOCK.get(int(task_id))
    return {'blocked': d is not None, 'check': d}


def materials_clear(task_id: int) -> dict:
    _MATERIALS_BLOCK.pop(int(task_id), None)
    return {'ok': True, 'blocked': False}


# ---------------- P0 领域团队（组织模型重构） ----------------
_TEAM_REG: Any = None


def _teams() -> Any:
    global _TEAM_REG
    if _TEAM_REG is None:
        from src.teams.registry import get_registry
        _TEAM_REG = get_registry()
    return _TEAM_REG


def teams_list() -> list[dict]:
    return _teams().list()


def team_get(team_id: str) -> dict | None:
    return _teams().get(team_id)


def team_by_domain(domain: str) -> dict | None:
    return _teams().get_by_domain(domain)


def team_create(team_id: str, domain: str, name: str, description: str = '',
                roles: list | None = None, skills: list | None = None,
                wf_template: str = '', report_tmpls: list | None = None,
                tools: list | None = None, status: str = 'active') -> dict:
    from src.teams.registry import DEFAULT_WF
    return _teams().create(team_id, domain, name, description, roles, skills,
                           wf_template or DEFAULT_WF, report_tmpls, tools, status)


def team_update(team_id: str, **fields: Any) -> dict | None:
    return _teams().update(team_id, **fields)


def team_delete(team_id: str) -> dict:
    ok = _teams().remove(team_id)
    return {'ok': ok} if ok else {'ok': False, 'error': '团队不存在'}


def team_context(domain: str = '') -> dict:
    """按领域返回团队上下文（供对话装配 system prompt / 任务上下文）。"""
    return _teams().build_team_context(domain or None)


def team_onboarding(domain: str, name: str, description: str = '',
                    skills: list | None = None, roles: list | None = None) -> dict:
    """新领域自举：创建 onboarding 团队（产物待 R8 审核）。"""
    return _teams().create_onboarding_team(domain, name, description, skills, roles)


# ---------------- P1 报告模板库 + 多状态机 ----------------
_TMPL_STORE: Any = None


def _tmpl() -> Any:
    global _TMPL_STORE
    if _TMPL_STORE is None:
        from src.report.template_store import get_store
        _TMPL_STORE = get_store()
    return _TMPL_STORE


def templates_list(status: str = '') -> list[dict]:
    return _tmpl().list(status)


def template_get(template_id: str) -> dict | None:
    return _tmpl().get(template_id)


def template_by_type(type_: str) -> dict | None:
    return _tmpl().get_by_type(type_)


def template_save(template_id: str, type_: str, name: str, sections: list | None = None,
                  placeholders: list | None = None, prompt: str = '', export_title: str = '',
                  docx_path: str = '', source_uploads: list | None = None,
                  status: str = 'draft') -> dict:
    return _tmpl().save(template_id, type_, name, sections, placeholders, prompt,
                        export_title, docx_path, source_uploads, status)


def template_publish(template_id: str) -> dict | None:
    return _tmpl().publish(template_id)


def template_delete(template_id: str) -> dict:
    ok = _tmpl().delete(template_id)
    return {'ok': ok} if ok else {'ok': False, 'error': '模板不存在'}


def template_learn(upload_id: str, text: str, report_type: str, name: str = '') -> dict:
    """用户上传报告 → 自动归纳模板建议（draft 待预览确认）。"""
    from src.report.template_store import learn_template_from_upload
    return learn_template_from_upload(upload_id, text, report_type, name)


def wf_templates_list() -> list[dict]:
    import json as _json
    from src.core.db import get_conn as _get_conn
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM wf_template").fetchall()
    out = []
    for r in rows:
        out.append({
            'key': r['key'], 'name': r['name'],
            'states': _json.loads(r['states'] or '[]'),
            'edges': _json.loads(r['edges'] or '[]'),
            'builtin': bool(r['builtin']),
        })
    return out


def wf_template_get(key: str) -> dict | None:
    import json as _json
    from src.core.db import get_conn as _get_conn
    conn = _get_conn()
    r = conn.execute("SELECT * FROM wf_template WHERE key=?", (key,)).fetchone()
    if not r:
        return None
    return {'key': r['key'], 'name': r['name'],
            'states': _json.loads(r['states'] or '[]'),
            'edges': _json.loads(r['edges'] or '[]'),
            'builtin': bool(r['builtin'])}


# ---------------- P5 新领域自举（团队搭建引导） ----------------
# 12 大类领域关键词（建议书生成参考）
_DOMAIN_CATALOG = [
    ("water", "水环境", "水质监测、排污许可、水处理"), ("air", "大气", "废气监测、VOC、空气质量"),
    ("noise", "声环境", "噪声监测、声功能区"), ("soil", "土壤", "土壤污染、固废、危废、修复"),
    ("ecology", "生态", "生物多样性、自然保护区、生态评价"), ("radiation", "辐射", "电离辐射、电磁辐射"),
    ("carbon", "碳气候", "碳排放核算、碳核查、碳普惠"), ("eia", "环评许可", "环评、排污许可、竣工验收"),
    ("monitor", "监测质控", "环境监测、实验室质控"), ("law", "执法监管", "环境执法、行政处罚、信访"),
    ("consult", "咨询评估", "环境咨询、规划评估"), ("std", "标准法规", "标准、政策、法规"),
]


def domain_onboarding_recommend(domain: str, description: str, materials: list | None = None) -> dict:
    """新领域引导：基于用户提供的领域描述与资料，生成《能力建议书》。

    - 资料不足时返回 questions（提示需补充的标准/案例等）。
    - 资料齐备时生成建议书：{domain, name, business, skills, roles, wf, report_types, gaps}。
    """
    mats = materials or []
    has_content = any(m.get("text", "") for m in mats) or bool(description.strip())
    # 1) 资料收集评估
    gap_hint = []
    if not has_content:
        gap_hint.append("请提供该领域的标准、政策或业务描述")
    if not any(k in description for k in ("标准", "政策", "法规", "办法", "导则", "规范")):
        gap_hint.append("建议补充该领域主要标准/政策名称")
    if gap_hint:
        return {"ok": True, "ready": False, "questions": gap_hint,
                "domain": domain, "description": description}
    # 2) 依据描述匹配 12 大类参考
    cat_hit = None
    for cid, cname, cbiz in _DOMAIN_CATALOG:
        if cname in description or cid in domain:
            cat_hit = (cid, cname, cbiz)
            break
    # 3) 生成建议书
    biz = cat_hit[2] if cat_hit else "待定（按用户描述归纳）"
    name = f"{cat_hit[1] if cat_hit else domain}领域团队"
    skills = [
        {"skill_id": f"sk-{domain}-001", "name": f"{cat_hit[1] if cat_hit else domain}报告编制",
         "definition": f"按{cat_hit[1] if cat_hit else domain}领域规范编制专业报告", "level": 3},
        {"skill_id": f"sk-{domain}-002", "name": f"{cat_hit[1] if cat_hit else domain}审核",
         "definition": f"对{cat_hit[1] if cat_hit else domain}报告进行 P0/P1 分级审核", "level": 2},
        {"skill_id": f"sk-{domain}-003", "name": f"{cat_hit[1] if cat_hit else domain}合规",
         "definition": f"核验{cat_hit[1] if cat_hit else domain}标准合规性", "level": 2},
    ]
    roles = [
        {"node_id": "draft", "label": f"{cat_hit[1] if cat_hit else domain}编制", "tools": ["kb_lookup", "kb_hybrid", "kb_save", "calc_formula", "web_search"]},
        {"node_id": "review", "label": f"{cat_hit[1] if cat_hit else domain}审核", "tools": ["kb_lookup", "kb_hybrid", "calc_formula"]},
        {"node_id": "archive", "label": "归档", "tools": ["kb_save", "kb_audit"]},
    ]
    report_types = [{"type": f"{domain}_report", "name": f"{cat_hit[1] if cat_hit else domain}报告"}]
    return {
        "ok": True, "ready": True,
        "suggestion": {
            "domain": domain, "name": name, "description": description,
            "business": biz, "report_types": report_types,
            "skills": skills, "roles": roles,
            "wf_template": "report_pipeline",
            "gaps": ["建议后续补充该领域标准库", "建议上传 1-2 份真实报告归纳模板"],
        },
    }


def domain_onboarding_confirm(suggestion: dict) -> dict:
    """确认建议书 → 自动搭建新 Team（技能草稿 + 角色节点 + onboarding 团队，全部 pending R8 审核）。

    复用：team_onboarding（团队）+ skills2 结晶（技能草稿）+ roles_create（角色节点，无独立表则团队内）。
    """
    from src.teams.registry import get_registry
    reg = get_registry()
    domain = (suggestion or {}).get("domain", "")
    name = (suggestion or {}).get("name", f"{domain}领域团队")
    desc = (suggestion or {}).get("description", "")
    skills_defs = (suggestion or {}).get("skills") or []
    roles_defs = (suggestion or {}).get("roles") or []
    report_types = (suggestion or {}).get("report_types") or []
    # 幂等：同领域团队已存在（onboarding 或 active）→ 直接返回，不重复结晶技能
    existing_team = reg.get_by_domain(domain)
    if existing_team:
        return {"ok": True, "team": existing_team, "skill_ids": existing_team.get("skills") or [],
                "pending": existing_team.get("status") == "onboarding",
                "note": "该领域团队已存在，已复用"}
    # 1) 技能草稿 → OERCR pending_review（先 reflect 生成反思，再 crystallize）
    skill_ids = []
    for sd in skills_defs[:5]:
        try:
            # 每条技能定义 → 一条反思（gap=技能名，pattern_hint=建议沉淀）
            oercr_reflect(domain=domain, gap=sd.get("name", sd.get("skill_id", "技能")),
                          severity="P2", pattern_hint=sd.get("definition", ""))
            created = oercr_crystallize(level=int(sd.get("level", 2)), role="R8",
                                        domain=domain, definition=sd.get("definition", ""))
            for s in created.get("skills") or []:
                if s.get("id"):
                    skill_ids.append(s["id"])
        except Exception:
            pass
    # 2) 创建团队（onboarding 状态，产物待 R8 审核）
    team = reg.create_onboarding_team(
        domain=domain, name=name, description=desc,
        skills=skill_ids or [s.get("skill_id") for s in skills_defs],
        roles=roles_defs or [],
    )
    return {"ok": True, "team": team, "skill_ids": skill_ids, "pending": True,
            "note": "团队已创建（onboarding），技能草稿待 R8 审核，审核通过后可投入使用"}


# ---------------- P5 文档学习管线 ----------------
def learn_report(report_type: str = '', text: str = '', source: str = '') -> dict:
    """学习一份报告语料，更新章节模式库（data/report_learning.json）。"""
    import report_learning
    return report_learning.learn(report_type, text, source)


def learning_pattern(report_type: str) -> dict:
    import report_learning
    return report_learning.pattern(report_type)


def learning_status() -> dict:
    import report_learning
    data = report_learning._load()
    return {'types': {
        t: {'samples': b.get('samples', 0), 'sections': len(b.get('sections', {}))}
        for t, b in data.items()}}


# ---------------- P6 公开 API 适配器 ----------------
def publicapi_init() -> None:
    """注册内置适配器（幂等）。"""
    try:
        from src.public_api import registry
        registry.register_default()
    except Exception:
        pass


def publicapi_sources() -> list:
    from src.public_api import registry
    registry.register_default()
    return registry.list_sources()


def publicapi_fetch(source_id: str = '', **params) -> dict:
    from src.public_api import registry
    registry.register_default()
    return registry.fetch(source_id, **params)


def publicapi_health() -> dict:
    from src.public_api import registry
    registry.register_default()
    return registry.health_all()


# ---------------- P1 公式计算引擎（FormulaEngine） ----------------
_ENGINE: Any = None


def _engine() -> Any:
    global _ENGINE
    if _ENGINE is None:
        from src.compute.engine import FormulaEngine
        _ENGINE = FormulaEngine()
    return _ENGINE


def calc(standard: str = '', calc_type: str = '', data: dict | None = None,
         formula_id: str = '') -> dict:
    try:
        return _engine().calc(standard, calc_type, data or {}, formula_id)
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def formulas_list(standard: str = '', calc_type: str = '') -> list[dict]:
    return _engine().list(standard, calc_type)
