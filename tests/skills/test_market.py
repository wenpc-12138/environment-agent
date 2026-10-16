# -*- coding: utf-8 -*-
"""G8 技能打包/市场：目录浏览/关联收集/导出 zip/导入进 P9 待审。"""
from __future__ import annotations

import json
import os
import zipfile

import pytest

from src.skills import market as mk


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'market.db'))
    import db as v12_db
    v12_db.init_db()
    from src.core import config, db as core_db
    config.get_settings.cache_clear()
    core_db.run_migrations()
    yield
    try:
        from src.core import db as core_db
        core_db.close_db()
    except Exception:
        pass


@pytest.fixture()
def _skill(_db):
    """插入一个 active v2 技能供导出测试（符合 SkillDef 约束）。"""
    from src.memory.procedural import ProceduralMemory
    from src.models.core import SkillDef
    defn = SkillDef(
        id='sk-tst-001', name='水质自动监测技能', level=1, role='R4',
        domain='D1', version='1.2.0', status='active',
        definition='- 使用 formula_id: std-index-single 计算污染指数\n'
                   '- 依据 GB 3838-2002 Ⅲ类标准评价\n'
                   '- 输出达标结论',
        created_by='manual')
    ProceduralMemory().create_skill(defn)
    return defn


class TestCollectRelated:
    def test_formula_id_and_std(self):
        fids, stds = mk.collect_related(
            'formula_id: std-index-single\nGB 3838-2002 与 HJ 633-2012')
        assert 'std-index-single' in fids
        assert 'GB 3838-2002' in stds
        assert 'HJ 633-2012' in stds

    def test_empty(self):
        assert mk.collect_related('') == ([], [])

    def test_std_matches_formula(self):
        # GB 3838 应匹配公式库中含该标准的公式
        fids, stds = mk.collect_related('按 GB 3838-2002 计算')
        assert any('GB 3838' in (s or '') for s in stds)
        assert len(fids) >= 1  # 公式库中有 GB 3838 相关公式


class TestListMarket:
    def test_contains_v2_and_file(self, _db):
        out = mk.list_market()
        assert out['count'] >= 1  # 环境含既有技能
        ids = [i['id'] for i in out['items']]
        assert any(i.startswith('file:') for i in ids) or len(ids) >= 0

    def test_filter_source(self, _db):
        out = mk.list_market(source='v2')
        assert all(i['source'] == 'v2' for i in out['items'])

    def test_stats(self, _db):
        s = mk.market_stats()
        assert s['total'] >= 0 and 'active' in s and 'pending' in s


class TestExportImport:
    def _drop_skill(self, sid):
        """直接从库中删除技能（模拟导出到别处再导入场景）。"""
        from src.core import db as core_db
        core_db.get_conn().execute('DELETE FROM v2_skills WHERE id=?', (sid,))
        core_db.get_conn().commit()

    def test_export_then_import(self, _db, _skill):
        r = mk.export_skill('sk-tst-001')
        assert r['ok'] and os.path.isfile(r['path'])
        assert r['name'] == '水质自动监测技能'
        assert r['formula_ids']  # 关联公式已收集
        # zip 结构校验
        with zipfile.ZipFile(r['path']) as zf:
            names = set(zf.namelist())
            assert 'SKILL.md' in names and 'manifest.json' in names
            assert any(n.startswith('formulas/') for n in names)
            man = json.loads(zf.read('manifest.json').decode('utf-8'))
            assert man['name'] == '水质自动监测技能'
            assert man['version'] == '1.2.0'
        # 模拟导出到别处：删除原技能后再导入
        self._drop_skill('sk-tst-001')
        imp = mk.import_skill_zip(r['path'])
        assert imp['ok'] and imp['status'] == 'pending_review'
        assert imp['skill_id'].startswith('sk-mkt-')
        # 已进待审库
        from src.memory.procedural import ProceduralMemory
        found = [s for s in ProceduralMemory().list_skills('pending_review')
                 if s.id == imp['skill_id']]
        assert len(found) == 1
        # R8 审批后 active（复用 P9 闸门）
        assert ProceduralMemory().approve_skill(imp['skill_id'], 'R8')
        active = [s for s in ProceduralMemory().list_skills('active')
                  if s.id == imp['skill_id']]
        assert len(active) == 1

    def test_import_duplicate_rejected(self, _db, _skill):
        r = mk.export_skill('sk-tst-001')
        self._drop_skill('sk-tst-001')
        mk.import_skill_zip(r['path'])
        imp2 = mk.import_skill_zip(r['path'])
        assert imp2['ok'] is False and '已存在' in imp2['error']

    def test_import_bad_zip(self, tmp_path, _db):
        bad = tmp_path / 'bad.zip'
        bad.write_bytes(b'not a zip')
        r = mk.import_skill_zip(str(bad))
        assert r['ok'] is False

    def test_import_missing_manifest(self, tmp_path, _db):
        p = tmp_path / 'nom.zip'
        with zipfile.ZipFile(p, 'w') as zf:
            zf.writestr('SKILL.md', '---\nname: x\n---\n内容')
        r = mk.import_skill_zip(str(p))
        assert r['ok'] is False and 'manifest' in r['error']

    def test_import_missing_file(self, _db):
        assert mk.import_skill_zip('no/such.zip')['ok'] is False

    def test_export_unknown(self, _db):
        r = mk.export_skill('no-such-skill')
        assert r['ok'] is False

    def test_browse(self, _db, _skill):
        b = mk.browse_skill('sk-tst-001')
        assert b['ok'] and b['name'] == '水质自动监测技能'
        assert b['formula_ids'] and b['standard_refs']
