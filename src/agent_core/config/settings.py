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

from dotenv import dotenv_values
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

    workspace_dir: str = "./workspace"

    # Code-execution backend. "host" runs run_code on the host with an
    # agent-managed venv (system site-packages visible; installs land in the
    # venv, never the system); "podman" runs every command inside a rootless
    # container with only the workspace mounted — the host's secrets and the
    # rest of the filesystem stay out of reach. "none" is a deprecated alias
    # of "host" kept for old configs.
    sandbox: Literal["none", "host", "podman"] = "host"
    sandbox_image: str = "localhost/agent-core-sandbox:latest"
    sandbox_memory_mb: int = 2048
    sandbox_cpus: float = 2.0
    sandbox_pids_limit: int = 256

    # Agent-managed Python environment for the "host" sandbox backend (venv
    # with --system-site-packages). Defaults to ~/.agent_core/agent-env.
    agent_env_dir: str | None = None

    # Console (Phase 22): when set, every /v1 and /console request must carry
    # this shared token (X-Console-Token header or ?token=) — a minimal guard
    # for a console exposed on the LAN. Unset means open access.
    console_token: str | None = None

    # Outbound HTTP proxy for model providers / MCP (e.g. http://127.0.0.1:7890).
    # Applied to the standard HTTP_PROXY / HTTPS_PROXY env vars so every HTTP
    # client in the process (OpenAI SDK, langchain, MCP) picks it up.
    proxy_url: str | None = None
    # Hosts that must bypass the proxy (NO_PROXY), comma-separated. When a
    # proxy is configured, localhost/127.0.0.1 are always exempt by default;
    # add LAN service hosts (local model...) so they stay direct.
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
    # Read the .env file so provider SDKs and the notification channel — which
    # read OPENROUTER_API_KEY, TELEGRAM_BOT_TOKEN, ... directly from os.environ
    # — see the same values as Settings. pydantic-settings maps AGENT_CORE_*
    # fields itself, so those must NOT leak into os.environ: that would corrupt
    # hermetic tests that build Settings(_env_file=None). Real environment
    # variables are authoritative over the .env file — keys that already exist
    # in os.environ are never overwritten here nor popped below.
    added: list[str] = []
    env_file = dotenv_values(".env")
    for key, value in env_file.items():
        if value is not None and key not in os.environ:
            os.environ.setdefault(key, value)
            added.append(key)
    # AGENT_CORE_* keys this function itself injected from the .env file stay
    # out of os.environ: pydantic reads them itself, and leaking them breaks
    # hermetic tests that build Settings(_env_file=None). Real environment
    # variables are left untouched.
    for key in added:
        if key.startswith("AGENT_CORE_"):
            os.environ.pop(key, None)
    settings = Settings()
    apply_proxy(settings)
    return settings
