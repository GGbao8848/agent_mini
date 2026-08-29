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
from typing import Literal

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

    # Built-in multimodal tools (Phase 18). ``image_api_base_url`` points at an
    # A1111/Forge-compatible txt2img endpoint (e.g. http://host:18542); when set
    # the ``generate_image`` tool is registered. Generated/read files live under
    # ``workspace_dir``.
    image_api_base_url: str | None = None
    workspace_dir: str = "./workspace"

    # Code-execution sandbox (Phase 21). "none" runs run_code directly on the
    # host (legacy behaviour); "podman" runs every command inside a rootless
    # container with only the workspace mounted — the host's secrets and the
    # rest of the filesystem stay out of reach.
    sandbox: Literal["none", "podman"] = "none"
    sandbox_image: str = "localhost/agent-core-sandbox:latest"
    sandbox_memory_mb: int = 2048
    sandbox_cpus: float = 2.0
    sandbox_pids_limit: int = 256

    # Outbound HTTP proxy for model providers / MCP (e.g. http://127.0.0.1:7890).
    # Applied to the standard HTTP_PROXY / HTTPS_PROXY env vars so every HTTP
    # client in the process (OpenAI SDK, langchain, MCP) picks it up.
    proxy_url: str | None = None
    # Hosts that must bypass the proxy (NO_PROXY), comma-separated. When a
    # proxy is configured, localhost/127.0.0.1 are always exempt by default;
    # add LAN service hosts (local model, txt2img...) so they stay direct.
    no_proxy: str | None = None


def apply_proxy(settings: Settings) -> None:
    """Export ``settings.proxy_url`` as standard proxy env vars (no override).

    ``NO_PROXY`` always exempts loopback hosts; ``settings.no_proxy`` appends
    more (LAN services must not be tunneled through the proxy).
    """
    if not settings.proxy_url:
        return
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.setdefault(var, settings.proxy_url)
    no_proxy = "localhost,127.0.0.1,::1"
    if settings.no_proxy:
        no_proxy = f"{no_proxy},{settings.no_proxy}"
    for var in ("NO_PROXY", "no_proxy"):
        os.environ.setdefault(var, no_proxy)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings (cached)."""
    settings = Settings()
    apply_proxy(settings)
    return settings
