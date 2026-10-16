# -*- coding: utf-8 -*-
"""pytest 全局配置：项目根加入 sys.path，保证 import src.* 可用。"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _build_schema(db_file: str) -> None:
    """在指定库上建 v1.2 schema 并跑完 v2.0 全部迁移（幂等）。"""
    from src.core import config
    from src.core import db as core_db
    from src.core.db_v12 import base as v12_base

    v12_base.close_db()
    core_db.close_db()
    config.get_settings.cache_clear()
    v12_base.init_db()
    core_db.run_migrations()
    v12_base.close_db()
    core_db.close_db()
    config.get_settings.cache_clear()


@pytest.fixture(scope='session')
def _db_template(tmp_path_factory) -> Path:
    """会话级「模板库」：一次性建好完整 schema + 迁移，供每个用例复制。

    这样每个用例都拿到一个结构完整但内容干净的独立库，既不依赖真实
    `data/ecoagent.db`，也不必为每个用例重跑一遍迁移（811 用例只建一次）。
    """
    from src.core import config
    from src.core.db_v12 import base as v12_base

    path = tmp_path_factory.mktemp('dbtpl') / 'ecoagent.db'
    old_env = os.environ.get('ECOAGENT_DB')
    old_path = v12_base.DB_PATH
    os.environ['ECOAGENT_DB'] = str(path)
    v12_base.DB_PATH = str(path)
    config.get_settings.cache_clear()
    try:
        _build_schema(str(path))
    finally:
        if old_env is None:
            os.environ.pop('ECOAGENT_DB', None)
        else:
            os.environ['ECOAGENT_DB'] = old_env
        v12_base.DB_PATH = old_path
        config.get_settings.cache_clear()
    return path


@pytest.fixture(autouse=True)
def _isolate_databases(tmp_path, monkeypatch, _db_template):
    """把两层数据层都指向临时库，确保测试**绝不触碰**真实 `data/ecoagent.db`。

    背景（真实事故）：v1.2 数据层（`src/core/db_v12`）的 `DB_PATH` 是 import 时
    确定的模块级常量，只在测试里设置 `ECOAGENT_DB` 环境变量对它无效。历史上因此
    让 `tests/kb/test_kb_fts_trigram.py` 的 `DELETE FROM kb_entries` 直接删掉了
    真实库的知识库条目（用户数据丢失，需从备份恢复）。

    做两件事：
    1. 每个用例复制一份「结构完整、内容干净」的临时库（见 `_db_template`）；
    2. 同时改写 `v12_base.DB_PATH` 与 `ECOAGENT_DB`，覆盖 v1.2 / v2.0 两层。

    用例若自行指定数据库（再 patch DB_PATH），其设置优先级更高。
    """
    from src.core import config
    from src.core.db_v12 import base as v12_base

    tmp_db = tmp_path / 'ecoagent.db'
    shutil.copyfile(_db_template, tmp_db)
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_db))
    monkeypatch.setattr(v12_base, 'DB_PATH', str(tmp_db), raising=False)
    config.get_settings.cache_clear()
    v12_base.close_db()
    yield
    # 关闭线程本地连接，防止残留连接串库（M01），并还原配置缓存
    v12_base.close_db()
    from src.core import db as core_db

    core_db.close_db()
    config.get_settings.cache_clear()
