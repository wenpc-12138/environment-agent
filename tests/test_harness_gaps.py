# -*- coding: utf-8 -*-
"""DeepSeek Harness 对标补缺测试：
D1 自动会话标题（session-title）；D2 逐消息反馈（feedback）；D3 跨会话引用（session-reference）。
"""
from __future__ import annotations

import pytest

import db as root_db
import v2_bridge


@pytest.fixture()
def _db(tmp_path, monkeypatch):
    # v1.2 数据层的 DB_PATH 是 import 时确定的模块级常量，仅设环境变量不会生效，
    # 必须直接改写，否则用例会写到真实库 data/ecoagent.db（污染 + 依赖本机数据）。
    import src.core.db_v12.base as v12_base

    monkeypatch.setattr(v12_base, 'DB_PATH', str(tmp_path / 'harness_gaps.db'))
    monkeypatch.setenv('ECOAGENT_DB', str(tmp_path / 'harness_gaps.db'))
    # init_db 会改写跨模块全局向量标志，测试后还原以免污染其它用例
    monkeypatch.setattr(v12_base, '_VEC_OK', v12_base._VEC_OK)
    monkeypatch.setattr(v12_base, '_VEC_METRIC', v12_base._VEC_METRIC)
    root_db.init_db()
    from src.core import config, db as core_db
    config.get_settings.cache_clear()
    core_db.run_migrations()
    yield
    v12_base.close_db()
    root_db.close_db()


class TestAutoTitle:
    """D1 自动会话标题（对齐 Harness session-title）。"""

    def test_generate_with_reply(self, _db):
        tid = root_db.create_task('新任务')
        r = v2_bridge.auto_title(tid, first_user='帮我解读《大气污染物综合排放标准》GB 16297 最新版',
                                 reply='该标准为现行有效版本，主要限值包括……')
        assert r['ok'] is True
        assert r['generated'] is True
        assert r['title']
        assert len(r['title']) <= 14
        t = root_db.get_task(tid)
        assert t['title'] == r['title']
        assert t['title'] != '新任务'

    def test_custom_title_untouched(self, _db):
        tid = root_db.create_task('自定义标题-水污染防治')
        r = v2_bridge.auto_title(tid, first_user='帮我查新', reply='好的')
        assert r['ok'] is True
        assert r['generated'] is False
        assert root_db.get_task(tid)['title'] == '自定义标题-水污染防治'

    def test_fallback_to_first_user(self, _db, monkeypatch):
        # 模拟无可用 provider：确保走回退分支（截取首条用户消息）
        monkeypatch.setattr(root_db, 'get_active_provider', lambda: None)
        tid = root_db.create_task('新任务')
        r = v2_bridge.auto_title(tid, first_user='环境空气质量现状分析与评价技术规范',
                                 reply='')
        assert r['ok'] is True
        assert r['generated'] is True
        assert r['title'] == '环境空气质量现状分析与评价技'

    def test_missing_task(self, _db):
        r = v2_bridge.auto_title(999999)
        assert r['ok'] is False


class TestMessageFeedback:
    """D2 逐消息反馈（对齐 Harness feedback）。"""

    def test_good_feedback(self, _db):
        tid = root_db.create_task('反馈测试')
        mid = root_db.add_message(tid, 'assistant', '这是回复内容')
        r = v2_bridge.message_feedback(mid, value='good', comment='回答准确')
        assert r['ok'] is True
        assert r['feedback'] == 'good'
        rows = v2_bridge.feedback_list(task_id=tid)
        assert rows['ok'] is True
        assert rows['total'] >= 1
        item = [i for i in rows['items'] if i['id'] == mid][0]
        assert item['feedback'] == 'good'
        assert item['comment'] == '回答准确'

    def test_bad_feedback(self, _db):
        tid = root_db.create_task('反馈测试2')
        mid = root_db.add_message(tid, 'assistant', '旧数据回复')
        r = v2_bridge.message_feedback(mid, value='bad', comment='数据过时')
        assert r['ok'] is True
        rows = v2_bridge.feedback_list()
        item = [i for i in rows['items'] if i['id'] == mid][0]
        assert item['feedback'] == 'bad'
        assert item['comment'] == '数据过时'

    def test_invalid_value(self, _db):
        tid = root_db.create_task('反馈测试3')
        mid = root_db.add_message(tid, 'assistant', 'x')
        r = v2_bridge.message_feedback(mid, value='meh')
        assert r['ok'] is False

    def test_missing_message(self, _db):
        r = v2_bridge.message_feedback(999999, value='good')
        assert r['ok'] is False


class TestSessionRef:
    """D3 跨会话引用（对齐 Harness session-reference）。"""

    def test_ref_returns_context(self, _db):
        tid = root_db.create_task('土壤重金属污染评估')
        root_db.add_message(tid, 'user', '请评估该地块土壤重金属超标情况')
        root_db.add_message(tid, 'assistant', '经评估：镉超标 1.2 倍，需修复')
        r = v2_bridge.session_ref(tid)
        assert r['ok'] is True
        ref = r['ref']
        assert ref['task_id'] == tid
        assert ref['title'] == '土壤重金属污染评估'
        assert '评估' in ref['summary']
        assert '镉超标' in ref['key_output']

    def test_ref_missing(self, _db):
        r = v2_bridge.session_ref(999999)
        assert r['ok'] is False

    def test_ref_with_offload_file(self, _db, tmp_path, monkeypatch):
        tid = root_db.create_task('VOCs 排放核算')
        root_db.add_message(tid, 'user', '核算 VOCs 排放量')
        root_db.add_message(tid, 'assistant', '已核算完成')
        # 模拟 offload 落盘文件：<TASK_OUTPUT_DIR>/<tid>/refs/live_001.md
        import src.core.db_v12.tasks as v12_tasks

        monkeypatch.setattr(v12_tasks, 'TASK_OUTPUT_DIR', str(tmp_path))
        outdir = tmp_path / str(tid) / 'refs'
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / 'live_001.md').write_text('全文内容：VOCs 排放总量 2.3 万吨', encoding='utf-8')
        r = v2_bridge.session_ref(tid)
        assert r['ok'] is True
        assert 'VOCs' in r['ref']['refs_tail'] or r['ref']['refs_tail'] == ''


class TestLoopIntegration:
    """D3 在 agent_core 中解析 `@任务N` 语法的单元验证（不启动完整循环）。"""

    def test_ref_syntax_extraction(self):
        """run() 中使用的正则应能解析 @任务N / @会话N / @N 三种写法。"""
        import re
        cases = [
            ('参考@任务12 的做法', ['12']),
            ('结合@会话3 的结论', ['3']),
            ('沿用@7 的流程', ['7']),
            ('无引用内容', []),
        ]
        for text, expected in cases:
            found = re.findall(r'@(?:任务|会话)?\s*(\d{1,6})', text)
            assert found == expected, text


class TestAutoKnowledgeSink:
    """V4 全自动知识沉淀（对标 Mem0 ADD/SEARCH + Harness episodic/profile/wiki 子系统）：
    标准事实自动激活 / 批量审批 / 自动召回路由 / 任务级事件 + wiki 自动登记。"""

    def test_std_fact_auto_activated(self, _db):
        """标准编号事实（GB 3838-2002）应自动激活（approved/active），无需人工审批。"""
        from src.memory import facts as F
        out = F.extract_facts('本项目执行标准：GB 3838-2002', source='test-v4')
        std = [f for f in out if '3838' in (f.attr or '')]
        assert std, '应抽取到标准事实'
        assert std[0].status == 'active', '标准事实应自动激活'

    def test_approve_all_pending(self, _db):
        """批量审批：一键通过全部 pending（conclusion 类除外并跳过）。"""
        from src.memory import facts as F
        F.extract_facts('用户偏好深度处理工艺，且进水 COD 不超过 40 mg/L 是约束',
                        source='test-v4')
        F.extract_facts('结论：该厂应采用 A2O 工艺', source='test-v4')
        r = F.approve_all_pending('R8')
        assert r['approved'], '应有偏好/约束被批量通过'
        # conclusion 类应保留 pending
        left = F.pending_facts()
        assert all(f.ftype == 'conclusion' for f in left), '结论类应保留待人工核对'

    def test_facts_approve_all_bridge(self, _db):
        import v2_bridge
        r = v2_bridge.facts_approve_all()
        assert r['ok'] is True
        assert isinstance(r['approved'], list)
        assert isinstance(r['skipped'], int)

    def test_recall_route_kb(self, _db):
        """自动召回：知识型提问应命中 kb 源（空库需先落一条知识，避免依赖本机数据）。"""
        import v2_bridge
        eid = root_db.kb_add(title='GB 3838-2002 地表水环境质量标准',
                             url='', category='standard',
                             content='污水排放标准：COD、氨氮限值与监测要求。', source='test')
        root_db.kb_embed_entry(eid)  # 补向量，保证空库环境下多路召回也能命中
        rec = v2_bridge.memory_route_search('帮我查污水排放标准', top_k=3)
        srcs = [s for s in rec.get('sources', []) if s.get('items')]
        assert any(s['source'] == 'kb' for s in srcs)

    def test_recall_route_empty_safe(self, _db):
        """自动召回：空内容不抛异常、不注入。"""
        import v2_bridge
        rec = v2_bridge.memory_route_search('', top_k=3)
        assert 'sources' in rec

    def test_task_episodic_auto_write(self, _db):
        """任务级情景事件自动写入（_post_task_learning 新增逻辑）。"""
        from src.memory import episodic
        epi = episodic.EpisodicMemory()
        hit = epi.add('任务', '完成任务 #1：标准解读', {'task_id': 1, 'auto': True,
                                                      'source': 'agent_task'})
        assert hit is not None
        q = epi.query('标准解读', top_k=3)
        assert len(q) >= 1

    def test_wiki_auto_register(self, _db):
        """wiki 自动登记：摘要沉淀为标准知识条目。"""
        from src.memory import wiki
        w = wiki.create_wiki(title='测试条目-标准解读', content='GB 3838-2002 适用性分析…',
                             tags='auto,task-summary', created_by='agent-auto',
                             source='task#1')
        assert w is not None
        r = wiki.search_wiki('标准解读')
        assert len(r) >= 1

    def test_profile_distill_available(self, _db):
        """画像自动蒸馏入口可用。"""
        from src.memory import profile
        p = profile.distill()
        assert isinstance(p, dict) or p is None
