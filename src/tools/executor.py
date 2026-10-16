# -*- coding: utf-8 -*-
"""M04 工具执行器（ToolExecutor，contracts.md §3.M04）。

包装 `ToolRegistry` + v1.2 `execute_tool`，提供带 trace 的执行入口：
`run(name, params)` -> `ToolResult`；`run_sequence(steps)` 顺序执行并记录每步 trace。
"""
from __future__ import annotations

from .registry import ToolRegistry, ToolResult


class ToolExecutor:
    """工具执行器：单步执行 + 顺序编排。"""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or ToolRegistry()
        self.traces: list[dict] = []

    def run(self, name: str, params: dict | None = None) -> ToolResult:
        result = self.registry.execute(name, params or {})
        self.traces.append({'tool': name, 'trace_id': result.trace_id, 'ok': result.ok})
        return result

    def run_sequence(self, steps: list[dict]) -> list[ToolResult]:
        """顺序执行工具步骤（M03 工具编排的最小 DAG 形态）。

        steps 形如 [{"tool": "kb_lookup", "params": {...}}, ...]；
        每步 params 中的 ``$prev`` 引用会被上一步 data 替换。
        """
        results: list[ToolResult] = []
        for step in steps:
            params = dict(step.get('params') or {})
            prev = results[-1] if results else None
            if prev is not None and '$prev' in params:
                params['$prev'] = prev.data
            results.append(self.run(step.get('tool', ''), params))
        return results
