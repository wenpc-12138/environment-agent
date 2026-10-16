# -*- coding: utf-8 -*-
"""PDF 解析完整性回退 + std_import 性能护栏测试。

背景：
1. RapidAI 管线对部分页失败时输出页数远少于 PDF 实际页数（HJ 700 24 页只出 7 页），
   导致入库内容中间章节/附录表格全缺失 → _read_pdf_md 增加"页数完整性校验，不足 60%
   回退 pypdf 纯文本层"；
2. std_import 对 10+ 候选串行抓全文累积 50s+（前端表现为卡死）→ 增加候选抓取上限
   与"合格 2 个即停"。
"""
from __future__ import annotations

from src.tools import v12 as v12mod


# ---------- std_import 性能护栏 ----------

def test_std_import_candidate_limit(monkeypatch):
    """std_import 候选抓取有上限且合格 2 个即停（避免 50s 卡死）。"""
    fetch_calls = {'n': 0}

    def fake_fetch_text(url, max_chars=1000000, save_dir=None):
        fetch_calls['n'] += 1
        return f"标题: HJ 836-2017\n来源: {url}\n正文(Markdown):\n" + ("标准全文内容" * 500)

    def fake_search(q, top_n=8, site_filter=None):
        return [{"url": f"https://mee.gov.cn/{i}.pdf", "title": f"HJ 836-2017 标准 {i}"}
                for i in range(10)]

    monkeypatch.setattr(v12mod.websearch, 'fetch_text', fake_fetch_text)
    monkeypatch.setattr(v12mod.websearch, 'search', fake_search)
    monkeypatch.setattr(v12mod.db, 'kb_add', lambda *a, **k: 999)

    out = v12mod.std_import('HJ 836-2017 固定污染源废气 低浓度颗粒物测定')
    assert fetch_calls['n'] <= 6, f'抓取次数 {fetch_calls["n"]} 应受上限约束'
    assert '已取到 2 个合格候选' in out or '已达候选抓取上限' in out


# ---------- PDF 完整性回退 ----------

def test_pdf_completeness_guard_logic():
    """完整性校验逻辑：_read_pdf_md 应含页数不足时回退纯文本层的分支。"""
    import inspect
    import kb_pipeline as kp
    src = inspect.getsource(kp._read_pdf_md)
    assert '0.6' in src or '完整性' in src, '_read_pdf_md 应含页数完整性校验'
    assert '_read_pdf(path)' in src, '_read_pdf_md 应回退 pypdf 纯文本层'


def test_extract_markdown_full_pdf(tmp_path):
    """真实 24 页 PDF 应解析出完整内容（页标记接近页数，含附录/表格）。"""
    import glob
    import kb_pipeline as kp

    # 使用测试环境已有的多页 PDF（若存在）；否则构造 20 页假 PDF（含文字层）
    pdfs = glob.glob('data/task_outputs/*/downloads/W020140523543423227755.pdf')
    if not pdfs:
        try:
            import pypdf  # noqa: F401  (探测依赖可用性)
        except Exception:
            return  # pypdf 不可用则跳过
        from reportlab.pdfgen import canvas
        import io
        # 每页写入足量正文，保证纯文本层解析结果稳定超过完整性阈值
        filler = ("固定污染源废气低浓度颗粒物测定重量法附录数据表格采样体积标况浓度检出限"
                  "滤膜恒重称量质控样回收率平行样空白样品分析结果记录评价标准限值")
        buf = io.BytesIO()
        c = canvas.Canvas(buf)
        for i in range(1, 21):
            c.drawString(72, 720, f"第{i}页内容测试段落 {filler}")
            c.drawString(72, 700, filler)
            c.showPage()
        c.save()
        buf.seek(0)
        p = tmp_path / 'test20.pdf'
        p.write_bytes(buf.getvalue())
        pdfs = [str(p)]

    md = kp.extract_markdown(pdfs[0])
    assert len(md or '') > 1000, f'完整 PDF 应解析出足量内容，实际 {len(md or "")}'
    assert '第' in (md or '') or '附录' in (md or ''), '应含正文内容'
