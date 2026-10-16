# -*- coding: utf-8 -*-
"""Wiki 知识资产：创建 / 检索 / 更新 / 删除 / 资产联动。"""
from __future__ import annotations

import pytest

from src.core import config, db as core_db
from src.memory import wiki


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'wiki.db'))
    config.get_settings.cache_clear()
    core_db.run_migrations()
    yield


class TestWiki:
    def test_create_and_get(self, _db):
        wid = wiki.create_wiki('限值速查', content='GB 16297-1996 颗粒物 120mg/m3', tags='限值,标准')
        assert wid
        w = wiki.get_wiki(wid)
        assert w['title'] == '限值速查'
        assert '120mg' in w['content']

    def test_create_empty_title_rejected(self, _db):
        assert wiki.create_wiki('   ') == ''

    def test_create_registers_asset(self, _db):
        wid = wiki.create_wiki('采样方法', content='HJ/T 373', visibility='team')
        row = core_db.get_conn().execute(
            'SELECT * FROM memory_assets WHERE asset_id=?', (f'wiki:{wid}',)).fetchone()
        assert row and row['asset_type'] == 'wiki' and row['visibility'] == 'team'

    def test_list_filter(self, _db):
        wiki.create_wiki('A 排放', content='废气', tags='废气')
        wiki.create_wiki('B 废水', content='水质', tags='水')
        all_ = wiki.list_wiki()
        assert len(all_) == 2
        hits = wiki.list_wiki(q='废')
        assert len(hits) == 2
        hits2 = wiki.list_wiki(q='水质')
        assert len(hits2) == 1 and hits2[0]['title'] == 'B 废水'

    def test_search_touches_count(self, _db):
        wid = wiki.create_wiki('监测频次', content='每季度一次')
        before = wiki.get_wiki(wid)['use_count']
        wiki.search_wiki('监测')
        after = wiki.get_wiki(wid)['use_count']
        assert after == before + 1

    def test_update_visibility(self, _db):
        wid = wiki.create_wiki('标签规范', content='旧内容')
        assert wiki.update_wiki(wid, content='新内容', visibility='agent')
        w = wiki.get_wiki(wid)
        assert w['content'] == '新内容' and w['visibility'] == 'agent'

    def test_delete_removes_asset(self, _db):
        wid = wiki.create_wiki('待删条目')
        assert wiki.delete_wiki(wid)
        assert wiki.get_wiki(wid) is None
        row = core_db.get_conn().execute(
            'SELECT * FROM memory_assets WHERE asset_id=?', (f'wiki:{wid}',)).fetchone()
        assert row is None

    def test_delete_missing(self, _db):
        assert not wiki.delete_wiki('wiki-9999')
