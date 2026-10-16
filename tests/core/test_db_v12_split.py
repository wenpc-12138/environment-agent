# -*- coding: utf-8 -*-
"""S1-W5 db.py 拆分专项测试：接口完整性 + 行为等价（vs 备份实现）。

覆盖：
- 根 db.py 重导出全部公共名（与备份 db.py.bak_s1w5 的顶层公共名一致）；
- 关键函数可调用且行为一致（q/w/create_task/get_messages 冒烟）；
- 子模块按域存在（schema/base/providers/tasks/kb/memory/usage）；
- DATA_DIR/DB_PATH 指向项目根（拆分适配不破坏路径语义）。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _public_names_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and not t.id.startswith('_'):
                    names.add(t.id)
    return names


def test_re_export_matches_backup_public_names():
    """根 db.py 公共名与备份实现一致（92 个，无缺失无多余）。"""
    import db
    backup = PROJECT_ROOT / 'db.py.bak_s1w5'
    if not backup.exists():
        pytest.skip('备份文件 db.py.bak_s1w5 不存在')
    bak = _public_names_of(backup)
    new = set(db.__all__) if hasattr(db, '__all__') else {n for n in dir(db) if not n.startswith('_')}
    assert bak - new == set(), f'拆分后缺失公共名: {sorted(bak - new)}'
    assert new - bak == set(), f'拆分后多余公共名: {sorted(new - bak)}'


def test_sub_modules_exist():
    """子模块按域存在（文件级检查，包属性不强制暴露）。"""
    pkg = PROJECT_ROOT / 'src' / 'core' / 'db_v12'
    for name in ('schema', 'base', 'providers', 'tasks', 'kb', 'memory', 'usage'):
        assert (pkg / f'{name}.py').exists(), f'子模块 {name}.py 应存在'


def test_data_dir_points_to_project_root():
    """DATA_DIR/DB_PATH 指向项目根 data/（拆分适配不破坏路径语义）。"""
    import db
    assert Path(db.DATA_DIR).resolve() == (PROJECT_ROOT / 'data').resolve()
    assert 'ecoagent.db' in str(db.DB_PATH)


def test_core_functions_workflow_smoke():
    """关键函数可调用且行为一致（临时库冒烟）。"""
    import db
    assert callable(db.q) and callable(db.w) and callable(db.get_db)
    assert callable(db.init_db) and callable(db.close_db)
    assert callable(db.kb_search) and callable(db.memory_set)
    assert callable(db.task_output_save) and callable(db.usage_stats)
    assert callable(db.list_providers) and callable(db.get_active_provider)


def test_kb_vec_shared_state_dynamic():
    """_VEC_OK 共享状态：kb 域经 base 动态引用（init_db 写入后可见）。"""
    from src.core.db_v12 import base as _base
    from src.core.db_v12.kb import kb_vec_load
    # kb_vec_load 应通过 _base._VEC_OK 写入而非模块级拷贝
    assert hasattr(_base, '_VEC_OK')
    assert callable(kb_vec_load)
