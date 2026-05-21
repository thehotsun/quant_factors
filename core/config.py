"""Application configuration helpers.

Keep secrets out of source code. Values are loaded from environment variables
so the same code can run in local, systemd, and CI environments.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional


class MissingConfigError(RuntimeError):
    """Raised when a required runtime configuration value is missing."""


def get_env(name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    value = os.getenv(name, default)
    if required and not value:
        raise MissingConfigError(f"缺少必要环境变量: {name}")
    return value


@lru_cache(maxsize=1)
def get_tushare_token() -> Optional[str]:
    """Return the Tushare token from the environment, if configured."""
    return get_env("TUSHARE_TOKEN")


@lru_cache(maxsize=1)
def get_tushare_pro():
    """Create a Tushare pro client lazily.

    Importing modules should not fail just because the token is absent. Data
    refresh tasks that actually need Tushare will fail with a clear message.
    """
    token = get_tushare_token()
    if not token:
        raise MissingConfigError("TUSHARE_TOKEN 未设置，无法从 Tushare 拉取期货数据")

    import tushare as ts

    ts.set_token(token)
    return ts.pro_api()
