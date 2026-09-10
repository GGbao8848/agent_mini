"""Model factory: ``provider:model`` specs -> LangChain chat models.

Supported providers: ``openai``, ``openrouter`` and ``local`` (any
OpenAI-compatible self-hosted endpoint: vLLM, llama.cpp server, LMDeploy...).
Provider API keys resolve with console overrides first (see
:mod:`agent_core.config.model_config`), then standard environment variables
(``OPENAI_API_KEY``, ``OPENROUTER_API_KEY``, ``LOCAL_LLM_API_KEY``); they are
never part of Settings or code. The local endpoint address comes from the
overrides or ``LOCAL_LLM_BASE_URL``.
Outbound proxy configuration is applied by
:func:`agent_core.config.settings.get_settings`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from agent_core.config.model_config import get_model_config
from agent_core.config.settings import Settings, get_settings
from agent_core.errors.exceptions import ConfigurationError

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

PROVIDER_ENV_VARS: dict[str, str] = {
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
    """Build the chat model for ``spec``, falling back to the active config.

    Resolution order for the default model and keys: console overrides →
    environment / ``.env`` → ``settings.model``.
    """
    resolved = settings or get_settings()
    overrides = get_model_config()
    provider, model = parse_model_spec(spec or overrides.model or resolved.model)

    # Endpoints registered (or overridden) on the model-config page win over
    # the built-in provider wiring: "<name>:<model>" builds against the stored
    # base_url / api_format, with the key falling back to the built-in env var.
    custom = next((m for m in overrides.custom_models if m.name == provider), None)
    if custom is not None:
        fallback_var = PROVIDER_ENV_VARS.get(provider)
        custom_key = (
            custom.api_key
            or (os.environ.get(fallback_var) if fallback_var else None)
            or "local"
        )
        return _build_custom(
            model,
            custom,
            api_key=custom_key,
            streaming=resolved.model_streaming,
        )

    if provider == "local":
        return _build_local(model, overrides.local_base_url, streaming=resolved.model_streaming)

    env_var: str | None = PROVIDER_ENV_VARS.get(provider)
    if env_var is None:
        raise ConfigurationError(
            f"Unsupported model provider '{provider}'",
            details={"provider": provider, "supported": sorted(PROVIDER_ENV_VARS)},
        )
    api_key: str | None = overrides.api_keys.get(provider) or os.environ.get(env_var)
    if not api_key:
        raise ConfigurationError(
            f"Missing API key for model provider '{provider}'; set {env_var} "
            "or configure it on the console's 模型配置 page",
            details={"provider": provider, "env_var": env_var},
        )

    if provider == "openrouter":
        return _chat_model(
            model,
            api_key,
            base_url=OPENROUTER_BASE_URL,
            streaming=resolved.model_streaming,
        )
    # The official OpenAI endpoint: langchain-openai already enables streaming
    # usage accounting there, so the default constructor is correct.
    return ChatOpenAI(
        model=model,
        api_key=SecretStr(api_key),
        temperature=0,
        streaming=resolved.model_streaming,
    )


def _build_custom(
    model: str,
    endpoint: Any,
    *,
    api_key: str,
    streaming: bool = True,
) -> BaseChatModel:
    """Build the client for a console-registered endpoint.

    Honors the endpoint's ``api_format`` (openai-compatible, OpenAI Responses,
    Anthropic Messages) and the per-model context window, so an endpoint that
    speaks a non-default protocol actually works instead of silently using the
    Chat Completions shape.
    """
    window = endpoint.window_for(model)
    fmt = (endpoint.api_format or "openai").lower()
    if fmt == "anthropic":
        return _anthropic_model(
            model, api_key, base_url=endpoint.base_url, context_window=window
        )
    return _chat_model(
        model,
        api_key,
        base_url=endpoint.base_url,
        streaming=streaming,
        context_window=window,
        # "responses" targets OpenAI's Responses API; the default stays the
        # broadly-compatible chat-completions shape (vLLM/Ollama/OpenRouter).
        use_responses_api=fmt == "responses",
    )


def _anthropic_model(
    model: str,
    api_key: str,
    *,
    base_url: str | None = None,
    context_window: int | None = None,
) -> BaseChatModel:
    """ChatAnthropic client for an Anthropic-Messages endpoint.

    langchain-anthropic is an optional dependency: a deployment that never uses
    an Anthropic endpoint should not have to install it, so the import is local
    and a missing package produces a clear configuration error.
    """
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise ConfigurationError(
            "api_format 'anthropic' requires the langchain-anthropic package; "
            "install it (uv add langchain-anthropic) to use this endpoint",
            details={"provider": "anthropic"},
        ) from exc
    instance = ChatAnthropic(
        model=model,
        api_key=SecretStr(api_key),
        base_url=base_url,
        temperature=0,
        max_tokens=4096,
    )
    if context_window is not None:
        instance.profile = {"max_input_tokens": context_window}
    return instance


def _chat_model(
    model: str,
    api_key: str,
    *,
    base_url: str | None = None,
    streaming: bool = True,
    context_window: int | None = None,
    use_responses_api: bool = False,
) -> ChatOpenAI:
    """Chat model for self-hosted / OpenAI-compatible endpoints.

    ``stream_usage`` must be explicit here: langchain-openai only turns usage
    streaming on for the official OpenAI base URL, so against vLLM & friends
    the default is off — and without it every streamed response carries no
    token counts, which silently zeroes the run's usage, the budget
    middleware's verdicts and the console's token display.

    ``context_window`` (when configured) is injected as the model profile's
    ``max_input_tokens``: deepagents' summarization middleware keys its
    trigger off that field, so a self-hosted model gets its real-window
    fraction instead of the 170k flat default that assumes giant frontier
    models.
    """
    instance = ChatOpenAI(
        model=model,
        api_key=SecretStr(api_key),
        base_url=base_url,
        temperature=0,
        streaming=streaming,
        stream_usage=True,
        use_responses_api=use_responses_api,
    )
    if context_window is not None:
        instance.profile = {"max_input_tokens": context_window}
    return instance


def _build_local(
    model: str, base_url_override: str | None = None, *, streaming: bool = True
) -> BaseChatModel:
    """Any OpenAI-compatible self-hosted endpoint (vLLM, llama.cpp server, ...).

    ``LOCAL_LLM_API_KEY`` (or the console override) is optional — many local
    servers run without auth — but ChatOpenAI needs a non-empty key value, so
    a placeholder is used.
    """
    base_url = base_url_override or os.environ.get("LOCAL_LLM_BASE_URL")
    if not base_url:
        raise ConfigurationError(
            "Local model provider selected but no endpoint is configured "
            "(LOCAL_LLM_BASE_URL or the console's 模型配置 page)",
            details={"provider": "local", "env_var": "LOCAL_LLM_BASE_URL"},
        )
    overrides = get_model_config()
    api_key = overrides.api_keys.get("local") or os.environ.get("LOCAL_LLM_API_KEY") or "local"
    return _chat_model(model, api_key, base_url=base_url, streaming=streaming)
