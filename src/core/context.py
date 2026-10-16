# -*- coding: utf-8 -*-
"""生态Agent - 上下文管理:预算估算 / 窗口压缩 / 缓存记账口径

S2-M2 迁移（2026-08-20）：自根目录 `context_mgr.py` 原样迁入；
根文件已转兼容重导出（`from src.core.context import *`）。
"""

# 默认预算:未匹配到模型窗口时的回退值(等价 32k 模型)
SOFT_BUDGET = 22000
HARD_BUDGET = 30000
# 保留最近 N 条原始消息,更早的进入摘要
KEEP_RAW = 6

# 软/硬预算占模型上下文窗口的比例
# soft: 超出触发压缩(旧轮次摘要化); hard: 窗口留白,避免输出溢出
SOFT_RATIO = 0.7
HARD_RATIO = 0.9

# 模型上下文窗口表:key 按模型名小写子串匹配(长 key 优先),值 = 窗口 tokens
MODEL_CONTEXT_LENGTHS = {
    # DeepSeek V4 系列:1M 超长上下文
    "deepseek-v4": 1_000_000,
    # DeepSeek 其他
    "deepseek-v3": 64_000,
    "deepseek-r1": 64_000,
    "deepseek-chat": 128_000,
    "deepseek-reasoner": 128_000,
    # 智谱 GLM
    "glm-4.6": 200_000,
    "glm-4.5": 128_000,
    "glm-4-flash": 128_000,
    "glm-4": 128_000,
    # 通义千问
    "qwen3": 128_000,
    "qwen2.5": 32_768,
    "qwen-max": 32_000,
    "qwen-plus": 131_072,
    "qwen-turbo": 1_000_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 32_768,
    "gpt-3.5": 16_385,
    "o3": 200_000,
    "o1": 200_000,
    # Anthropic
    "claude-3.7": 200_000,
    "claude-3.5": 200_000,
    "claude-3": 200_000,
    # 月之暗面 / Kimi
    "moonshot": 128_000,
    "kimi": 128_000,
}


def context_length_for(model):
    """按模型名匹配上下文窗口;未命中返回 None(调用方回退默认 32k)。"""
    if not model:
        return None
    m = str(model).strip().lower()
    for key in sorted(MODEL_CONTEXT_LENGTHS, key=len, reverse=True):
        if key in m:
            return MODEL_CONTEXT_LENGTHS[key]
    return None


def budgets_for(model, context_length=None):
    """返回 (soft, hard, context_length, source):
    优先级 = 显式 context_length > 模型映射表 > 默认常量(32k)。
    source: manual(手动设置) / auto(映射表) / default(回退)"""
    if context_length:
        try:
            ctx = int(context_length)
            if ctx > 0:
                return int(ctx * SOFT_RATIO), int(ctx * HARD_RATIO), ctx, "manual"
        except (TypeError, ValueError):
            pass
    ctx = context_length_for(model)
    if ctx:
        return int(ctx * SOFT_RATIO), int(ctx * HARD_RATIO), ctx, "auto"
    return SOFT_BUDGET, HARD_BUDGET, None, "default"


def estimate_tokens(text):
    """混合中英文的 token 估算:中文约 0.6 字/token,英文约 4 字符/token"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return int(cjk / 1.7 + other / 3.8) + 6


def estimate_messages(messages):
    total = 0
    for m in messages:
        total += estimate_tokens(m.get("content") or "")
        total += estimate_tokens(m.get("name") or "")
    return total + 8 * len(messages)


def compress_window(messages, keep_raw=KEEP_RAW, model=None, context_length=None):
    """返回 (summary_text, kept_messages):超出窗口或消息条数过多时把旧轮次抽成摘要"""
    soft, _hard, _ctx, _src = budgets_for(model, context_length)
    total = estimate_messages(messages)
    # 原始消息条数上限:即便未超 token 预算(如 1M 窗口),过长会话也压缩旧轮次,
    # 控制每轮 prefill 耗时,避免对话"越聊越慢"
    MAX_RAW = 48
    if total <= soft and len(messages) <= MAX_RAW:
        return None, messages
    kept = messages[-keep_raw:]
    old = messages[:-keep_raw]
    summary_text = ""
    if old:
        pairs = []
        for m in old:
            role = m["role"]
            content = (m.get("content") or "")[:400]
            if role == "user":
                pairs.append(f"用户: {content}")
            elif role == "assistant":
                pairs.append(f"助手: {content[:200]}")
        joined = "\n".join(pairs)
        summary_text = (
            "[早前对话摘要,已压缩以节省上下文]\n" + joined[:6000]
        )
    return summary_text, kept


def budget_info(messages, model=None, context_length=None):
    total = estimate_messages(messages)
    soft, hard, ctx, source = budgets_for(model, context_length)
    return {
        "estimated_tokens": total,
        "soft_budget": soft,
        "hard_budget": hard,
        "context_length": ctx or hard,  # 生效的模型上下文窗口
        "context_source": source,       # manual / auto / default
        "model": (model or "").strip(),
        "keep_raw": KEEP_RAW,
        "over_soft": total > soft,
        "over_hard": total > hard,
    }
