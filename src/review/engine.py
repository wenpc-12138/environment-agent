# -*- coding: utf-8 -*-
"""M11 审核引擎（contracts.md §3.M11；architecture.md §5 R5 职责）。

双契约兼容：
- 契约测试骨架（M18 时代）：`ReviewIssue{table,row_id,field,description,severity}`、
  `ReviewFeedback{issue,status,comment,reviewer}`、`ReviewEngine.run(report)`、
  `ReviewEngine.submit_feedback(feedback)`；
- contracts.md §3.M11：`ReviewEngine.review/auto_fix/diff`（P0/P1/P2 分级 +
  仅 auto_fixable 自动修复 + 版本 diff 回滚保护）。

审核流程（复用 R5 审核员职责）：review() 运行四类过滤器产出问题 →
summary 汇总；auto_fix() 仅处理 auto_fixable=True 的问题并通过
diff_worsened 闸门；diff() 返回任意两版本间差异，杜绝"越改越乱"。
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from ..models.core import Report
from .diff import diff_texts, diff_worsened
from .filters import run_filters


class ReviewIssue(BaseModel):
    """单条审核问题（P0/P1/P2）。

    - table/row_id/field：定位到具体数据表行字段（契约测试字段）；
    - description 必填；severity P0=必须修 / P1=应修 / P2=建议。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    table: str = ''
    row_id: str = ''
    field: str = ''
    description: str
    severity: str = 'P1'
    id: str = ''
    type: str = ''
    location: str = ''
    suggested_fix: str = ''
    auto_fixable: bool = False


class ReviewFeedback(BaseModel):
    """一次审核的完整反馈。

    - issue/status/comment/reviewer：契约测试字段（单条意见语义）；
    - version/issues/summary：contracts.md 字段（完整反馈语义）。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    issue: str = ''
    status: str = 'pending'  # pending / approved / rejected
    comment: str = ''
    reviewer: str = 'R5'
    version: int = 0
    issues: list[ReviewIssue] = Field(default_factory=list)
    summary: str = ''


class ReviewEngine:
    """报告审核引擎（R5 审核员）。"""

    def __init__(self, kb=None, query_for: str | None = None):
        self._kb = kb
        self._query_for = query_for
        self._versions: dict[int, str] = {}  # version -> 文本快照
        self._feedback: list[ReviewFeedback] = []
        self._seq = 0

    # ---- 内部 ----

    def _snapshot(self, report) -> str:
        from .filters import _extract_text
        return _extract_text(report)

    def _next_version(self) -> int:
        return max(self._versions, default=0) + 1

    def _build_issue(self, raw: dict) -> ReviewIssue:
        self._seq += 1
        sev = raw.get('severity', 'P1')
        return ReviewIssue(
            id=f'{sev}-{self._seq:03d}',
            type=raw.get('type', ''),
            severity=sev,
            location=raw.get('location', ''),
            description=raw.get('description', ''),
            suggested_fix=raw.get('suggested_fix', ''),
            auto_fixable=bool(raw.get('auto_fixable', False)),
            table=raw.get('table', ''),
            row_id=raw.get('row_id', ''),
            field=raw.get('field', ''),
        )

    # ---- contracts.md §3.M11 主接口 ----

    def review(self, report) -> ReviewFeedback:
        """审核报告：运行过滤器产出问题并汇总。"""
        text = self._snapshot(report)
        version = self._next_version()
        self._versions[version] = text
        raw_issues = run_filters(report, kb=self._kb, query_for=self._query_for)
        issues = [self._build_issue(r) for r in raw_issues]
        counts = {'P0': 0, 'P1': 0, 'P2': 0}
        for it in issues:
            counts[it.severity] += 1
        if issues:
            summary = (f'发现 {len(issues)} 个问题：'
                       f'P0 {counts["P0"]}、P1 {counts["P1"]}、P2 {counts["P2"]}')
        else:
            summary = '未发现问题，通过审核'
        return ReviewFeedback(
            issue=summary,
            version=version,
            issues=issues,
            summary=summary,
            reviewer='R5',
        )

    # 契约测试别名：run == review
    def run(self, report) -> ReviewFeedback:
        """契约测试入口（等价 review）。"""
        return self.review(report)

    def auto_fix(self, report, issues: list[ReviewIssue]) -> Report:
        """自动修复：仅处理 auto_fixable=True 的问题，受 diff_worsened 闸门保护。

        输入为 Report 时 model_copy 返回新版本；str/dict 输入合成轻量 Report
        （正文快照写入 content 与内部版本库）。
        """
        fixable = [it for it in issues if it.auto_fixable]
        original = self._snapshot(report)
        text = original
        for it in fixable:
            if it.type != 'unit_inconsistent':
                continue
            m = re.search(r'"([^"]+)"', it.description)  # 从描述提取错误写法
            target = it.suggested_fix.replace('统一为', '').strip()
            if m and target:
                text = text.replace(m.group(1), target)
        if diff_worsened(original, text):
            text = original  # 越改越乱：回滚
        version = self._next_version()
        self._versions[version] = text
        if isinstance(report, Report):
            return report.model_copy(update={'content': text, 'status': 'auto_fix',
                                             'version': report.version + 1})
        rid = f"rpt-{datetime.now(UTC).strftime('%Y%m%d')}-{version:03d}"
        return Report(id=rid, type='monitoring', project_id='prj-00000000-000',
                      content=text, status='auto_fix', version=version)

    def diff(self, version_a: int, version_b: int) -> list[str]:
        """比较两版本差异；缺版本返回空列表。"""
        a = self._versions.get(version_a)
        b = self._versions.get(version_b)
        if a is None or b is None:
            return []
        return diff_texts(a, b)

    # 契约测试入口：记录反馈
    def submit_feedback(self, feedback: ReviewFeedback) -> str:
        """提交审核反馈（R5 确认意见）。"""
        self._feedback.append(feedback)
        return f'feedback-{len(self._feedback)}'

    # ---- 查询 ----

    def feedback_history(self) -> list[ReviewFeedback]:
        return list(self._feedback)

    def versions(self) -> dict[int, str]:
        return dict(self._versions)


__all__ = ['ReviewEngine', 'ReviewIssue', 'ReviewFeedback']
