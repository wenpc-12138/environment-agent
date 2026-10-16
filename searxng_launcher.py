# -*- coding: utf-8 -*-
"""SearXNG 自动拉起守护器 - 随软件启动自动带起 SearXNG 本体, 退出自动清理

职责:
- 软件启动时自动拉起 SearXNG (独立 venv, 不依赖 Docker), Agent 直接调用
- 端口占用自动探测: 从 8888 起扫描, 找到空闲端口自拉起 / 发现已有 SearXNG 则复用
- 软件关闭自动关闭: 仅终止本模块拉起的子进程, 外部实例(复用)一律不接管不关闭
- 崩溃自愈: 进程异常退出后, 下一次 ensure_running() 自动重启
- 尊重远程配置: 用户显式配置远程 base_url 时, 不覆盖不拉起
- AGPL 隔离: SearXNG 本体保持独立进程, Agent 主进程仍经 MCP Server 调用

用法:
    searxng_launcher.ensure_running()   # 幂等: 启动/复用/自愈
    searxng_launcher.status()           # 状态快照
    searxng_launcher.stop()             # 仅清理本模块拉起的进程
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(BASE_DIR, "runtime", "searxng")
# 跨平台 venv 解释器路径: Windows -> venv/Scripts/python.exe; macOS/Linux -> venv/bin/python
_VENV_BIN = "Scripts" if os.name == "nt" else "bin"
VENV_PYTHON = os.path.join(RUNTIME_DIR, "venv", _VENV_BIN, "python.exe" if os.name == "nt" else "python")
SETTINGS_PATH = os.path.join(RUNTIME_DIR, "settings.yml")
CONFIG_PATH = os.path.join(BASE_DIR, "data", "searxng.json")

DEFAULT_PORT = 8888
PORT_SCAN_MAX = 20           # 从默认端口起最多探测端口数
START_TIMEOUT = 60.0         # 等待 SearXNG 就绪秒数(首次安装启动较慢)
_WAIT = 0.5

_lock = threading.Lock()
_state = {
    "proc": None,      # 本模块拉起的子进程 (managed 才有)
    "port": None,      # 实际使用的端口
    "url": None,       # 实际生效的 base_url
    "mode": "idle",    # idle/disabled/remote/external/managed/not_installed/error
    "ready": False,
    "pid": None,
    "last_err": "",
}

SETTINGS_TEMPLATE = """\
# 生态Agent 自动生成 - SearXNG 配置 (searxng_launcher.py 管理, 请勿手改)
use_default_settings: true

server:
  port: {port}
  bind_address: "127.0.0.1"
  secret_key: "{secret_key}"
  limiter: false
  image_proxy: false

search:
  safe_search: 0
  autocomplete: ""
  default_lang: "zh-CN"
  languages: ["zh-CN", "zh-HK", "zh-TW", "en"]
  formats:
    - html
    - json

ui:
  default_locale: "zh-Hans-CN"  # Babel3 格式(带 script); search.languages 用 zh-CN 旧格式
  results_on_new_tab: true

outgoing:
  request_timeout: 15

engines:
  # 用 inactive(而非 disabled): disabled 引擎仍会执行 init 阻塞启动(wikidata SPARQL 国内超时)
  - name: wikidata
    inactive: true
  - name: torch
    inactive: true
  - name: ahmia
    inactive: true
  # 国内网络被墙/无法连通: 彻底禁用, 避免聚合搜索等待 15s 超时
  - name: google
    inactive: true
  - name: google cse
    inactive: true
  - name: duckduckgo
    inactive: true
  - name: brave
    inactive: true
  # brave 关联引擎引用 network 'brave', 必须一并禁用, 否则启动 KeyError
  - name: brave.images
    inactive: true
  - name: brave.videos
    inactive: true
  - name: brave.news
    inactive: true
  - name: startpage
    inactive: true
  - name: wikipedia
    inactive: true
  # 非网页搜索的特殊引擎(翻译/词典/汇率): 不参与联网搜索
  - name: currency
    inactive: true
  - name: lingva
    inactive: true
  - name: dictzone
    inactive: true
  - name: mymemory translated
    inactive: true
  # 主力引擎: 必应(用 cn 域名直连, 规避 www.bing.com 302 重定向导致解析 0 结果)
  # 注意: SearXNG 配置键是 disabled(不是 enabled), disabled: false 才真正启用
  - name: bing
    disabled: false
    base_url: "https://cn.bing.com"
  # 国内引擎(验证码封禁会周期恢复)
  - name: baidu
    disabled: false
  - name: sogou
    disabled: false
"""


def _port_open(port, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _health_ok(url, timeout=3.0):
    try:
        import requests
        r = requests.get(url + "/healthz", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def _is_local(url):
    u = (url or "").lower().strip().rstrip("/")
    return u.startswith("http://localhost") or u.startswith("http://127.0.0.1")


def _pid_on_port(port):
    """通过端口反查监听进程 PID (external/remote 模式用于展示, 失败返回 None)"""
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING":
                    local = parts[1].rsplit(":", 1)
                    if len(local) == 2 and local[1] == str(port):
                        try:
                            return int(parts[4])
                        except ValueError:
                            pass
            return None
        try:
            import psutil  # noqa: PLC0415
            for conn in psutil.net_connections("tcp"):
                if conn.status == "LISTEN" and conn.laddr and conn.laddr.port == port:
                    return conn.pid
        except Exception:  # noqa: BLE001
            pass
        return None
    except Exception:  # noqa: BLE001
        return None


def _read_config():
    cfg = {"enabled": True, "base_url": "http://localhost:8888"}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    if os.environ.get("SEARXNG_URL"):
        cfg["base_url"] = os.environ["SEARXNG_URL"].strip()
    if os.environ.get("SEARXNG_ENABLED") is not None:
        cfg["enabled"] = os.environ["SEARXNG_ENABLED"].lower() in ("1", "true", "yes", "on")
    return cfg


def probe_port(port):
    """端口三态探测: free=空闲 / searxng=已有SearXNG / other=被其他程序占用"""
    if not _port_open(port):
        return "free"
    if _health_ok(f"http://127.0.0.1:{port}", 2.0):
        return "searxng"
    return "other"


def find_port(start=DEFAULT_PORT, max_tries=PORT_SCAN_MAX):
    """从 start 起扫描: 遇到已有 SearXNG 直接返回(复用), 遇到空闲端口返回(自拉起)"""
    for p in range(start, start + max_tries):
        kind = probe_port(p)
        if kind in ("searxng", "free"):
            return p, kind
    raise RuntimeError(f"端口 {start}-{start + max_tries - 1} 均被其他程序占用")


def _write_settings(port):
    secret = os.urandom(32).hex()
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        f.write(SETTINGS_TEMPLATE.format(port=port, secret_key=secret))


def _apply_url(url):
    """使 Agent 侧实际指向生效端口: 环境变量 + data/searxng.json"""
    os.environ["SEARXNG_MCP_BASE_URL"] = url
    try:
        cfg = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        if (cfg.get("base_url") or "").strip().rstrip("/") != url:
            cfg["base_url"] = url
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:  # 配置更新失败不致命
        _state["last_err"] = f"更新配置失败: {e}"


def _start_managed(port):
    if not os.path.exists(VENV_PYTHON):
        _state.update(mode="not_installed", ready=False, last_err="SearXNG 运行时未安装, 请先运行 install_searxng.py")
        return snapshot()
    try:
        _write_settings(port)
    except Exception as e:
        _state.update(mode="error", ready=False, last_err=f"settings.yml 写入失败: {e}")
        return snapshot()

    env = os.environ.copy()
    env["SEARXNG_SETTINGS_PATH"] = SETTINGS_PATH
    env["SEARXNG_MCP_BASE_URL"] = f"http://127.0.0.1:{port}"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    log_path = os.path.join(RUNTIME_DIR, "searxng.log")
    err_f = open(log_path, "a", encoding="utf-8", buffering=1)
    try:
        proc = subprocess.Popen(
            [VENV_PYTHON, "-m", "searx.webapp"],
            cwd=RUNTIME_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=err_f,
            creationflags=flags,
        )
    except Exception as e:
        err_f.close()
        _state.update(mode="error", ready=False, last_err=f"SearXNG 启动失败: {e}")
        return snapshot()
    err_f.close()  # 句柄已由子进程继承, 父进程安全释放

    url = f"http://127.0.0.1:{port}"
    _state.update(proc=proc, port=port, url=url, mode="managed", ready=False, pid=proc.pid, last_err="")
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        if _health_ok(url):
            _state["ready"] = True
            _apply_url(url)
            return snapshot()
        if proc.poll() is not None:
            _state["last_err"] = f"SearXNG 进程退出 code={proc.returncode}"
            break
        time.sleep(_WAIT)
    # 启动超时: 清理自己拉起的进程, 交由上层降级
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    _state["ready"] = False
    if not _state["last_err"]:
        _state["last_err"] = f"SearXNG 启动超时 ({int(START_TIMEOUT)}s)"
    return snapshot()


def ensure_running():
    """幂等: 启动/复用/自愈 SearXNG。线程安全。"""
    with _lock:
        cfg = _read_config()
        if not cfg.get("enabled", True):
            _state.update(mode="disabled", ready=False, proc=None, last_err="")
            return snapshot()

        # 本模块拉起的进程仍存活 -> 直接复用(ready 随健康检测)
        proc = _state["proc"]
        if proc is not None and proc.poll() is None:
            return snapshot()
        # 曾拉起的进程已退出(崩溃) -> 清空状态, 允许自愈重启
        if proc is not None:
            _state["proc"] = None
            _state["ready"] = False
            _state["pid"] = None

        base = (cfg.get("base_url") or "http://localhost:8888").strip().rstrip("/")
        if base and not _is_local(base):
            # 用户显式配置远程实例: 不接管不拉起, 仅透传可用性
            if _health_ok(base):
                _state.update(mode="remote", url=base, port=None, ready=True, pid=None, last_err="")
            else:
                _state.update(mode="remote", url=base, port=None, ready=False,
                              last_err=f"远程 SearXNG 不可达: {base}")
            return snapshot()

        try:
            port, kind = find_port()
        except RuntimeError as e:
            _state.update(mode="error", ready=False, port=None, last_err=str(e))
            return snapshot()

        if kind == "searxng":
            # 端口上已有外部 SearXNG 实例 -> 直接复用, 不接管不关闭
            # 反查端口 PID 供状态面板展示(仅展示, 不接管不关闭)
            url = f"http://127.0.0.1:{port}"
            pid = _pid_on_port(port)
            _state.update(proc=None, port=port, url=url, mode="external", ready=True, pid=pid, last_err="")
            return snapshot()
        return _start_managed(port)


def restart():
    """控制: 强制重启本模块管理的 SearXNG(先停后起)。
    外部(external)/远程(remote)实例不接管不重启, 仅刷新状态。"""
    with _lock:
        was_managed = _state["mode"] == "managed"
    if was_managed:
        stop()
    return ensure_running()


def stop():
    """软件退出清理: 仅终止本模块拉起的子进程 (managed), 外部/远程实例不受影响"""
    with _lock:
        proc = _state["proc"]
        _state["proc"] = None
        _state["ready"] = False
        _state["pid"] = None
        if _state["mode"] == "managed":
            _state["mode"] = "idle"
            _state["port"] = None
            _state["url"] = None
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def snapshot():
    return {
        "auto_start": True,
        "mode": _state["mode"],
        "port": _state["port"],
        "url": _state["url"],
        "pid": _state["pid"],
        "ready": _state["ready"],
        "last_err": _state["last_err"],
        "installed": os.path.exists(VENV_PYTHON),
        "venv_python": VENV_PYTHON,
    }


def status():
    with _lock:
        return snapshot()


if __name__ == "__main__":
    # 手动调试: python searxng_launcher.py [start|stop|status]
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "start":
        s = ensure_running()
        print(json.dumps(s, ensure_ascii=False, indent=2))
        print("[i] 进程保持运行中, Ctrl+C 或 stop 清理")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            stop()
    elif cmd == "stop":
        stop()
        print("[OK] 已清理本模块拉起的 SearXNG 进程")
    else:
        print(json.dumps(status(), ensure_ascii=False, indent=2))
