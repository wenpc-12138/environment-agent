# -*- coding: utf-8 -*-
"""M09 工作流 YAML 加载器（contracts.md §3.M09）。

YAML 状态机格式（EA_v2_Design Part 12.3 语义）：
```yaml
name: report_pipeline
trigger: auto_router
initial: drafting
states:
  drafting: {submit: review, escalate: escalate}
  ...
```
"""
from __future__ import annotations

from pathlib import Path

from ..models.core import WorkflowSpec

REQUIRED_KEYS = ('name', 'trigger', 'states')


def load_yaml_spec(yaml_path: str) -> WorkflowSpec:
    """读取 YAML 文件并校验结构，返回 WorkflowSpec。"""
    import yaml

    p = Path(yaml_path)
    if not p.is_file():
        raise FileNotFoundError(f'状态机文件不存在: {yaml_path}')
    raw = yaml.safe_load(p.read_text(encoding='utf-8'))
    if not isinstance(raw, dict):
        raise ValueError(f'状态机 YAML 顶层须为映射: {yaml_path}')
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        raise ValueError(f'状态机 YAML 缺少字段 {missing}: {yaml_path}')
    states = raw['states']
    if not isinstance(states, dict) or not states:
        raise ValueError(f'状态机 YAML states 须为非空映射: {yaml_path}')
    if 'initial' not in raw and 'drafting' not in states:
        raise ValueError(f'状态机缺少 initial 且无 drafting 状态: {yaml_path}')
    return WorkflowSpec(
        name=str(raw['name']),
        trigger=str(raw['trigger']),
        state_machine={
            'initial': raw.get('initial', 'drafting'),
            'states': states,
        },
    )
