"""Application configuration.

All settings come from environment variables with the ``AGENT_CORE_`` prefix
(or a local ``.env`` file). API keys for model providers are read directly by
the provider SDKs (``OPENAI_API_KEY`` etc.) and are deliberately not part of
this model.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_CORE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    model: str = "openai:gpt-4o-mini"
    model_provider: str = "openai"

    # Optional persistence (Phase 16): set to "sqlite:///./agent_core.db" to
    # mirror registries/runs/approvals/events into SQLite and restore on boot.
    database_url: str | None = None

    mcp_endpoint: str | None = None

    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"

    # Outbound HTTP proxy for model providers / MCP (e.g. http://127.0.0.1:7890).
    # Applied to the standard HTTP_PROXY / HTTPS_PROXY env vars so every HTTP
    # client in the process (OpenAI SDK, langchain, MCP) picks it up.
    proxy_url: str | None = None


def apply_proxy(settings: Settings) -> None:
    """Export ``settings.proxy_url`` as standard proxy env vars (no override)."""
    if not settings.proxy_url:
        return
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.setdefault(var, settings.proxy_url)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached)."""
    settings = Settings()
    apply_proxy(settings)
    return settings
