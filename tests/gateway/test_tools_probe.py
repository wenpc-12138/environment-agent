# -*- coding: utf-8 -*-
"""回归护栏：pytest prepend 模式下 `import tools` 会被 tests/tools 空包劫持，
v1.2 工具表须经 src.tools._v12 独立加载（绝对路径）拿到根 tools.py。"""

from src.tools import _v12


def test_v12_loader_resolves_root_tools():
    mod = _v12.load()
    assert mod is not None
    # 根 tools.py 而非 tests/tools 空包
    assert 'tests' not in (getattr(mod, '__file__', '') or '')
    assert hasattr(mod, 'TOOL_SCHEMAS')
    assert hasattr(mod, 'execute_tool')
    assert len(_v12.get_tool_schemas()) > 0


def test_v12_execute_delegates():
    ok, out = _v12.execute_tool('calc_formula', {})
    assert isinstance(ok, bool) and isinstance(out, str)


def test_v12_loader_cached():
    assert _v12.load() is _v12.load()
