# -*- coding: utf-8 -*-
"""RapidOCR + PyMuPDF 运行时安装器 - 独立 venv, 与主程序依赖完全隔离

镜像 install_searxng.py 的模式, 规避许可证问题:
- pymupdf (fitz, AGPL-3.0) 与 rapidocr_onnxruntime (Apache-2.0) 只装进
  runtime/ocr/venv 独立虚拟环境, 主程序 requirements 不引入
- OCR/PDF 解析运行在 ocr_worker.py 独立进程, Agent 主进程经 HTTP 调用,
  不 import 这两个库 => 不构成 AGPL 派生产品, 主程序无需开源

用法:
    python install_ocr.py            # 安装(已存在则跳过)
    python install_ocr.py --force    # 删除 venv 重装
    python install_ocr.py --no-mirror
    python install_ocr.py --mirror https://pypi.tuna.tsinghua.edu.cn/simple
"""
import argparse
import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(BASE_DIR, "runtime", "ocr")
VENV_DIR = os.path.join(RUNTIME_DIR, "venv")
if os.name == "nt":
    VENV_PYTHON = os.path.join(VENV_DIR, "Scripts", "python.exe")
    VENV_PIP = os.path.join(VENV_DIR, "Scripts", "pip.exe")
else:
    VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python")
    VENV_PIP = os.path.join(VENV_DIR, "bin", "pip")

PKGS = ["pymupdf", "rapidocr_onnxruntime"]
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"


def _run(args, **kw):
    print(">>", " ".join(args))
    return subprocess.run(args, **kw)


def create_venv(force):
    if os.path.isdir(VENV_DIR):
        if not force:
            print(f"[skip] venv 已存在: {VENV_DIR} (加 --force 重装)")
            return True
        import shutil
        print(f"[del] 删除旧 venv: {VENV_DIR}")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    r = _run([sys.executable, "-m", "venv", VENV_DIR])
    return r.returncode == 0


def pip_install(mirror):
    args = [VENV_PIP, "install", "-U", "--disable-pip-version-check"]
    if mirror:
        args += ["-i", mirror]
    args += PKGS
    r = _run(args)
    if r.returncode != 0:
        print("[warn] 主镜像失败, 回退官方 PyPI 重试...")
        args = [VENV_PIP, "install", "-U", "--disable-pip-version-check"] + PKGS
        r = _run(args)
    return r.returncode == 0


def verify():
    r = subprocess.run(
        [VENV_PYTHON, "-c",
         "import fitz, rapidocr_onnxruntime; print('fitz', fitz.__doc__.splitlines()[0] if fitz.__doc__ else 'ok'); print('rapidocr_onnxruntime ok')"],
        capture_output=True, text=True,
    )
    ok = r.returncode == 0
    if ok:
        print("[ok] worker venv 验证通过:")
        for line in (r.stdout or "").splitlines():
            print("   ", line)
    else:
        print("[fail] worker venv 验证失败:")
        print((r.stderr or "")[-2000:])
    return ok


def main():
    ap = argparse.ArgumentParser(description="安装 OCR/PDF 独立运行时 (runtime/ocr/venv)")
    ap.add_argument("--force", action="store_true", help="删除旧 venv 重装")
    ap.add_argument("--no-mirror", action="store_true", help="不使用镜像源")
    ap.add_argument("--mirror", default=None, help="自定义 pip 镜像 (默认清华源)")
    args = ap.parse_args()
    if args.no_mirror and not args.mirror:
        args.mirror = False
    if args.mirror is None:
        args.mirror = MIRROR
    if not create_venv(args.force):
        sys.exit("创建 venv 失败")
    if not pip_install(args.mirror):
        sys.exit("pip 安装失败")
    if not verify():
        sys.exit("运行时验证失败")
    print("[done] OCR/PDF 独立运行时已就绪, 由 ocr_launcher.py 自动拉起 ocr_worker.py")


if __name__ == "__main__":
    main()
