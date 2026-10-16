# -*- coding: utf-8 -*-
"""统一日志（coding_standards §5 配套）。

`setup_logging()` 幂等初始化：控制台 + 文件（`<log_dir>/ecoagent.log`）。
默认静默 werkzeug 访问日志，与 v1.2 打包（console=False）行为保持一致。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_FORMAT = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
_DATEFMT = '%Y-%m-%d %H:%M:%S'

_configured = False


def setup_logging(log_dir: Path | str | None = None, level: int = logging.INFO) -> None:
    """初始化根 logger（幂等）：控制台必开，文件可选。"""
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(level)
    fmt = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_dir is not None:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(Path(log_dir) / 'ecoagent.log'), encoding='utf-8')
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger（需先调用 setup_logging）。"""
    return logging.getLogger(name)
