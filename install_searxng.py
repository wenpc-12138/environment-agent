# -*- coding: utf-8 -*-
"""SearXNG 运行时安装器 - 独立 venv + pip install searxng

用法:
    python install_searxng.py                    # 安装(已安装则跳过)
    python install_searxng.py --force            # 强制重装
    python install_searxng.py --no-mirror        # 不走镜像(官方 PyPI)
    python install_searxng.py --mirror https://pypi.org/simple

说明:
- 独立 venv 隔离, 不污染 Agent 主环境依赖
- 安装完成后由 searxng_launcher.py 自动拉起
"""
import argparse
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(BASE_DIR, "runtime", "searxng", "venv")
# 跨平台 venv 解释器路径: Windows -> venv/Scripts/python.exe; macOS/Linux -> venv/bin/python
VENV_BIN = "Scripts" if os.name == "nt" else "bin"
VENV_PYTHON = os.path.join(VENV_DIR, VENV_BIN, "python.exe" if os.name == "nt" else "python")
DEFAULT_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def _ok():
    # 官方 searxng 包模块名为 searx (webapp 为服务入口); 占位空壳包 import searx 必然失败
    try:
        subprocess.check_call(
            [VENV_PYTHON, "-c", "import searx.webapp; sys.stdout.write('ok')"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description="SearXNG 运行时安装器")
    ap.add_argument("--force", action="store_true", help="强制重装")
    ap.add_argument("--no-mirror", action="store_true", help="使用官方 PyPI")
    ap.add_argument("--mirror", default=None, help="自定义镜像地址")
    args = ap.parse_args()

    if not args.force and os.path.exists(VENV_PYTHON) and _ok():
        print("[OK] SearXNG 已安装于独立 venv, 跳过 (--force 重装)")
        print("     venv:", VENV_DIR)
        return

    print(f"[..] 创建独立 venv: {VENV_DIR}")
    os.makedirs(os.path.dirname(VENV_DIR), exist_ok=True)
    subprocess.check_call([sys.executable, "-m", "venv", VENV_DIR])
    print("[..] 升级 pip ...")
    subprocess.check_call([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"])
    print("[..] 安装 setuptools/wheel (构建依赖) ...")
    subprocess.check_call([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "setuptools", "wheel"])

    cmd = [VENV_PYTHON, "-m", "pip", "install"]
    mirror = args.mirror
    if mirror is None and not args.no_mirror:
        mirror = DEFAULT_MIRROR
    if mirror:
        cmd += ["-i", mirror]

    # 优先本地官方源码安装: PyPI 上 'searxng' 存在 0.0.0.dev0 占位空壳包(无 searx 模块),
    # 从镜像安装可能再次装上空壳导致启动失败
    src_dir = os.path.join(BASE_DIR, "runtime", "searxng", "searxng-master")
    if os.path.exists(os.path.join(src_dir, "setup.py")):
        req = os.path.join(src_dir, "requirements.txt")
        if os.path.exists(req):
            print("[..] 安装 searxng 运行依赖 (来自源码 requirements.txt) ...")
            subprocess.check_call(cmd + ["-r", req])
        print("[..] 从本地源码安装 searxng (依赖较多, 请耐心等待) ...")
        subprocess.check_call(cmd + ["--no-build-isolation", src_dir])
    else:
        print("[..] 未找到本地源码, 从 PyPI 安装 searxng ...")
        subprocess.check_call(cmd + ["searxng"])

    if not _ok():
        print("[X] 安装后校验失败, 请检查上面的报错")
        sys.exit(1)
    print("[OK] SearXNG 运行时安装完成")
    print("     venv:", VENV_DIR)
    print("     之后启动软件将自动拉起 SearXNG (默认端口 8888, 被占自动换端口)")


if __name__ == "__main__":
    main()
