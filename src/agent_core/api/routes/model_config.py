"""Console-editable model configuration.

The page reads the current override state (keys masked), writes partial
updates (persisted to SQLite and applied immediately to new model builds),
and can round-trip a tiny completion to verify a model actually works. It can
also register custom OpenAI-compatible endpoints (添加模型): probe the
endpoint's ``GET /models`` to discover ids, then pick the ones to expose as
``<name>:<model>`` specs.
"""

from __future__ import annotations

import os
import time

import httpx
from fastapi import APIRouter, HTTPException

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import (
    CustomModelOut,
    CustomModelUpsertRequest,
    ModelConfigOut,
    ModelConfigUpdate,
    ModelDiscoverOut,
    ModelDiscoverRequest,
    ModelVerifyOut,
    ModelVerifyRequest,
    ProviderKeyOut,
)
from agent_core.config.model_config import (
    CustomModel,
    ModelConfig,
    get_model_config,
    mask_secret,
    save_model_config,
)
from agent_core.config.settings import get_settings
from agent_core.runtime.model import PROVIDER_ENV_VARS, build_model

router = APIRouter(prefix="/model-config", tags=["model-config"])


def _key_status(provider: str, overrides: ModelConfig) -> ProviderKeyOut:
    env_var = PROVIDER_ENV_VARS[provider]
    page_key = overrides.api_keys.get(provider)
    env_key = os.environ.get(env_var)
    if page_key:
        return ProviderKeyOut(
            provider=provider, env_var=env_var, set=True, source="page",
            hint=mask_secret(page_key),
        )
    if env_key:
        return ProviderKeyOut(
            provider=provider, env_var=env_var, set=True, source="env",
            hint=mask_secret(env_key),
        )
    return ProviderKeyOut(provider=provider, env_var=env_var, set=False)


_BUILTIN_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}
"""Conventional endpoints for the built-in providers shown as cards."""


def _endpoint_cards(overrides: ModelConfig) -> list[CustomModelOut]:
    """Unified endpoint view: stored overrides plus synthesized built-ins.

    Every provider — built-in or user-added — shows up as the same card shape
    so the page stays uniform. A stored entry replaces its built-in card.
    """
    cards: list[CustomModelOut] = []
    seen: set[str] = set()
    for stored in overrides.custom_models:
        env_var = PROVIDER_ENV_VARS.get(stored.name)
        key = stored.api_key or (os.environ.get(env_var) if env_var else None)
        cards.append(
            CustomModelOut(
                name=stored.name,
                base_url=stored.base_url,
                api_format=stored.api_format,
                models=list(stored.models),
                key_hint=mask_secret(key) if key else None,
                builtin=stored.name in PROVIDER_ENV_VARS,
                context_window=stored.context_window,
            )
        )
        seen.add(stored.name)
    for provider in PROVIDER_ENV_VARS:
        if provider in seen:
            continue
        env_var = PROVIDER_ENV_VARS[provider]
        key = os.environ.get(env_var) or overrides.api_keys.get(provider)
        if provider == "local":
            base = overrides.local_base_url or os.environ.get("LOCAL_LLM_BASE_URL") or ""
        else:
            base = _BUILTIN_BASE_URLS.get(provider, "")
        cards.append(
            CustomModelOut(
                name=provider,
                base_url=base,
                api_format="openai",
                models=[],
                key_hint=mask_secret(key) if key else None,
                builtin=True,
            )
        )
    return cards


def _config_out(overrides: ModelConfig) -> ModelConfigOut:
    settings = get_settings()
    effective = overrides.model or settings.model
    return ModelConfigOut(
        model=overrides.model,
        model_source="page" if overrides.model else "env",
        effective_model=effective,
        local_base_url=next(
            (c.base_url or None for c in _endpoint_cards(overrides) if c.name == "local"),
            None,
        ),
        local_base_url_source="page" if overrides.local_base_url else "env",
        api_keys=[_key_status(provider, overrides) for provider in PROVIDER_ENV_VARS],
        custom_models=_endpoint_cards(overrides),
    )


@router.get("", response_model=ModelConfigOut)
def read_model_config(service: ServiceDep) -> ModelConfigOut:
    return _config_out(get_model_config())


@router.put("", response_model=ModelConfigOut)
def update_model_config(payload: ModelConfigUpdate, service: ServiceDep) -> ModelConfigOut:
    """Partial update: omitted fields stay, empty strings clear the override."""
    current = get_model_config()
    updated = current.model_copy()

    if payload.model is not None:
        updated.model = payload.model or None
    if payload.local_base_url is not None:
        updated.local_base_url = payload.local_base_url or None
    for provider, key in payload.api_keys.items():
        if provider not in PROVIDER_ENV_VARS:
            continue
        if key:
            updated.api_keys[provider] = key
        else:
            updated.api_keys.pop(provider, None)

    return _config_out(save_model_config(updated))


@router.post("/verify", response_model=ModelVerifyOut)
async def verify_model(payload: ModelVerifyRequest, service: ServiceDep) -> ModelVerifyOut:
    """Build the effective model and round-trip a one-line completion."""
    spec = payload.model or get_model_config().model or get_settings().model
    started = time.perf_counter()
    try:
        model = build_model(spec)
        response = await model.ainvoke("Reply with exactly: OK")
        text = getattr(response, "content", response)
        return ModelVerifyOut(
            ok=True,
            model=spec,
            latency_ms=round((time.perf_counter() - started) * 1000),
            reply=str(text)[:200],
        )
    except Exception as exc:  # noqa: BLE001 — every failure mode is a verify result
        return ModelVerifyOut(
            ok=False,
            model=spec,
            latency_ms=round((time.perf_counter() - started) * 1000),
            error=str(exc)[:500],
        )


# ------------------------------------------------------- custom endpoints


@router.post("/discover", response_model=ModelDiscoverOut)
async def discover_models(payload: ModelDiscoverRequest) -> ModelDiscoverOut:
    """Probe an OpenAI-compatible endpoint's ``GET /models`` for its list."""
    base = payload.base_url.rstrip("/")
    url = f"{base}/models"
    headers = {}
    if payload.api_key:
        headers["Authorization"] = f"Bearer {payload.api_key}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload_json = response.json()
    except httpx.HTTPError as exc:
        return ModelDiscoverOut(ok=False, models=[], error=f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 — any parse failure is a discover result
        return ModelDiscoverOut(ok=False, models=[], error=str(exc))

    data = payload_json.get("data") if isinstance(payload_json, dict) else payload_json
    models: list[str] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                models.append(str(item["id"]))
            elif isinstance(item, str):
                models.append(item)
    return ModelDiscoverOut(ok=True, models=sorted(models))


@router.put("/custom/{name}", response_model=ModelConfigOut)
def upsert_custom_model(name: str, payload: CustomModelUpsertRequest) -> ModelConfigOut:
    """Create or replace a custom endpoint registration (matched by name)."""
    if payload.api_format != "openai":
        raise HTTPException(
            status_code=422, detail=f"unsupported api_format '{payload.api_format}'"
        )
    current = get_model_config()
    existing = next((m for m in current.custom_models if m.name == name), None)
    # Blank key = "keep what's stored" so editing a card without retyping the
    # secret never wipes it (the dialog shows the masked hint in that case).
    entry = CustomModel(
        name=name,
        base_url=payload.base_url,
        api_format=payload.api_format,
        api_key=payload.api_key or (existing.api_key if existing else None),
        models=payload.models,
        context_window=payload.context_window
        or (existing.context_window if existing else None),
    )
    others = [m for m in current.custom_models if m.name != name]
    updated = current.model_copy(update={"custom_models": [*others, entry]})
    return _config_out(save_model_config(updated))


@router.delete("/custom/{name}", response_model=ModelConfigOut)
def delete_custom_model(name: str) -> ModelConfigOut:
    """Remove a custom endpoint registration."""
    current = get_model_config()
    if not any(m.name == name for m in current.custom_models):
        raise HTTPException(status_code=404, detail=f"custom model '{name}' not found")
    updated = current.model_copy(
        update={"custom_models": [m for m in current.custom_models if m.name != name]}
    )
    return _config_out(save_model_config(updated))
