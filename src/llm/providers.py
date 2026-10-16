# -*- coding: utf-8 -*-
"""生态Agent - Provider 抽象层(OpenAI 兼容 / 内置演示)

S2-M2 迁移（2026-08-20）：自根目录 `providers.py` 原样迁入；
根文件已转兼容重导出（`from src.llm.providers import *`）。
"""
import json
import time
import requests
from ..core.context import estimate_tokens as _ctx_estimate_tokens


class ProviderError(Exception):
    pass


def parse_usage(usage, model=""):
    """从各家 API 的 usage 中解析 token 与缓存命中(DeepSeek/OpenAI/Qwen 等)"""
    usage = usage or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    details = usage.get("prompt_tokens_details") or {}
    if not hit:
        hit = int(details.get("cached_tokens") or 0)
    miss = max(prompt - hit, 0)
    if hit and not prompt:
        # 某些实现只报 miss,没有总 prompt
        miss = int(usage.get("prompt_cache_miss_tokens") or 0)
        prompt = hit + miss
    creation = int(usage.get("prompt_cache_creation_tokens") or 0)
    if not creation:
        creation = int(details.get("cache_creation_tokens") or 0)
    thinking = int(usage.get("thinking_tokens") or 0)
    if not thinking:
        cd = usage.get("completion_tokens_details") or {}
        thinking = int(cd.get("reasoning_tokens") or 0)
    return {
        "prompt": prompt,
        "completion": completion,
        "hit": hit,
        "miss": miss,
        "cache_creation": creation,
        "thinking": thinking,
    }


class OpenAIProvider:
    """任意 OpenAI 兼容 /chat/completions 端点"""

    def __init__(self, prov):
        self.prov = prov
        self.base = (prov.get("base_url") or "").rstrip("/")
        if not self.base:
            raise ProviderError("未配置 base_url")
        self.model = prov.get("model") or "deepseek-chat"
        self.api_key = prov.get("api_key") or ""
        self.reasoning_effort = (prov.get("reasoning_effort") or "high").strip().lower()

    def _url(self):
        # 兼容 base_url 直接含 /v1 的情况
        if self.base.endswith("/chat/completions"):
            return self.base
        return self.base + "/chat/completions"

    def stream(self, messages, tools=None, temperature=0.4):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        # DeepSeek V4 思考模式:thinking + reasoning_effort(off/low/high/xhigh/max)
        if "deepseek" in (self.base + " " + self.model).lower():
            if self.reasoning_effort and self.reasoning_effort != "off":
                payload["thinking"] = {"type": "enabled"}
                if self.reasoning_effort in ("low", "high", "xhigh", "max"):
                    payload["reasoning_effort"] = self.reasoning_effort
            else:
                payload["thinking"] = {"type": "disabled"}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        try:
            resp = requests.post(
                self._url(), json=payload, headers=headers, stream=True, timeout=(10, 300)
            )
        except requests.exceptions.RequestException as e:
            yield {"error": f"连接失败: {e}"}
            return
        if resp.status_code != 200:
            body = resp.text[:400]
            yield {"error": f"HTTP {resp.status_code}: {body}"}
            return
        usage = None
        tool_acc = {}  # index -> {"id","name","args"}
        content_acc = []
        finish_reason = None
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except Exception:
                continue
            if chunk.get("usage"):
                usage = chunk["usage"]
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            ch = choices[0]
            if ch.get("finish_reason"):
                finish_reason = ch["finish_reason"]
            delta = ch.get("delta") or {}
            if delta.get("content"):
                piece = delta["content"]
                content_acc.append(piece)
                yield {"delta": {"content": piece}}
            reasoning = delta.get("reasoning_content") or delta.get("thinking_content")
            if reasoning:
                yield {"delta": {"reasoning": reasoning}}
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                acc = tool_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
                fn = tc.get("function") or {}
                if tc.get("id"):
                    acc["id"] = tc["id"]
                if fn.get("name"):
                    acc["name"] += fn["name"]
                if fn.get("arguments"):
                    acc["args"] += fn["arguments"]
                yield {"delta": {"tool_piece": {"index": idx}}}
        # 组装 tool_calls
        calls = []
        for idx in sorted(tool_acc):
            a = tool_acc[idx]
            try:
                args = json.loads(a["args"]) if a["args"].strip() else {}
            except Exception:
                args = {"_raw": a["args"]}
            calls.append({"id": a["id"] or f"call_{idx}", "name": a["name"], "arguments": args})
        yield {"tool_calls": calls, "finish_reason": finish_reason,
               "content": "".join(content_acc), "usage": parse_usage(usage, self.model)}


class DeepSeekResponsesProvider:
    """DeepSeek Responses API 通道(https://api.deepseek.com/responses)。
    - 声明内置 web_search 工具(服务端执行): 模型自动联网搜索,
      streaming 事件序列中包含 response.web_search_call.in_progress /
      searching / completed 三个状态事件(前端可展示"正在联网搜索")。
    - 同时保留自定义 function 工具(kb_lookup 等), 兼容 agent_core 的
      tool_calls 循环: function_call 事件按 OpenAI 兼容格式回传。
    - 输出格式与 OpenAIProvider.stream 完全一致(delta.content / delta.reasoning /
      tool_calls / usage), agent_core 无需改动。"""

    def __init__(self, prov):
        self.prov = prov
        self.base = (prov.get("base_url") or "https://api.deepseek.com").rstrip("/")
        self.model = prov.get("model") or "deepseek-chat"
        self.api_key = prov.get("api_key") or ""
        self.reasoning_effort = (prov.get("reasoning_effort") or "high").strip().lower()
        self.use_server_search = bool(prov.get("use_server_search"))
        # Responses API 思考模式要求下一轮回传 reasoning 明文, 这里跨轮保存
        self._last_reasoning = ""

    def _url(self):
        if self.base.endswith("/responses"):
            return self.base
        return self.base + "/responses"

    def _build_tools(self, tools):
        """内置 web_search + 自定义 function 工具混合声明。
        - 内置 web_search 工具声明为首个, 替代本地 web_search function
          (模型要联网时只能选服务端内置搜索, 满足"直接调用内置 web_search")
        - 其余本地 function 工具(kb_lookup/std_import 等)原样保留
        - Responses API 的 function 工具为顶层 name/description/parameters"""
        out = [{"type": "web_search"}]
        for t in tools or []:
            fn = (t or {}).get("function") or {}
            fname = fn.get("name") or (t.get("name") if "name" in t else "")
            if not fname:
                continue
            if fname == "web_search":
                # 联网搜索统一由内置 web_search 提供, 跳过本地 SearXNG 版本
                continue
            if "name" in t:
                out.append(t)  # 已是 Responses API 格式
                continue
            out.append({
                "type": "function",
                "name": fname,
                "description": fn.get("description") or "",
                "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                "strict": False,
            })
        return out

    def _messages_to_input(self, messages):
        """OpenAI 消息格式 → Responses API input items:
        - user/system/assistant 普通消息 → message item
        - assistant 带 tool_calls → reasoning item(思考明文, 如有) + function_call item
        - role=tool → function_call_output item
        """
        items = []
        for m in messages or []:
            role = m.get("role") or ""
            content = m.get("content") or ""
            if role == "tool":
                items.append({
                    "type": "function_call_output",
                    "call_id": m.get("tool_call_id") or "call_0",
                    "output": content if isinstance(content, str) else json.dumps(content, ensure_ascii=False),
                })
                continue
            if role == "assistant" and m.get("tool_calls"):
                # 思考模式要求回传上一轮 reasoning 明文
                if self._last_reasoning:
                    items.append({
                        "type": "reasoning",
                        "content": [{"type": "reasoning_text", "text": self._last_reasoning}],
                    })
                    self._last_reasoning = ""
                # 先放 assistant 消息文本(如有), 再放 function_call
                if content:
                    items.append({"type": "message", "role": "assistant",
                                  "content": [{"type": "output_text", "text": content}]})
                for tc in m["tool_calls"]:
                    fn = tc.get("function") or {}
                    items.append({
                        "type": "function_call",
                        "call_id": tc.get("id") or f"call_{len(items)}",
                        "name": fn.get("name") or "",
                        "arguments": fn.get("arguments") or "{}",
                    })
                continue
            # user / system / assistant 普通消息
            if role not in ("user", "system", "assistant", "developer"):
                continue
            r = "assistant" if role in ("assistant",) else role
            items.append({"type": "message", "role": r,
                          "content": [{"type": "input_text", "text": content}]})
        return items

    def stream(self, messages, tools=None, temperature=0.4):
        payload = {
            "model": self.model,
            "input": self._messages_to_input(messages),
            "stream": True,
            "temperature": temperature,
            "tools": self._build_tools(tools),
            "tool_choice": "auto",
        }
        # 思考模式: reasoning.effort
        if self.reasoning_effort and self.reasoning_effort != "off":
            payload["reasoning"] = {"effort": self.reasoning_effort}
        else:
            payload["reasoning"] = {"effort": "low"}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        try:
            resp = requests.post(
                self._url(), json=payload, headers=headers, stream=True, timeout=(10, 300)
            )
        except requests.exceptions.RequestException as e:
            yield {"error": f"连接失败: {e}"}
            return
        if resp.status_code != 200:
            body = resp.text[:400]
            yield {"error": f"HTTP {resp.status_code}: {body}"}
            return
        # 事件解析
        content_acc = []
        reasoning_acc = []
        usage = None
        finish_reason = None
        fn_acc = {}  # call_id -> {"name", "args", "id"}
        fn_order = []
        seen_web = set()
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                ev = json.loads(data)
            except Exception:
                continue
            etype = ev.get("type") or ""
            if etype == "response.web_search_call.in_progress":
                seen_web.add("in_progress")
                yield {"delta": {"web_search_status": "in_progress"}}
            elif etype == "response.web_search_call.searching":
                seen_web.add("searching")
                yield {"delta": {"web_search_status": "searching"}}
            elif etype == "response.web_search_call.completed":
                seen_web.add("completed")
                yield {"delta": {"web_search_status": "completed"}}
            elif etype == "response.reasoning_text.delta":
                piece = ev.get("delta") or ""
                if piece:
                    reasoning_acc.append(piece)
                    yield {"delta": {"reasoning": piece}}
            elif etype == "response.reasoning_text.done":
                # 思考模式: 保存完整 reasoning 供下一轮回传
                full = ev.get("text") or ev.get("content") or ""
                if full:
                    reasoning_acc.append(full if isinstance(full, str) else json.dumps(full, ensure_ascii=False))
            elif etype == "response.output_text.delta":
                piece = ev.get("delta") or ""
                if piece:
                    content_acc.append(piece)
                    yield {"delta": {"content": piece}}
            elif etype in ("response.output_item.added", "response.output_item.done"):
                item = ev.get("item") or {}
                if item.get("type") == "function_call":
                    cid = item.get("id") or item.get("call_id") or f"call_{len(fn_acc)}"
                    if cid not in fn_acc:
                        fn_acc[cid] = {"id": cid, "name": item.get("name") or "", "args": ""}
                        fn_order.append(cid)
                    else:
                        fn_acc[cid]["name"] = item.get("name") or fn_acc[cid]["name"]
                    yield {"delta": {"tool_piece": {"index": len(fn_order) - 1}}}
            elif etype == "response.function_call_arguments.delta":
                cid = ev.get("item_id") or ev.get("call_id") or ""
                delta = ev.get("delta") or ""
                for k, acc in fn_acc.items():
                    if cid in k or k in cid or cid == "":
                        acc["args"] += delta
                        break
            elif etype in ("response.completed", "response.incomplete", "response.failed"):
                obj = ev.get("response") or ev.get("output") or {}
                usage = ev.get("usage") or (obj.get("usage") if isinstance(obj, dict) else None)
                if etype == "response.completed":
                    finish_reason = "stop"
                elif etype == "response.incomplete":
                    finish_reason = "length"
                else:
                    finish_reason = "error"
                # 失败时输出 error 信息
                if etype == "response.failed":
                    err = ((obj.get("error") if isinstance(obj, dict) else None) or ev.get("error") or "")
                    if err:
                        yield {"error": str(err)[:300]}
                break
        # 保存思考明文(下轮回传给 Responses API)
        if reasoning_acc:
            self._last_reasoning = "".join(reasoning_acc)
        # 组装 tool_calls(OpenAI 兼容格式)
        calls = []
        for cid in fn_order:
            a = fn_acc[cid]
            try:
                args = json.loads(a["args"]) if a["args"].strip() else {}
            except Exception:
                args = {"_raw": a["args"]}
            calls.append({"id": a["id"] or cid, "name": a["name"], "arguments": args})
        yield {
            "tool_calls": calls,
            "finish_reason": finish_reason or "stop",
            "content": "".join(content_acc),
            "usage": parse_usage(usage, self.model),
            "server_search": sorted(seen_web) if seen_web else [],
        }


class MockProvider:
    """演示模式:无需密钥,复现完整 Agent 闭环(检索->思考->回答)"""

    def __init__(self, prov):
        self.prov = prov

    def _tool_lookup(self, query):
        import tools
        return tools.execute_tool("kb_lookup", {"query": query, "top_n": 3}, None)

    def stream(self, messages, tools=None, temperature=0.4):
        # 找出最后一条用户消息
        user_msgs = [m for m in messages if m["role"] == "user"]
        last_user = user_msgs[-1]["content"] if user_msgs else "环境监测"
        asked = [m for m in messages if m.get("role") == "assistant" and not m.get("tool_blocks")]
        first_round = len(asked) == 0
        usage = {"prompt": 0, "completion": 0, "hit": 0, "miss": 0}
        finish_reason = "stop"

        def emit_text(parts, delay=0.012):
            for p in parts:
                time.sleep(delay)
                yield {"delta": {"content": p}}
                usage["prompt"] += 8
                usage["completion"] += len(p)

        # 演示:第一轮只触发知识库检索工具,工具结果注入后由第二轮给出最终回答
        if first_round and tools:
            g = emit_text(["让我先检索本地知识库,确认相关信息。\n\n"], delay=0.006)
            for e in g:
                yield e
            yield {"tool_calls": [{"id": "mock_call_1", "name": "kb_lookup", "arguments": {"query": last_user, "top_n": 3}}],
                   "finish_reason": "tool_calls", "content": "让我先检索本地知识库,确认相关信息。",
                   "usage": parse_usage(usage)}
            return

        # 普通回答:基于上一轮工具结果作答(演示模式)
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        tool_out = tool_msgs[-1]["content"] if tool_msgs else ""
        lines = tool_out.splitlines()
        entries = []
        for ln in lines:
            if ln[:2].rstrip(".").isdigit() or (ln and ln[0].isdigit() and ". " in ln[:5]):
                entries.append(ln)
            elif ln.startswith("[") and "]" in ln:
                entries.append(ln)
        body = [f"根据本地知识库检索结果,针对「{last_user}」回答如下:", ""]
        if entries:
            body.append("知识库命中条目(相关度排序):")
            for e in entries[:4]:
                body.append("  " + e)
            body.append("")
            body.append("说明:以上内容来自本地知识库,标准编号与限值请以原文及现行有效版本为准。")
        else:
            body.append("知识库未命中直接相关条目。建议: 1) 改用 ask 模式说明你的知识背景; 2) 联网检索补充(web_search); 3) 提供标准原文由我落库。")
        body.append("")
        body.append("[提示] 当前为演示模式(mock),未消耗真实 API 额度。在左侧配置真实 Provider 后可获得完整推理能力。")
        g = emit_text([b + "\n" for b in body], delay=0.015)
        for e in g:
            yield e
        yield {"tool_calls": [], "finish_reason": finish_reason, "content": "\n".join(body), "usage": parse_usage(usage)}


def build_provider(prov):
    if not prov:
        raise ProviderError("未选择 Provider")
    if prov.get("kind") == "mock":
        return MockProvider(prov)
    # DeepSeek 内置 web_search: 选用 DeepSeek 模型且开启 use_server_search 开关时,
    # 走 Responses API 通道(服务端联网搜索 + 保留本地 function 工具)
    if prov.get("use_server_search"):
        blob = ("%s %s" % (prov.get("base_url") or "", prov.get("model") or "")).lower()
        if "deepseek" in blob:
            return DeepSeekResponsesProvider(prov)
    return OpenAIProvider(prov)


# 多模态(视觉)模型识别模式: 命中即视为支持 image_url 输入(VLM)
_VISION_MODEL_PATTERNS = (
    "gpt-4o", "gpt-4.1", "o3", "o4", "o4-mini", "gemini",
    "claude-3", "glm-4v", "glm-4.5v", "glm-4.6v",
    "qwen-vl", "qwen2-vl", "qwen2.5-vl", "qwen3-vl", "qwen3-ocr",
    "moonshot-v1-8k-vision", "step-1v", "step-2v", "minimax-vl", "hunyuan-vl", "hunyuan-vision",
)


def supports_vision(prov):
    """判定 Provider 是否支持多模态视觉输入(VLM 读图)。
    演示 mock 与纯文本模型(deepseek 等)返回 False -> 扫描件回退 RapidOCR 路线。"""
    if not prov:
        return False
    if prov.get("kind") == "mock":
        return False
    model = (prov.get("model") or "").lower()
    return any(p in model for p in _VISION_MODEL_PATTERNS)


def chat_text(prov, messages, temperature=0.1, timeout=180):
    """非流式文本补全(OpenAI 兼容): 用于 VLM 逐页转录/回校等结构化子任务。
    支持 messages 中 content 为数组(含 image_url)的多模态请求。
    返回 (文本, usage), 失败抛 ProviderError。"""
    p = build_provider(prov)
    if isinstance(p, MockProvider):
        raise ProviderError("演示模式不支持结构化子任务, 请配置真实 Provider")
    try:
        r = requests.post(
            p._url(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer %s" % p.api_key,
            },
            json={
                "model": p.model,
                "messages": messages,
                "temperature": temperature,
                "stream": False,
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            raise ProviderError("HTTP %s: %s" % (r.status_code, (r.text or "")[:300]))
        data = r.json()
        if data.get("error"):
            raise ProviderError(str(data["error"]))
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return content, parse_usage(data.get("usage") or {}, p.model)
    except requests.RequestException as e:
        raise ProviderError("请求失败: %s" % e)


def estimate_messages_tokens(messages):
    return sum(_ctx_estimate_tokens(m.get("content") or "") for m in messages)
