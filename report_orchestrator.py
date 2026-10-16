# -*- coding: utf-8 -*-
"""专家团报告流水线（对话驱动内部实现，非独立界面）。

用户在主界面对话框输入报告需求后，按工作流自动编排多角色协作：
  R4 编制员    生成报告初稿（M10 ReportService + 五章节模板）
  R5 审核员    P0/P1/P2 分级审核（M11 ReviewEngine）
  R6 合规员    CMA 合规检查（M12 ComplianceEngine）
  R8 知识管理员 标准有效性核验（M06 check_validity）
状态机（M09）全程自动流转：drafting → review → compliance → signoff → learn → done。
"""
from __future__ import annotations

import os
from typing import Any

ROLE_NAMES = {'R4': '编制员', 'R5': '审核员', 'R6': '合规员', 'R8': '知识管理员'}


def _infer_type(conversation: str) -> str:
    c = (conversation or '').lower()
    if '验收' in c or 'acceptance' in c:
        return 'acceptance'
    if '环评' in c or 'eia' in c:
        return 'eia'
    return 'monitoring'


def run(conversation: str, project_id: str = 'P-DIALOG', task_id: int | None = None,
        materials: dict | None = None, rewriter_caller=None) -> dict:
    """执行专家团流水线，返回 {report, steps, workflow}；task_id 提供时自动落盘 MD/DOCX。

    materials：P2 资料核对通过后的已有资料（{key: 证据, data_rows: [监测数据行]}），
    R4 生成后自动填充数据章节，避免"待填写"占位。
    rewriter_caller：P3 LLM 重写回调（messages -> str），None 时仅规则重写。
    """
    steps: list[dict[str, Any]] = []

    # ---- R4 编制员：生成报告初稿（复用 v2_bridge 单例，报告档案可见） ----
    from src.gateway import bridge_compat as v2_bridge
    svc = v2_bridge._report_svc()
    report = svc.generate(_infer_type(conversation), project_id)
    sections = svc._sections.get(report.id, [])
    # P2/P4：资料核验后把监测数据填入结果章节——P4 按标准自动取公式计算
    # （单项污染指数/超标判定/均值/综合指数）随行填充，消除"待填写"占位
    rows = (materials or {}).get('data_rows') or []
    if rows:
        try:
            import report_calc
            cfill = report_calc.calc_fill(sections, rows)
            summ = cfill['summary']
            parts = [f"填入 {cfill['filled']} 条监测数据并计算：超标 {summ.get('exceeded', 0)} 项"]
            if summ.get('mean') is not None:
                parts.append(f"均值 {summ['mean']}")
            if summ.get('nemean') is not None:
                parts.append(f"综合指数 {summ['nemean']}")
            steps.append({
                'role': 'R4', 'name': ROLE_NAMES['R4'],
                'action': '按标准自动计算并填充数据（P4 集成计算）',
                'summary': '；'.join(parts),
                'formulas': cfill['used_formulas'],
            })
        except Exception:  # noqa: BLE001
            pass

    # ---- P5 文档学习增强：用真实语料学习的章节模式增强编制 ----
    import report_learning
    learned_pat = report_learning.pattern(_infer_type(conversation))
    if learned_pat.get('sections'):
        from src.models.core import ReportSection
        extras = report_learning.extra_sections(learned_pat)
        learned_plan = report_learning.apply_learned(learned_pat)
        reqs_txt = '、'.join(learned_plan.get('learned_reqs', []) or [])
        for sec in sections:
            if sec.name == 'monitoring_plan' and reqs_txt:
                sec.content += f"\n数据要求（P5 语料学习）：本类报告常包含 {reqs_txt} 相关信息。"
        for e in extras[:4]:
            sections.append(ReportSection(
                name=f"learned_{e['name'][:8]}",
                content=report_learning.learned_extra_content(e), refs=[]))
        steps.append({
            'role': 'R4', 'name': ROLE_NAMES['R4'],
            'action': '文档学习增强（P5）',
            'summary': (f"基于 {learned_pat.get('source_count', 0)} 份语料："
                        f"附加 {len(extras[:4])} 节学习章节"
                        + (f"，数据要求：{reqs_txt}" if reqs_txt else "")),
            'learned': {'sections': len(learned_pat.get('sections', [])),
                        'extras': [e['name'] for e in extras[:4]]},
        })
    content = '\n'.join((s.content or '') for s in sections)
    steps.append({
        'role': 'R4', 'name': ROLE_NAMES['R4'],
        'action': f'生成{report.type}报告初稿（五章节模板）',
        'summary': f'已生成 {report.id}（{report.type}，v{report.version}，{report.status}）',
    })

    # 落盘：MD + DOCX 到任务输出目录
    if task_id:
        try:
            import db
            md = '\n\n'.join(f'## {s.name or ""}\n{s.content or ""}' for s in sections)
            db.task_output_save(task_id, "report.md", md)
            from src.report.exporter import docx as render_docx
            render_docx(sections, os.path.join(db.task_output_dir(task_id), "report.docx"))
            steps.append({
                'role': 'R4', 'name': ROLE_NAMES['R4'],
                'action': '输出报告文件',
                'summary': '已输出 report.md + report.docx 到任务输出文件夹',
            })
        except Exception:  # noqa: BLE001
            pass

    # ---- R5 审核员：P0/P1/P2 分级审核 + P4 计算验证 + P3 重写闭环 ----
    from src.review.engine import ReviewEngine, ReviewIssue
    import report_calc

    def _review_with_calc(t: str):
        """审核 + 计算验证（FormulaEngine 重算核对，不一致追加 P1）+ P7 反馈自动沉淀。"""
        fb = ReviewEngine().review(t)
        v = report_calc.verify_calcs(t, data_rows=rows)
        if v.get('errors'):
            extra = [ReviewIssue(severity='P1', type='calc_verify',
                                 description=f'计算验证不一致：{e}', location='监测结果/结论')
                     for e in v['errors']]
            fb.issues = list(fb.issues) + extra
            fb.summary += f"；计算验证 {len(v['errors'])} 处不一致"
        # P7：审核反馈自动喂 Learner，高置信模式结晶 pending_review（R8 审批）
        try:
            from src.gateway import bridge_compat as v2_bridge
            v2_bridge.oercr_learn_from_review(fb.issues)
        except Exception:  # noqa: BLE001
            pass
        return fb

    fb = _review_with_calc(content)
    issues = fb.issues
    hard = any(i.severity in ('P0', 'P1') for i in issues)
    steps.append({
        'role': 'R5', 'name': ROLE_NAMES['R5'],
        'action': 'P0/P1/P2 分级审核 + 计算验证（初审）',
        'summary': fb.summary,
        'issues': [i.model_dump() for i in issues],
        'auto_fix': not hard,
    })

    # P3：存在 P0/P1 时自动重写闭环（规则/LLM 重写 -> 复审，含计算验证），直至通过或达轮次上限
    rewrite = None
    if hard:
        import report_rewrite
        rewrite = report_rewrite.rewrite_loop(
            sections, _review_with_calc,
            caller=rewriter_caller, max_rounds=3)
        content = report_rewrite.join_sections(sections)
        fb2 = _review_with_calc(content)
        issues = fb2.issues
        hard = any(i.severity in ('P0', 'P1') for i in issues)
        steps.append({
            'role': 'R5', 'name': ROLE_NAMES['R5'],
            'action': '自动重写与复审',
            'summary': (f"重写 {rewrite.get('rounds', 0)} 轮，"
                        f"消除 {len(rewrite.get('hard_before', [])) - len(rewrite.get('hard_after', []))} 项问题"
                        if rewrite.get('passed') else
                        f"重写 {rewrite.get('rounds', 0)} 轮后仍余 {len(rewrite.get('hard_after', []))} 项 P0/P1，待人工处理"),
            'issues': [i.model_dump() for i in issues],
            'rewrites': rewrite.get('rewrites', []),
            'verified': rewrite.get('verified', {}),
            'passed': rewrite.get('passed', False),
        })

    # ---- R6 合规员：CMA 合规检查 ----
    from src.compliance.engine import ComplianceEngine
    cres = ComplianceEngine().check(report=content)
    steps.append({
        'role': 'R6', 'name': ROLE_NAMES['R6'],
        'action': 'CMA 合规检查',
        'summary': '合规通过' if cres.passed else f'存在 {len(cres.violations)} 项违规',
        'passed': cres.passed,
        'violations': [v.model_dump() for v in cres.violations],
    })

    # ---- R8 知识管理员：标准有效性核验 ----
    try:
        from src.kb.standards import StandardKB
        info = StandardKB().check_validity('GB 3838-2002')
        status = info.status if info else '未知'
    except Exception:  # noqa: BLE001
        status = 'KB 未就绪'
    steps.append({
        'role': 'R8', 'name': ROLE_NAMES['R8'],
        'action': '标准有效性核验（GB 3838-2002）',
        'summary': f'GB 3838-2002：{status}',
    })

    # ---- 状态机自动流转（M09）----
    # 决策点 4：无签发动作，报告完成即归档
    from src.workflow.engine import WorkflowEngine
    eng = WorkflowEngine()
    iid = eng.start('report_pipeline', {project_id: report.id})
    for ev in ('submit', 'approve', 'pass', 'done'):
        eng.transition(iid, {'type': ev})

    # P4 学习归档：报告完成自动归档知识库 + 语料学习 + 技能迭代提案（无需人工签发）
    learning = None
    try:
        from src.gateway import bridge_compat as v2_bridge
        learning = v2_bridge._report_learning_auto(report.id, report)
    except Exception:
        pass

    return {
        'report': report.model_dump(),
        'steps': steps,
        'workflow': {'instance_id': iid, 'state': eng.get_state(iid)},
        'report_sections': sections,
        'learning': learning,
    }


def step_text(step: dict[str, Any], max_issues: int = 3) -> str:
    """角色步骤摘要文本（供对话输出）。"""
    out = step.get('summary', '')
    issues = step.get('issues') or []
    if issues:
        out += '；问题：' + '；'.join(
            f"{i.get('severity')} {i.get('description', '')}" for i in issues[:max_issues])
    violations = step.get('violations') or []
    if violations:
        out += '；违规：' + '；'.join(
            f"{v.get('severity')} {str(v.get('message', ''))[:40]}" for v in violations[:max_issues])
    return out
