"""Configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import __version__

DEFAULT_BASE_URL = "https://api.bgm.tv"
DEFAULT_USER_AGENT = (
    f"whycantiusemyname/bangumi-mcp/{__version__} "
    "(https://github.com/whycantiusemyname/bangumi-mcp)"
)


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class BangumiConfig:
    """Runtime settings for BangumiClient and services."""

    base_url: str = DEFAULT_BASE_URL
    access_token: str | None = None
    user_agent: str = DEFAULT_USER_AGENT
    default_username: str | None = None
    timeout: float = 20.0
    max_retries: int = 4
    retry_base_delay: float = 0.6
    page_delay: float = 0.2
    cache_ttl: float = 300.0

    @classmethod
    def from_env(cls) -> BangumiConfig:
        base_url = (os.getenv("BANGUMI_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
        token = (os.getenv("BANGUMI_ACCESS_TOKEN") or "").strip() or None
        user_agent = (os.getenv("BANGUMI_USER_AGENT") or DEFAULT_USER_AGENT).strip()
        default_username = (os.getenv("BANGUMI_DEFAULT_USERNAME") or "").strip() or None
        return cls(
            base_url=base_url,
            access_token=token,
            user_agent=user_agent,
            default_username=default_username,
            timeout=_float_env("BANGUMI_TIMEOUT", 20.0),
            max_retries=max(0, _int_env("BANGUMI_MAX_RETRIES", 4)),
            retry_base_delay=max(0.0, _float_env("BANGUMI_RETRY_BASE_DELAY", 0.6)),
            page_delay=max(0.0, _float_env("BANGUMI_PAGE_DELAY", 0.2)),
            cache_ttl=max(0.0, _float_env("BANGUMI_CACHE_TTL", 300.0)),
        )
