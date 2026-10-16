# -*- coding: utf-8 -*-
"""M02 网关 CLI（Typer，contracts.md §3.M17）。

子命令：
- `serve`：启动 FastAPI 网关（uvicorn）
- `route`：意图路由（IntentRouter.analyze）调试
- `complete`：LLM 结构化补全调试
- `tools`：列出工具注册表（M04）

typer 未安装时本模块 import 失败（契约测试自动 skip），属预期降级。
"""
from __future__ import annotations

from ...llm import IntentRouter, LLMRouter
from ...models.core import RouteResult
from ...tools import ToolRegistry


def _serve(host: str, port: int, reload: bool) -> None:
    import uvicorn

    from ..api import app

    uvicorn.run(app, host=host, port=port, reload=reload)


def _route(text: str, mode_hint: str) -> None:
    router = IntentRouter()
    ctx = {'mode_hint': mode_hint} if mode_hint else None
    r: RouteResult = router.analyze(text, ctx)
    print(f'mode={r.mode} confidence={r.confidence} domain={r.domain} skills={r.skill_ids}')


def _complete(model: str, prompt: str, schema_cls: str | None) -> None:
    llm = LLMRouter()
    messages = [{'role': 'user', 'content': prompt}]
    print(llm.complete(model, messages, schema=None))


def _tools(capability: str | None) -> None:
    reg = ToolRegistry()
    for spec in reg.list(capability):
        print(f'{spec.id:24s} {spec.capability:8s} {spec.description[:40]}')


def main() -> None:
    import typer

    cli = typer.Typer(add_completion=False)

    @cli.command()
    def serve(host: str = '127.0.0.1', port: int = 8000, reload: bool = False) -> None:
        """启动 FastAPI 网关。"""
        _serve(host, port, reload)

    @cli.command()
    def route(text: str, mode_hint: str = '') -> None:
        """意图路由调试。"""
        _route(text, mode_hint)

    @cli.command()
    def complete(model: str, prompt: str) -> None:
        """LLM 补全调试。"""
        _complete(model, prompt, None)

    @cli.command()
    def tools(capability: str = '') -> None:
        """列出工具注册表。"""
        _tools(capability or None)

    cli()


if __name__ == '__main__':
    main()
