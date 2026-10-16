# -*- coding: utf-8 -*-
"""生态Agent 启动入口
用法:
  python run.py          # 桌面窗口(pywebview,优先)
  python run.py --browser # 浏览器模式
  python run.py --port 5837
"""
import atexit
import os
import socket
import sys
import threading
import webbrowser

from app import create_app
import searxng_launcher

PORT = int(os.environ.get("PORT", "0"))


def pick_free_port():
    """获取一个随机空闲端口,避免端口被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_flask():
    app = create_app()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)


def _searxng_guard():
    """后台守护: 自动拉起 SearXNG (幂等), 崩溃后 30s 内自愈, 不阻塞主流程"""
    import time as _t
    while True:
        try:
            searxng_launcher.ensure_running()
        except Exception:
            pass
        _t.sleep(30)


def main():
    global PORT
    # 本机服务（SearXNG / OCR / 就绪探针）一律直连，避免被系统代理转发导致超时
    try:
        from src.core.net import ensure_local_no_proxy

        ensure_local_no_proxy()
    except Exception:
        pass
    args = sys.argv[1:]
    use_browser = "--browser" in args
    for i, a in enumerate(args):
        if a == "--port" and i + 1 < len(args):
            PORT = int(args[i + 1])
    if PORT <= 0:
        PORT = pick_free_port()
    print(f"[生态Agent] 使用端口: {PORT}")

    # 随软件自动拉起 SearXNG, 退出自动清理 (仅清理本模块拉起的进程)
    threading.Thread(target=_searxng_guard, daemon=True, name="searxng-guard").start()
    atexit.register(searxng_launcher.stop)
    try:
        import searxng_mcp
        atexit.register(searxng_mcp.stop)  # MCP 隔离子进程同样随软件退出清理
    except Exception:
        pass

    t = threading.Thread(target=start_flask, daemon=True)
    t.start()

    url = f"http://127.0.0.1:{PORT}"
    print(f"[生态Agent] 服务已启动: {url}")
    print("[生态Agent] 首次启动将初始化数据库与演示知识库,请稍候...")

    # 等待服务就绪
    import time
    import requests
    for _ in range(30):
        try:
            requests.get(url + "/api/meta", timeout=1)
            break
        except Exception:
            time.sleep(0.3)

    if use_browser:
        webbrowser.open(url)
        print("[生态Agent] 浏览器模式,关闭窗口即退出。按 Ctrl+C 停止服务。")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
        return

    try:
        import webview
        win_kwargs = dict(
            width=1500, height=920,
            min_size=(1100, 720),
            background_color="#0A0A0F",
        )
        # icon 参数依赖 pywebview 版本, 部分版本不支持, 失败时自动降级不传
        try:
            import inspect
            sig = inspect.signature(webview.create_window)
            if "icon" in sig.parameters:
                icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "favicon.ico")
                if os.path.exists(icon_path):
                    win_kwargs["icon"] = icon_path
        except Exception:  # noqa: BLE001
            pass
        webview.create_window(
            "生态Agent - 生态环境特化智能体工作台",
            url,
            **win_kwargs,
        )
        webview.start()
    except ImportError:
        print("[生态Agent] 未安装 pywebview,改用浏览器打开。")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
