# -*- coding: utf-8 -*-
"""G4 会话断点续传（对齐 Claude Code /resume 思路，实现完全自研）。

- `save()`：任务中途暂停时落点（round / 窗口摘要 / 已完成步骤 / 中间产物），幂等 upsert。
- `resume()`：恢复时读取断点，生成"恢复上下文"（摘要 + 已完成步骤提示），供 _loop 注入。
- `clear()`：任务完成 / 放弃 / 删除时清除断点。

数据层在根 `db.py`（task_checkpoints 表，与 tasks/messages 同库）。
"""
from __future__ import annotations

import json
from typing import Any

from src.core import db_v12 as v12_db  # S2-M6：数据层统一


class CheckpointManager:
    """任务断点读写封装。"""

    def save(self, task_id: int, round_no: int = 0, window_summary: str = '',
             done_steps: list | None = None, partial_outputs: dict | None = None,
             status: str = 'paused') -> dict:
        """保存断点；返回 {'ok': True, 'task_id': ...}。"""
        v12_db.save_checkpoint(task_id, round_no, window_summary, done_steps, partial_outputs, status)
        return {'ok': True, 'task_id': task_id, 'round': int(round_no), 'status': status}

    def get(self, task_id: int) -> dict | None:
        ck = v12_db.get_checkpoint(task_id)
        if not ck:
            return None
        return {
            'task_id': ck['task_id'],
            'round': ck['round'],
            'status': ck['status'],
            'window_summary': ck.get('window_summary') or '',
            'done_steps': _loads(ck.get('done_steps'), []),
            'partial_outputs': _loads(ck.get('partial_outputs'), {}),
            'created_at': ck.get('created_at'),
            'updated_at': ck.get('updated_at'),
        }

    def resume(self, task_id: int) -> dict | None:
        """标记断点为已恢复（resumed），返回断点内容供注入；无断点返回 None。"""
        ck = self.get(task_id)
        if not ck:
            return None
        v12_db.checkpoint_set_status(task_id, 'resumed')
        ck['status'] = 'resumed'
        return ck

    def clear(self, task_id: int) -> dict:
        v12_db.clear_checkpoint(task_id)
        return {'ok': True, 'task_id': task_id}

    def build_resume_context(self, ck: dict) -> str:
        """把断点转成注入 _loop 的恢复提示文本。"""
        parts = [f'[会话恢复] 该任务曾在第 {ck.get("round", 0)} 轮被暂停，以下是暂停前进度摘要，请接着完成未竟工作：']
        if ck.get('window_summary'):
            parts.append(f'进度摘要：{ck["window_summary"][:800]}')
        steps = ck.get('done_steps') or []
        if steps:
            names = ', '.join(f"{s.get('name') or s.get('tool') or '步骤'}"
                              f"({'已完成' if s.get('ok') else '失败'})" for s in steps[:20])
            parts.append(f'已完成步骤：{names}')
        parts.append('请勿复述进度。请立即继续调用工具，执行断点处尚未完成的任务步骤，'
                     '执行完毕后直接把最终成果输出给用户，不要询问确认，不要中途停下。')
        return '\n'.join(parts)


def _loads(raw: Any, default: Any) -> Any:
    try:
        v = json.loads(raw) if raw else default
        return v if v is not None else default
    except (ValueError, TypeError):
        return default
