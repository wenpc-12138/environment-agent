# -*- coding: utf-8 -*-
"""M04 工具注册表（ToolRegistry，contracts.md §3.M04）。

- `ToolSpec`：工具规格（id/name/capability/input_schema/output_schema/sandbox）。
- `ToolResult`：统一执行结果（ok/data/error/trace_id）。
- `ToolRegistry`：register / execute / list；从 v1.2 `tools.TOOL_SCHEMAS` 动态重铸
  存量工具（双轨共存，零迁移），同时支持注册本地方可调用 handler。

设计对齐 ADR-010/ADR-011：懒加载 v1.2 工具表，测试/离线环境无 v1.2 模块也能独立运行。
"""
from __future__ import annotations

import uuid
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

_CAPABILITY_PREFIX = {
    'kb_': 'kb', 'locate': 'kb', 'std_': 'kb', 'query_std': 'kb',
    'web_': 'web', 'searxng': 'web', 'http_': 'web',
    'mem_': 'memory', 'memory_': 'memory',
    'skill_': 'skill',
    'report_': 'report', 'gen_report': 'report',
}


def _infer_capability(name: str) -> str:
    for prefix, cap in _CAPABILITY_PREFIX.items():
        if name.startswith(prefix):
            return cap
    return 'misc'


class ToolSpec(BaseModel):
    """工具规格（契约 §3.M04）。"""

    model_config = ConfigDict(str_strip_whitespace=True, arbitrary_types_allowed=True)

    id: str
    name: str = ''
    description: str = ''
    capability: str = 'misc'  # kb | web | memory | skill | report | misc
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    sandbox: str = 'none'  # none | local | container
    handler: Callable | str | None = None  # 可调用对象或 v1.2 工具名


class ToolResult(BaseModel):
    """工具执行结果（契约 §3.M04）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    ok: bool
    data: Any = None
    error: str = ''
    trace_id: str = ''


class ToolRegistry:
    """工具注册与执行。"""

    def __init__(self, load_v12: bool = True) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._loaded_v12 = False
        if load_v12:
            self.list()  # 预热 v1.2 重铸（幂等）

    # -- 注册 -----------------------------------------------------------
    def register(self, tool: ToolSpec | dict | Callable) -> str:
        """注册工具（ToolSpec / 原始 dict / handler 可调用对象），返回 id。"""
        if isinstance(tool, ToolSpec):
            spec = tool
        elif isinstance(tool, dict):
            spec = ToolSpec(
                id=tool.get('id') or tool.get('name', ''),
                name=tool.get('name') or tool.get('id', ''),
                description=tool.get('description', ''),
                capability=tool.get('capability') or _infer_capability(str(tool.get('name', ''))),
                input_schema=tool.get('input_schema') or tool.get('parameters', {}),
                output_schema=tool.get('output_schema', {}),
                sandbox=tool.get('sandbox', 'none'),
                handler=tool.get('handler'),
            )
        else:
            spec = ToolSpec(id=tool.__name__, name=tool.__name__,
                            capability=_infer_capability(tool.__name__), handler=tool)
        spec.name = spec.name or spec.id
        spec.id = spec.id or spec.name
        self._specs[spec.id] = spec
        return spec.id

    def get(self, tool_id: str) -> ToolSpec | None:
        self._load_v12_schemas()
        return self._specs.get(tool_id)

    # -- 执行 -----------------------------------------------------------
    def execute(self, tool_id: str, params: dict | None = None) -> ToolResult:
        """执行工具，返回 ToolResult（含 trace_id）。"""
        trace_id = uuid.uuid4().hex[:12]
        spec = self.get(tool_id)
        if spec is None:
            return ToolResult(ok=False, data=None, error=f'未知工具: {tool_id}', trace_id=trace_id)
        handler = spec.handler
        try:
            if callable(handler):
                out = handler(params or {})
            else:
                out = self._call_v12(spec.id, params or {})
            if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], bool):
                ok, data = out
            else:
                ok, data = True, out
            return ToolResult(ok=ok, data=data, trace_id=trace_id)
        except Exception as exc:  # noqa: BLE001 工具边界统一捕获
            return ToolResult(ok=False, data=None, error=f'{type(exc).__name__}: {exc}', trace_id=trace_id)

    # -- 列表 -----------------------------------------------------------
    def list(self, capability: str | None = None) -> list[ToolSpec]:
        self._load_v12_schemas()
        specs = list(self._specs.values())
        if capability:
            specs = [s for s in specs if s.capability == capability]
        return specs

    # -- v1.2 双轨重铸 ------------------------------------------------
    def _load_v12_schemas(self) -> None:
        if self._loaded_v12:
            return
        self._loaded_v12 = True
        try:
            import tools as v12_tools  # v1.2 顶层模块

            for raw in getattr(v12_tools, 'TOOL_SCHEMAS', []) or []:
                fn = (raw or {}).get('function') or {}
                name = fn.get('name')
                if not name or name in self._specs:
                    continue
                self._specs[name] = ToolSpec(
                    id=name,
                    name=name,
                    description=fn.get('description', ''),
                    capability=_infer_capability(name),
                    input_schema=fn.get('parameters', {}) or {},
                    sandbox='none',
                )
        except Exception:
            pass  # 无 v1.2 模块时保持空注册表

    @staticmethod
    def _call_v12(name: str, params: dict) -> Any:
        import tools as v12_tools  # v1.2 顶层模块

        ok, out = v12_tools.execute_tool(name, params)
        return ok, out
