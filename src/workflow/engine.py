# -*- coding: utf-8 -*-
"""M09 工作流引擎：报告状态机 + 实例流转（contracts.md §3.M09）。

- `WorkflowEngine.load(yaml_path)`：从 YAML 文件加载 WorkflowSpec。
- `WorkflowEngine.start(workflow_name, payload)`：启动实例（无 YAML 时回退内置报告状态机）。
- `WorkflowEngine.transition(instance_id, event)`：按状态机流转，任意环节可 escalate（人工介入）。
- `WorkflowEngine.get_state(instance_id)`：返回当前 ReportStatus。

内置报告状态机（architecture.md §6）：
drafting -> review -> (auto_fix) -> compliance -> signoff -> learn -> done；任意环节 escalate。

S1-W1 持久化（2026-08-20）：
- `WorkflowEngine(storage='memory'|'db')`——memory 为默认（纯内存，行为不变）；
  db 模式把实例（state/payload/history/retry_count）持久化到 `workflow_instances`
  表（迁移 0013），重启后可恢复；内存 dict 仍作热缓存，DB 为持久化镜像。
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from ..models.core import ReportStatus, StateResult, WorkflowSpec

# workflow_instances 表字段（与 db/migrations/0013_workflow_instances.sql 对应）
_INSTANCE_COLS = ('instance_id', 'workflow', 'state', 'payload', 'history', 'retry_count',
                  'created_at', 'updated_at')

# ---- 内置报告状态机（YAML 语义的 dict；无外部文件时回退）----
BUILTIN_REPORT_SM: dict[str, Any] = {
    'name': 'report_pipeline',
    'trigger': 'auto_router',
    'initial': 'drafting',
    'states': {
        'drafting': {'submit': 'review', 'escalate': 'escalate'},
        'review': {'approve': 'compliance', 'fix': 'auto_fix', 'escalate': 'escalate'},
        'auto_fix': {'fixed': 'review', 'escalate': 'escalate'},
        'compliance': {'pass': 'signoff', 'fail': 'review', 'escalate': 'escalate'},
        'signoff': {'sign': 'learn', 'escalate': 'escalate'},
        'learn': {'done': 'done', 'escalate': 'escalate'},
        'done': {},
        'escalate': {'resolve': 'drafting'},  # 人工处理完成后回 drafting 重新走
    },
}

_ESCALATE = 'escalate'


class WorkflowEngine:
    """状态机引擎：YAML 加载 + 实例流转（memory 或 db 持久化）。"""

    def __init__(self, storage: str = 'memory') -> None:
        """storage: 'memory'（默认，纯内存） | 'db'（实例持久化到 workflow_instances 表）。"""
        if storage not in ('memory', 'db'):
            raise ValueError(f"storage 仅支持 'memory'|'db'，收到: {storage!r}")
        self._storage = storage
        self._specs: dict[str, WorkflowSpec] = {}
        self._instances: dict[str, dict[str, Any]] = {}

    # ---- DB 后端（S1-W1）----
    @staticmethod
    def _conn():
        from ..core.db import get_conn
        return get_conn()

    def _db_save(self, inst: dict[str, Any]) -> None:
        """把实例写入/更新 workflow_instances 表（幂等 upsert）。"""
        conn = self._conn()
        conn.execute(
            'INSERT INTO workflow_instances(instance_id, workflow, state, payload, history,'
            ' retry_count, updated_at) VALUES (?,?,?,?,?,?, datetime(\'now\',\'localtime\'))'
            ' ON CONFLICT(instance_id) DO UPDATE SET'
            ' workflow=excluded.workflow, state=excluded.state, payload=excluded.payload,'
            ' history=excluded.history, retry_count=excluded.retry_count,'
            ' updated_at=excluded.updated_at',
            (inst['instance_id'], inst['workflow'], inst['state'],
             json.dumps(inst.get('payload', {}), ensure_ascii=False),
             json.dumps(inst.get('history', []), ensure_ascii=False),
             int(inst.get('retry_count', 0))))
        conn.commit()

    def _db_load(self, instance_id: str) -> dict[str, Any] | None:
        """从 DB 读取实例（不存在返回 None）。"""
        row = self._conn().execute(
            'SELECT * FROM workflow_instances WHERE instance_id=?', (instance_id,)).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row['payload'] or '{}')
        except ValueError:
            payload = {}
        try:
            history = json.loads(row['history'] or '[]')
        except ValueError:
            history = []
        return {
            'instance_id': row['instance_id'],
            'workflow': row['workflow'],
            'state': row['state'],
            'payload': payload,
            'history': history,
            'retry_count': int(row['retry_count'] or 0),
        }

    def _db_list(self) -> list[str]:
        rows = self._conn().execute('SELECT instance_id FROM workflow_instances').fetchall()
        return [r['instance_id'] for r in rows]

    def _get(self, instance_id: str) -> dict[str, Any]:
        """取实例：内存热缓存优先，db 模式 miss 时回源 DB 并回填缓存。"""
        inst = self._instances.get(instance_id)
        if inst is not None:
            return inst
        if self._storage == 'db':
            loaded = self._db_load(instance_id)
            if loaded is not None:
                self._instances[instance_id] = loaded
                return loaded
        raise KeyError(f'工作流实例不存在: {instance_id}')

    # ---- 加载 ----
    def load(self, yaml_path: str) -> WorkflowSpec:
        """从 YAML 文件加载状态机，缓存并返回 WorkflowSpec。"""
        from .loader import load_yaml_spec

        spec = load_yaml_spec(yaml_path)
        self._specs[spec.name] = spec
        return spec

    def register(self, spec: WorkflowSpec) -> None:
        """直接注册 WorkflowSpec（测试 / 编程式加载）。"""
        self._specs[spec.name] = spec

    def _ensure_spec(self, workflow_name: str) -> WorkflowSpec:
        spec = self._specs.get(workflow_name)
        if spec is None:
            spec = WorkflowSpec(
                name=BUILTIN_REPORT_SM['name'],
                trigger=BUILTIN_REPORT_SM['trigger'],
                state_machine={
                    'initial': BUILTIN_REPORT_SM.get('initial', 'drafting'),
                    'states': BUILTIN_REPORT_SM['states'],
                },
            )
            self._specs[workflow_name] = spec
        return spec

    # ---- 启动 ----
    def start(self, workflow_name: str, payload: dict) -> str:
        """启动工作流实例，返回 instance_id。"""
        spec = self._ensure_spec(workflow_name)
        sm = spec.state_machine
        initial = sm.get('initial', 'drafting')
        instance_id = f'{workflow_name}-{uuid.uuid4().hex[:12]}'
        inst = {
            'instance_id': instance_id,
            'workflow': workflow_name,
            'state': initial,
            'payload': payload,
            'retry_count': 0,
            'history': [(None, initial, payload)],
        }
        self._instances[instance_id] = inst
        if self._storage == 'db':
            self._db_save(inst)
        return instance_id

    # ---- 流转 ----
    def transition(self, instance_id: str, event: dict) -> StateResult:
        """应用事件流转。event 至少含 'type'（如 {'type': 'submit'}）。

        - escalate 事件：任意状态可转 escalate，StateResult.escalated=True。
        - 非法事件：保持在原状态（to_state==from_state）。
        - 'fail' 事件累加 retry_count（auto_fix 重试保护）。
        """
        inst = self._get(instance_id)
        event_type = event.get('type') or event.get('event') or ''
        spec = self._specs.get(inst['workflow']) or self._ensure_spec(inst['workflow'])
        states = spec.state_machine.get('states', {})
        from_state = inst['state']

        to_state = states.get(from_state, {}).get(event_type, from_state)
        escalated = to_state == _ESCALATE
        if event_type == 'fail':
            inst['retry_count'] = inst.get('retry_count', 0) + 1

        inst['state'] = to_state
        inst['history'].append((from_state, to_state, event))
        if self._storage == 'db':
            self._db_save(inst)
        return StateResult(
            from_state=from_state,
            to_state=to_state,
            retry_count=inst['retry_count'],
            escalated=escalated,
        )

    # ---- 查询 ----
    def get_state(self, instance_id: str) -> ReportStatus:
        """返回实例当前状态（ReportStatus 字面量）。"""
        inst = self._get(instance_id)
        return inst['state']  # type: ignore[return-value]

    def instances(self) -> list[str]:
        """返回全部实例 id（db 模式 = DB 全量 + 内存缓存并集）。"""
        if self._storage != 'db':
            return list(self._instances)
        seen = set(self._instances)
        seen.update(self._db_list())
        return list(seen)
