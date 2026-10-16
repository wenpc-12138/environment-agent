# -*- coding: utf-8 -*-
"""OCR/PDF worker 自动拉起守护器 - 镜像 searxng_launcher.py 的 AGPL 隔离模式

职责:
- 首次调用 ensure_running() 时自动拉起 runtime/ocr/venv 下的 ocr_worker.py 独立进程
- 端口占用自动探测: 从 8891 起扫描, 空闲端口自拉起 / 发现已有 OCR worker 则复用
- 崩溃自愈: 进程异常退出后, 下一次 ensure_running() 自动重启
- 仅终止本模块拉起的子进程, 外部实例(复用)一律不接管不关闭
- 许可证隔离: pymupdf(AGPL) 与 rapidocr( Apache-2.0) 只在独立 venv 进程内,
  Agent 主进程经 HTTP 调用, 不 import 这两个库

用法:
    ocr_launcher.ensure_running()   # 幂等: 启动/复用/自愈
    ocr_launcher.status()           # 状态快照
    ocr_launcher.stop()             # 仅清理本模块拉起的进程
"""
import json
import os
import socket
import subprocess
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(BASE_DIR, "runtime", "ocr")
if os.name == "nt":
    VENV_PYTHON = os.path.join(RUNTIME_DIR, "venv", "Scripts", "python.exe")
else:
    VENV_PYTHON = os.path.join(RUNTIME_DIR, "venv", "bin", "python")

DEFAULT_PORT = 8891
PORT_SCAN_MAX = 10          # 从默认端口起最多探测端口数
START_TIMEOUT = 30.0        # 等待 worker 就绪秒数(首次启动加载模型较慢)
_WAIT = 0.5

_lock = threading.Lock()
_state = {
    "proc": None,       # 本模块拉起的子进程 (managed 才有)
    "port": None,
    "url": None,
    "mode": "idle",     # idle/external/managed/not_installed/error
    "ready": False,
    "pid": None,
    "last_err": "",
}


def _port_open(port, timeout=0.5):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _health_ok(url, timeout=3.0):
    try:
        import requests
        r = requests.get(url + "/health?quick=1", timeout=timeout)
        return r.status_code == 200 and (r.json() or {}).get("ok") is True
    except Exception:
        return False


def _pid_on_port(port):
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
    except Exception:
        return None


def _spawn(port):
    """拉起独立 OCR worker 进程, 等待就绪"""
    if not os.path.isfile(VENV_PYTHON):
        _state.update(mode="not_installed", last_err="runtime/ocr/venv 未安装, 运行 install_ocr.py")
        return False
    worker_py = os.path.join(BASE_DIR, "ocr_worker.py")
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(
            [VENV_PYTHON, worker_py, "--port", str(port)],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except Exception as e:  # noqa: BLE001
        _state.update(mode="error", last_err=f"spawn failed: {e}")
        return False
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        if proc.poll() is not None:
            _state.update(mode="error", last_err=f"worker exited rc={proc.returncode}")
            return False
        if _health_ok(url):
            _state.update(proc=proc, port=port, url=url, mode="managed",
                          ready=True, pid=proc.pid, last_err="")
            return True
        time.sleep(_WAIT)
    proc.terminate()
    _state.update(mode="error", last_err="worker start timeout", pid=None)
    return False


def ensure_running():
    """幂等: 已 managed 且健康 -> 复用; 崩溃 -> 重启; 无 -> 探测外部/自拉起"""
    with _lock:
        if _state["proc"] is not None:
            if _state["ready"] and _health_ok(_state["url"]):
                return _state
            if _state["proc"].poll() is not None:
                _state["proc"] = None
                _state.update(mode="idle", ready=False, pid=None)
        for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_SCAN_MAX):
            if not _port_open(port):
                _spawn(port)
                return _state
            url = f"http://127.0.0.1:{port}"
            if _health_ok(url):
                _state.update(proc=None, port=port, url=url, mode="external",
                              ready=True, pid=_pid_on_port(port), last_err="")
                return _state
        _state.update(mode="error", last_err="no free port in scan range")
        return _state


def status():
    # proc 为 Popen 对象不可序列化(jsonify/json.dumps 会失败), 故移除
    st = {k: v for k, v in _state.items() if k != "proc"}
    st["python"] = VENV_PYTHON if os.path.isfile(VENV_PYTHON) else None
    return st


def stop():
    with _lock:
        proc = _state.get("proc")
        _state.update(proc=None, mode="idle", ready=False, pid=None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    return status()


def restart():
    stop()
    return ensure_running()


if __name__ == "__main__":
    snap = ensure_running()
    print(json.dumps(snap, ensure_ascii=False, indent=2))
