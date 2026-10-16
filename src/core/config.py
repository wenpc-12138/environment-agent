# -*- coding: utf-8 -*-
"""v2.0 统一配置入口（coding_standards §3.5：pydantic-settings）。

- 项目根由本文件位置推导：`src/core/config.py` 上溯 3 层。
- 环境变量大小写不敏感且无前缀，直接兼容 v1.2 既有变量（PORT / ECOAGENT_DB），
  保证双轨运行期（v1.2 Flask 与 src/ 新代码）配置一致。
- 读取顺序：环境变量 > .env 文件 > 默认值。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """全局配置模型（路径字段为相对路径，用 resolve() 转绝对路径）。"""

    model_config = SettingsConfigDict(
        env_file='.env',
        case_sensitive=False,
        extra='ignore',
    )

    # ---- 路径（相对 project_root）----
    data_dir: str = 'data'
    db_path: str = 'data/ecoagent.db'
    log_dir: str = 'data/logs'
    migrations_dir: str = 'db/migrations'
    # v1.2 兼容：环境变量 ECOAGENT_DB 直接指定数据库文件（优先级高于 db_path）
    ecoagent_db: str | None = None

    # ---- 服务 ----
    host: str = '127.0.0.1'
    port: int = 0  # 0 = 自动分配空闲端口（v1.2 run.py 行为）

    # ---- 推理 ----
    llm_provider: str = 'openai'
    llm_model: str = 'deepseek-v4-pro'
    llm_base_url: str = 'https://api.deepseek.com'

    # ---- 业务 ----
    kb_top_k: int = 5
    router_confidence: float = 0.6
    context_soft_budget: int = 120_000
    context_hard_budget: int = 200_000

    def resolve(self, rel: str) -> Path:
        """将相对路径解析为绝对路径（相对 project_root）。"""
        p = Path(rel)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def db_file(self) -> Path:
        """实际数据库文件：ECOAGENT_DB 优先，其次 db_path。"""
        return self.resolve(self.ecoagent_db) if self.ecoagent_db else self.resolve(self.db_path)

    @property
    def data_dir_path(self) -> Path:
        """数据目录绝对路径。"""
        return self.resolve(self.data_dir)

    @property
    def log_dir_path(self) -> Path:
        """日志目录绝对路径。"""
        return self.resolve(self.log_dir)

    @property
    def migrations_dir_path(self) -> Path:
        """迁移脚本目录绝对路径。"""
        return self.resolve(self.migrations_dir)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例配置（lru_cache 保证只解析一次）。"""
    return Settings()
