# -*- coding: utf-8 -*-
"""记忆量化评测（对齐 TencentDB-Agent-Memory 的 WideSearch/SWE-bench 收益度量）。

三个可量化维度：
1. 检索命中率 Recall@K：给定 query-gold 对，测 episodic 混合检索的命中比例；
2. 任务压缩收益：offload + 窗口压缩带来的字符/token 减少率（对应官方 token −61%）；
3. 技能复用命中率：给定任务描述，测 best_match 是否命中对应技能。

CLI 用法：
    python -m src.memory.bench                # 跑内置示例集（离线可用）
    python -m src.memory.bench --json runtime/bench/report.json

返回结构化报告（dict），各维度独立 try/except，单维度失败不影响整体。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# 内置示例评测集：真实库为空时也能跑通
_SAMPLE_RETRIEVAL = [
    ("GB/T 14691 标准中的表头字号要求", ["14691"]),
    ("焚烧炉运行温度限值", ["焚烧", "温度"]),
    ("烟气排放监测频次要求", ["监测", "频次"]),
]
_SAMPLE_SKILLS = [
    ("解读一份新的环保排放标准", "标准解读"),
    ("查询某标准的废止情况", "废止"),
    ("将聊天记录导出为报告", "报告"),
]

_TOKEN_RATIO = 1.5  # 中文粗略估算：字符数 / 1.5 ≈ token 数


def _est_tokens(text: str) -> int:
    return max(1, int(len(text or '') / _TOKEN_RATIO))


def bench_retrieval(cases: list[tuple[str, list[str]]] | None = None, top_k: int = 5) -> dict:
    """检索命中率：cases = [(query, [gold 关键词])]。任一 gold 出现在 top_k 即命中。"""
    cases = cases or _SAMPLE_RETRIEVAL
    try:
        from src.memory.episodic import EpisodicMemory
        mem = EpisodicMemory()
    except Exception:
        return {'suite': 'retrieval', 'ok': False, 'recall@k': 0.0,
                'total': len(cases), 'hit': 0, 'error': 'episodic 不可用'}
    hit = 0
    details = []
    for q, golds in cases:
        try:
            rows = mem.query(q, top_k=top_k, mode='hybrid')
            blob = ' '.join(str(getattr(r, 'entity', '')) + ' ' + str(getattr(r, 'event', ''))
                            for r in rows)
            ok = any(g in blob for g in golds)
        except Exception:
            ok = False
        if ok:
            hit += 1
        details.append({'query': q, 'gold': golds, 'hit': ok})
    return {'suite': 'retrieval', 'ok': True, 'recall@k': round(hit / len(cases), 3),
            'total': len(cases), 'hit': hit, 'details': details}


def bench_compression(msgs: list[dict] | None = None) -> dict:
    """任务压缩收益：offload 阈值内 + 窗口压缩后的 token 减少率。"""
    if not msgs:
        return {'suite': 'compression', 'ok': False, 'token_save': 0.0,
                'error': '无消息可测'}
    from src.memory import offload
    raw_tokens = _est_tokens(''.join(str(m.get('content') or '') for m in msgs))
    # 先 offload 卸载长工具输出（阈内不动），再窗口压缩到 12000
    off = offload.offload_tool_outputs(0, msgs, dry_run=True)
    window = offload.summarize_window(off['compressed'], budget=12000)
    comp_tokens = _est_tokens(''.join(str(m.get('content') or '') for m in window))
    save = 0.0 if raw_tokens == 0 else round(1 - comp_tokens / raw_tokens, 3)
    return {'suite': 'compression', 'ok': True, 'token_save': save,
            'raw_tokens': raw_tokens, 'comp_tokens': comp_tokens,
            'msg_count': len(msgs), 'kept': len(window)}


def bench_skill_reuse(tasks: list[tuple[str, str]] | None = None) -> dict:
    """技能复用命中率：tasks = [(任务描述, 期望技能关键词)]。"""
    tasks = tasks or _SAMPLE_SKILLS
    try:
        from src.memory.procedural import ProceduralMemory
        pm = ProceduralMemory()
    except Exception:
        return {'suite': 'skill_reuse', 'ok': False, 'hit_rate': 0.0,
                'total': len(tasks), 'hit': 0, 'error': 'procedural 不可用'}
    hit = 0
    details = []
    for task, gold in tasks:
        try:
            s = pm.best_match(task)
            ok = bool(s) and gold in (s.name or '') + (s.definition or '')
        except Exception:
            ok = False
        if ok:
            hit += 1
        details.append({'task': task, 'gold': gold, 'hit': ok})
    return {'suite': 'skill_reuse', 'ok': True,
            'hit_rate': round(hit / len(tasks), 3),
            'total': len(tasks), 'hit': hit, 'details': details}


def run_benchmark() -> dict:
    """汇总三个维度评测，输出结构化报告。"""
    report = {
        'benchmark': 'EA Memory Suite',
        'dimensions': [
            bench_retrieval(),
            bench_compression(),
            bench_skill_reuse(),
        ],
    }
    report['summary'] = {
        'retrieval_recall@k': report['dimensions'][0].get('recall@k', 0.0),
        'compression_token_save': report['dimensions'][1].get('token_save', 0.0),
        'skill_hit_rate': report['dimensions'][2].get('hit_rate', 0.0),
    }
    return report


def main() -> int:
    """CLI 入口：python -m src.memory.bench [--json path]"""
    import argparse

    ap = argparse.ArgumentParser(description='EA 记忆量化评测')
    ap.add_argument('--json', default='', help='输出 JSON 报告路径')
    args = ap.parse_args()
    report = run_benchmark()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'报告已写入: {p}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
