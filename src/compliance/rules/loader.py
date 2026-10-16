# -*- coding: utf-8 -*-
"""M12 CMA 规则包加载（UPGRADE_PLAN §M12：先以 YAML 规则静态实现）。

规则语义见 cma_rules.yaml 头部注释；`load_rules()` 返回规则 dict 列表，
外部可通过 `load_rules(path)` 覆盖规则包（企业定制）。
"""
from __future__ import annotations

from pathlib import Path

import yaml

_DEFAULT_PATH = Path(__file__).with_name('cma_rules.yaml')


def load_rules(path: str | Path | None = None) -> list[dict]:
    """加载规则包；路径非法或 YAML 异常时降级返回空列表（不阻断检查）。"""
    p = Path(path) if path else _DEFAULT_PATH
    try:
        data = yaml.safe_load(p.read_text(encoding='utf-8'))
    except Exception:
        return []
    rules = data.get('rules') if isinstance(data, dict) else None
    return [r for r in (rules or []) if isinstance(r, dict) and r.get('id')]


def rules_path() -> str:
    return str(_DEFAULT_PATH)


__all__ = ['load_rules', 'rules_path']
