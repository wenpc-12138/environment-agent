# -*- coding: utf-8 -*-
"""M13 OERCR 闭环学习引擎（contracts.md §3.M13）。

闭环：observe(obs→O) → reflect(refl→R) → crystallize(cryst→C) → reuse(reuse→Rc)。
- observe：从任务日志提炼 Observation；
- reflect：对照基线反思差距，产出 Reflection 列表；
- crystallize：把反思沉淀为 SkillDef（status=pending_review，待 R8 审核）入 ProceduralMemory；
- reuse：任务复用，Procedural 优先（ProceduralMemory.best_match）。

循环依赖检测：同一 (domain, gap) 只结晶一次（_crystallized 去重），
复用阶段如闭环自洽（reuse 命中已学技能）则不再重复观察，防止无限学习循环。
"""
from __future__ import annotations

from datetime import UTC, datetime

from ..memory.procedural import ProceduralMemory
from ..models.core import (
    DomainEnum,
    Observation,
    Reflection,
    SkillDef,
)
from .learner import Learner

_UTC_ISO = lambda: datetime.now(UTC).isoformat(timespec='seconds')

_OBS_SEQ = {'n': 0}
_REF_SEQ = {'n': 0}
_SKILL_SEQ = {'n': 0}


class OercrEngine:
    """OERCR 闭环学习引擎。"""

    def __init__(self, memory: ProceduralMemory | None = None, learner: Learner | None = None) -> None:
        self._memory = memory or ProceduralMemory()
        self._learner = learner or Learner()
        self._crystallized: set[tuple[str, str]] = set()  # (domain, gap) 去重防循环
        self._episodes: set[str] = set()  # 已观察 episode

    # ---- 观测 ----
    def observe(self, task_log: dict) -> Observation:
        """从任务日志提炼 Observation（obs→O）。"""
        episode_id = task_log.get('episode_id') or task_log.get('task_id') or ''
        task = task_log.get('task') or ''
        domain = task_log.get('domain') or ''
        outcome = task_log.get('outcome') or 'partial'
        feedback = task_log.get('feedback') or task_log.get('user_feedback') or ''
        _OBS_SEQ['n'] += 1
        obs = Observation(
            obs_id=f"obs-{datetime.now(UTC).strftime('%Y%m%d')}-{_OBS_SEQ['n']:03d}",
            episode_id=episode_id,
            task=task,
            domain=domain,
            task_log=task_log,
            outcome=outcome,
            user_feedback=feedback,
            ts=_UTC_ISO(),
        )
        if episode_id:
            self._episodes.add(episode_id)
        return obs

    # ---- 反思 ----
    def reflect(self, obs: Observation, baseline: dict | None = None) -> list[Reflection]:
        """对照基线反思差距（refl→R）。

        baseline 可含：
        - `threshold`：用户反馈负面即视为差距；
        - `patterns`：Learner 已提炼的模式，用于生成 pattern_hint。
        """
        baseline = baseline or {}
        threshold = float(baseline.get('threshold', 0.0))
        patterns = baseline.get('patterns') or self._learner.extract_pattern(
            [{'input': obs.task, 'output': '', 'feedback': obs.user_feedback, 'domain': obs.domain}]
        )
        reflections: list[Reflection] = []
        negative = any(k in obs.user_feedback.lower() for k in ('fail', '错误', '超限', '修正', '不符'))
        # 1) 用户反馈负面 → 首要差距
        if negative or obs.outcome in ('failed', 'partial'):
            _REF_SEQ['n'] += 1
            reflections.append(
                Reflection(
                    ref_id=f"refl-{datetime.now(UTC).strftime('%Y%m%d')}-{_REF_SEQ['n']:03d}",
                    obs_id=obs.obs_id,
                    domain=obs.domain,
                    gap=obs.task or '任务执行存在差距',
                    pattern_hint=patterns[0].rule if patterns else '',
                    severity='P0' if obs.outcome == 'failed' else 'P1',
                    confidence=patterns[0].confidence if patterns else 0.5,
                )
            )
        # 2) 模式置信度高于阈值 → 记录为可沉淀模式
        for p in patterns:
            if p.confidence >= threshold and p.confidence >= 0.7:
                _REF_SEQ['n'] += 1
                reflections.append(
                Reflection(
                    ref_id=f"refl-{datetime.now(UTC).strftime('%Y%m%d')}-{_REF_SEQ['n']:03d}",
                    obs_id=obs.obs_id,
                    domain=obs.domain,
                    gap=p.rule,
                    pattern_hint=p.rule,
                    severity='P2',
                    confidence=p.confidence,
                )
                )
        return reflections

    # ---- 结晶 ----
    def crystallize(self, reflections: list[Reflection]) -> list[SkillDef]:
        """把反思沉淀为 SkillDef（cryst→C），status=pending_review 待 R8 审核。

        循环依赖检测：同一 (domain, gap) 已结晶则跳过，返回已存在技能（闭环自洽）。
        H1 技能迭代：若同 gap 已有 **active** 技能（跨会话查库），不重复结晶，
        改为生成 `skill_update` 迭代提案（pending，R8 审批后 update_skill 演进版本）。
        """
        produced: list[SkillDef] = []
        proposed: list[int] = []
        for ref in reflections:
            key = (ref.pattern_hint or ref.gap, ref.gap)
            if key in self._crystallized:
                continue  # 已学习过，防止无限循环
            self._crystallized.add(key)
            domain = ref.domain if ref.domain in ('D1', 'D2', 'D3', 'D4', 'D5', 'D6') else ''
            if not domain and ref.pattern_hint:
                domain = ref.pattern_hint.split(' -> ')[0]
                domain = domain if domain in ('D1', 'D2', 'D3', 'D4', 'D5', 'D6') else ''
            # H1：同 gap 已有 active 技能 → 生成迭代提案（不重复结晶）
            existing = self._find_active_by_gap(ref.gap)
            if existing is not None:
                pid = self.propose_update(existing.id, ref)
                if pid:
                    proposed.append(pid)
                continue
            _SKILL_SEQ['n'] += 1
            skill = SkillDef(
                id=f"sk-oerc-{_SKILL_SEQ['n']:03d}",
                name=f"OERCR-{ref.gap[:24] or 'learned'}",
                level=2,
                role='R8',
                domain=domain or 'D1',
                version='1.0.0',
                status='pending_review',  # 待 R8 审核
                definition=f"gap: {ref.gap}\npattern: {ref.pattern_hint}\nseverity: {ref.severity}",
                created_by='agent_oercr',
            )
            self._memory.create_skill(skill)
            produced.append(skill)
        self._last_proposals = proposed
        return produced

    # ---- H1 技能迭代（对齐 Hermes 自进化闭环） ----
    def _find_active_by_gap(self, gap: str):
        """查库：是否存在 definition 含同 gap 的 active 技能（跨会话）。"""
        if not gap:
            return None
        for s in self._memory.list_skills(status='active'):
            if gap and gap in (s.definition or ''):
                return s
        return None

    def propose_update(self, skill_id: str, ref: Reflection) -> int:
        """为已存在 active 技能生成迭代提案（pending，待 R8 审批）。"""
        from src.core.db import get_conn
        from src.core.utils import now_iso
        base = self._memory.get_skill(skill_id)
        if base is None:
            return 0
        new_def = (f"gap: {ref.gap}\npattern: {ref.pattern_hint}\n"
                   f"severity: {ref.severity}\niteration: updated")
        cur = get_conn().execute(
            'INSERT INTO skill_update_proposals(skill_id,base_version,new_definition,reason,status,created_at) '
            'VALUES(?,?,?,?,?,?)',
            (skill_id, base.version, new_def, f'同 gap 重复学习，建议升级 {base.version} → 下一版本', 'pending',
             now_iso()),
        )
        get_conn().commit()
        return int(cur.lastrowid)

    def pending_updates(self) -> list:
        """待审迭代提案。"""
        from src.core.db import get_conn
        rows = get_conn().execute(
            "SELECT * FROM skill_update_proposals WHERE status='pending' ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    def approve_update(self, pid: int, reviewer: str = 'R8') -> bool:
        """R8 审批迭代提案：update_skill 版本递增（v+patch），提案置 approved。"""
        from src.core.db import get_conn
        if reviewer != 'R8':
            return False
        row = get_conn().execute(
            'SELECT * FROM skill_update_proposals WHERE id=? AND status=?', (pid, 'pending')).fetchone()
        if row is None:
            return False
        base = self._memory.get_skill(row['skill_id'])
        if base is None:
            return False
        # 版本递增 patch
        parts = (base.version or '1.0.0').split('.')
        parts[-1] = str(int(parts[-1] or 0) + 1)
        new_version = '.'.join(parts)
        new_def = SkillDef(
            id=base.id, name=base.name, level=base.level, role=base.role,
            domain=base.domain, version=new_version, status=base.status,
            definition=row['new_definition'], created_by=base.created_by,
        )
        if not self._memory.update_skill(base.id, new_def, reviewer):
            return False
        get_conn().execute("UPDATE skill_update_proposals SET status='approved' WHERE id=?", (pid,))
        get_conn().commit()
        return True

    def reject_update(self, pid: int, reviewer: str = 'R8') -> bool:
        from src.core.db import get_conn
        cur = get_conn().execute(
            "UPDATE skill_update_proposals SET status='rejected' WHERE id=? AND status='pending'", (pid,))
        get_conn().commit()
        return cur.rowcount > 0

    # ---- 复用 ----
    def reuse(self, task: str, domain: str | None = None) -> SkillDef | None:
        """任务复用（reuse→Rc）：Procedural 优先。

        命中 active 技能即返回；未命中返回 None（触发新一轮观察）。
        """
        hit = self._memory.best_match(task, domain)
        return hit

    # ---- R8 审核联动（第 8 波）----
    def approve_pending(self, reviewer: str = 'R8') -> list[SkillDef]:
        """R8 批量激活 OERCR 结晶产物（pending_review → active）。

        仅激活 `created_by='agent_oercr'` 的待审技能；返回本次成功激活的技能列表。
        非 R8 审核人返回空列表。
        """
        activated: list[SkillDef] = []
        if reviewer != 'R8':
            return activated
        for s in self._memory.list_skills(status='pending_review'):
            if s.created_by != 'agent_oercr':
                continue
            if self._memory.approve_skill(s.id, reviewer):
                # 重读激活后的记录（原对象仍为 pending_review）
                fresh = next((x for x in self._memory.list_skills(status='active')
                              if x.id == s.id), None)
                activated.append(fresh if fresh is not None else s)
        return activated


__all__ = ['OercrEngine']
