# -*- coding: utf-8 -*-
"""M05 MemoryManager：三层记忆统一入口（working / episodic / procedural）。"""
from __future__ import annotations

from .episodic import EpisodicMemory
from .procedural import ProceduralMemory
from .working import WorkingMemory


class MemoryManager:
    """统一记忆入口：组合三层记忆实例，供 Agent 主循环调用。"""

    # 契约 §3.M05：类级声明三实例（hasattr 契约测试要求类属性存在）
    working: WorkingMemory | None = None
    episodic: EpisodicMemory | None = None
    procedural: ProceduralMemory | None = None

    def __init__(self, summarizer=None) -> None:
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory(summarizer=summarizer)
        self.procedural = ProceduralMemory()

    def remember(self, entity: str, event: str, payload: dict | None = None) -> str:
        """便捷方法：写入一条情景记忆。"""
        return self.episodic.add(entity=entity, event=event, payload=payload)

    def recall(self, q: str, top_k: int = 10) -> list:
        """便捷方法：检索情景记忆。"""
        return self.episodic.query(q=q, top_k=top_k)
