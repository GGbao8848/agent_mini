"""Model factory: ``provider:model`` specs -> LangChain chat models.

Supported providers: ``openai``, ``openrouter`` and ``local`` (any
OpenAI-compatible self-hosted endpoint: vLLM, llama.cpp server, LMDeploy...).
Provider API keys come from standard environment variables (``OPENAI_API_KEY``,
``OPENROUTER_API_KEY``, ``LOCAL_LLM_API_KEY``); they are never part of Settings
or code. The local endpoint address is configured via ``LOCAL_LLM_BASE_URL``.
Outbound proxy configuration is applied by
:func:`agent_core.config.settings.get_settings`.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent_core.config.settings import Settings, get_settings
from agent_core.errors.exceptions import ConfigurationError

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_API_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "local": "LOCAL_LLM_API_KEY",
}

ModelFactory = Callable[[str | None], BaseChatModel]
"""Builds the chat model for a spec-level model string (None = default)."""


def parse_model_spec(spec: str) -> tuple[str, str]:
    """Split ``provider:model``; a bare model name defaults to provider ``openai``."""
    provider, sep, model = spec.partition(":")
    if not sep:
        return "openai", spec
    if not provider or not model:
        raise ConfigurationError(
            f"Invalid model spec '{spec}'; expected 'provider:model'",
            details={"spec": spec},
        )
    return provider, model


def build_model(spec: str | None, *, settings: Settings | None = None) -> BaseChatModel:
    """Build the chat model for ``spec``, falling back to ``settings.model``."""
    resolved = settings or get_settings()
    provider, model = parse_model_spec(spec or resolved.model)

    if provider == "local":
        return _build_local(model)

    env_var = _API_KEY_ENV.get(provider)
    if env_var is None:
        raise ConfigurationError(
            f"Unsupported model provider '{provider}'",
            details={"provider": provider, "supported": sorted(_API_KEY_ENV)},
        )
    api_key = os.environ.get(env_var)
    if not api_key:
        raise ConfigurationError(
            f"Missing API key for model provider '{provider}'; set {env_var}",
            details={"provider": provider, "env_var": env_var},
        )

    if provider == "openrouter":
        return ChatOpenAI(
            model=model,
            api_key=SecretStr(api_key),
            base_url=OPENROUTER_BASE_URL,
            temperature=0,
        )
    return ChatOpenAI(model=model, api_key=SecretStr(api_key), temperature=0)


def _build_local(model: str) -> BaseChatModel:
    """Any OpenAI-compatible self-hosted endpoint (vLLM, llama.cpp server, ...).

    ``LOCAL_LLM_API_KEY`` is optional — many local servers run without auth —
    but ChatOpenAI needs a non-empty key value, so a placeholder is used.
    """
    base_url = os.environ.get("LOCAL_LLM_BASE_URL")
    if not base_url:
        raise ConfigurationError(
            "Local model provider selected but LOCAL_LLM_BASE_URL is not set "
            "(e.g. http://10.0.0.5:8000/v1)",
            details={"provider": "local", "env_var": "LOCAL_LLM_BASE_URL"},
        )
    api_key = os.environ.get("LOCAL_LLM_API_KEY") or "local"
    return ChatOpenAI(
        model=model,
        api_key=SecretStr(api_key),
        base_url=base_url,
        temperature=0,
    )
