# -*- coding: utf-8 -*-
"""生态Agent - Flask 服务与 API 路由（薄入口）

S2-M4 迁移（2026-08-20）：207 个路由与 Flask app 已迁入
`src/gateway/flask_app.py`，本文件仅保留 `create_app` 入口与直接运行支持，
`from app import create_app` 用法不变。
"""
import os

from src.gateway.flask_app import create_app  # noqa: F401
from src.gateway.flask_app import app  # noqa: F401  （兼容直接 import app 的用法）

if __name__ == "__main__":
    create_app()
    port = int(os.environ.get("PORT", "5837"))
    print(f"[生态Agent] http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
