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
    ModelEntryIn,
    ModelEntryOut,
    ModelOptionOut,
    ModelVerifyOut,
    ModelVerifyRequest,
    ProviderKeyOut,
    ProviderKeyRevealOut,
    ProviderModelsAddRequest,
    ProviderUpdateRequest,
)
from agent_core.config.model_config import (
    CustomModel,
    ModelConfig,
    ModelEntry,
    catalog_from_models,
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
    """Unified provider view: stored overrides plus synthesized built-ins.

    Every provider — built-in or user-added — shows up as the same card shape
    so the page stays uniform. A stored entry replaces its built-in card.
    """
    cards: list[CustomModelOut] = []
    seen: set[str] = set()
    for stored in overrides.custom_models:
        env_var = PROVIDER_ENV_VARS.get(stored.name)
        key = stored.api_key or (os.environ.get(env_var) if env_var else None)
        card = CustomModelOut.of(stored)
        card.key_hint = mask_secret(key) if key else None
        card.builtin = stored.name in PROVIDER_ENV_VARS
        cards.append(card)
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
                catalog=[],
                key_hint=mask_secret(key) if key else None,
                builtin=True,
                enabled=True,
            )
        )
    return cards


def _available_models(cards: list[CustomModelOut]) -> list[ModelOptionOut]:
    """Every enabled model of every enabled provider, for the chat picker."""
    options: list[ModelOptionOut] = []
    for card in cards:
        if not card.enabled:
            continue
        entries = card.catalog or [
            ModelEntryOut(id=model_id) for model_id in card.models
        ]
        for entry in entries:
            if not entry.enabled:
                continue
            options.append(
                ModelOptionOut(
                    spec=f"{card.name}:{entry.id}",
                    label=f"{card.name} · {entry.id}",
                    provider=card.name,
                    model=entry.id,
                    context_window=entry.context_window or card.context_window,
                )
            )
    return options


def _config_out(overrides: ModelConfig) -> ModelConfigOut:
    settings = get_settings()
    effective = overrides.model or settings.model
    cards = _endpoint_cards(overrides)
    return ModelConfigOut(
        model=overrides.model,
        model_source="page" if overrides.model else "env",
        effective_model=effective,
        local_base_url=next(
            (c.base_url or None for c in cards if c.name == "local"),
            None,
        ),
        local_base_url_source="page" if overrides.local_base_url else "env",
        api_keys=[_key_status(provider, overrides) for provider in PROVIDER_ENV_VARS],
        custom_models=cards,
        available_models=_available_models(cards),
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


def _models_url(base_url: str, api_format: str) -> str:
    """The endpoint's model-list URL for its wire format.

    OpenAI-compatible servers expose ``{base}/models``; Anthropic's list lives
    at ``{origin}/v1/models``, so a base without ``/v1`` gets it appended.
    """
    base = base_url.rstrip("/")
    if api_format == "anthropic" and not base.endswith("/v1"):
        return f"{base}/v1/models"
    return f"{base}/models"


def _model_list_headers(api_key: str | None, api_format: str) -> dict[str, str]:
    if not api_key:
        return {}
    if api_format == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {api_key}"}


async def _probe_models(
    base_url: str, api_format: str, api_key: str | None
) -> ModelDiscoverOut:
    """Shared probe: GET the endpoint's model list and normalize the ids."""
    url = _models_url(base_url, api_format)
    headers = _model_list_headers(api_key, api_format)
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


@router.post("/discover", response_model=ModelDiscoverOut)
async def discover_models(payload: ModelDiscoverRequest) -> ModelDiscoverOut:
    """Probe an endpoint's model list with an explicit URL/key (pre-save flow)."""
    return await _probe_models(payload.base_url, payload.api_format, payload.api_key)


_API_FORMATS = frozenset({"openai", "responses", "anthropic"})


@router.get("/custom/{name}/key", response_model=ProviderKeyRevealOut)
def reveal_provider_key(name: str) -> ProviderKeyRevealOut:
    """Reveal a provider's stored/effective API key on explicit request.

    The key is deliberately kept OUT of the model-config payload (only a masked
    hint is returned there), so the page cannot accidentally leak it. Viewing a
    key is an explicit operator action, so it gets its own endpoint instead of
    being included in every list response.
    """
    if not any(c.name == name for c in _endpoint_cards(get_model_config())):
        raise HTTPException(status_code=404, detail=f"provider '{name}' not found")
    stored = next((m for m in get_model_config().custom_models if m.name == name), None)
    env_var = PROVIDER_ENV_VARS.get(name)
    env_key = os.environ.get(env_var) if env_var else None
    key = (stored.api_key if stored else None) or env_key
    if not key:
        return ProviderKeyRevealOut(name=name, api_key=None, source=None)
    source = "page" if (stored and stored.api_key) else "env"
    return ProviderKeyRevealOut(name=name, api_key=key, source=source)


@router.put("/custom/{name}", response_model=ModelConfigOut)
def upsert_custom_model(name: str, payload: CustomModelUpsertRequest) -> ModelConfigOut:
    """Create or replace a provider registration (matched by name)."""
    if payload.api_format not in _API_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported api_format '{payload.api_format}'; "
            f"expected one of {sorted(_API_FORMATS)}",
        )
    current = get_model_config()
    existing = next((m for m in current.custom_models if m.name == name), None)
    # Blank key = "keep what's stored" so editing a card without retyping the
    # secret never wipes it (the dialog shows the masked hint in that case).
    catalog = (
        [ModelEntry(id=e.id, context_window=e.context_window, enabled=e.enabled)
         for e in payload.catalog]
        if payload.catalog is not None
        else catalog_from_models(
            payload.models,
            existing=existing.catalog if existing else None,
            default_window=payload.context_window,
        )
    )
    entry = CustomModel(
        name=name,
        base_url=payload.base_url,
        api_format=payload.api_format,
        api_key=payload.api_key or (existing.api_key if existing else None),
        models=[e.id for e in catalog],
        catalog=catalog,
        context_window=payload.context_window
        or (existing.context_window if existing else None),
        enabled=payload.enabled,
        builtin=name in PROVIDER_ENV_VARS,
    )
    others = [m for m in current.custom_models if m.name != name]
    updated = current.model_copy(update={"custom_models": [*others, entry]})
    return _config_out(save_model_config(updated))


@router.patch("/custom/{name}", response_model=ModelConfigOut)
def update_provider(name: str, payload: ProviderUpdateRequest) -> ModelConfigOut:
    """Partial edit of one provider: rename, enable/disable, endpoint fields.

    Renaming a built-in provider is refused (the name doubles as the provider
    id and the key's env var); custom providers may be renamed freely.
    """
    current = get_model_config()
    index = next(
        (i for i, m in enumerate(current.custom_models) if m.name == name), None
    )
    if index is None:
        # No stored row yet (e.g. a built-in shown from .env): materialize one
        # from the synthesized card so the edit has something to persist.
        card = next((c for c in _endpoint_cards(current) if c.name == name), None)
        if card is None:
            raise HTTPException(status_code=404, detail=f"provider '{name}' not found")
        base = CustomModel(
            name=name,
            base_url=card.base_url or "",
            api_format=card.api_format,
            models=[],
            catalog=[],
            enabled=True,
            builtin=name in PROVIDER_ENV_VARS,
        )
        current = current.model_copy(
            update={"custom_models": [*current.custom_models, base]}
        )
        index = len(current.custom_models) - 1

    entry = current.custom_models[index]
    if payload.name is not None and payload.name != entry.name:
        if entry.name in PROVIDER_ENV_VARS:
            raise HTTPException(
                status_code=422, detail=f"built-in provider '{entry.name}' cannot be renamed"
            )
        if any(m.name == payload.name for m in current.custom_models):
            raise HTTPException(
                status_code=409, detail=f"provider '{payload.name}' already exists"
            )
    if payload.api_format is not None and payload.api_format not in _API_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported api_format '{payload.api_format}'; "
            f"expected one of {sorted(_API_FORMATS)}",
        )

    def _apply(model: CustomModel) -> CustomModel:
        update: dict[str, object] = {}
        if payload.name is not None:
            update["name"] = payload.name
        if payload.base_url is not None:
            update["base_url"] = payload.base_url
        if payload.api_format is not None:
            update["api_format"] = payload.api_format
        if payload.api_key is not None:
            # Blank clears the stored key (falls back to the env var).
            update["api_key"] = payload.api_key or None
        if payload.enabled is not None:
            update["enabled"] = payload.enabled
        if payload.context_window is not None:
            update["context_window"] = payload.context_window or None
        return model.model_copy(update=update)

    models = [
        _apply(m) if i == index else m for i, m in enumerate(current.custom_models)
    ]
    updated = current.model_copy(update={"custom_models": models})
    return _config_out(save_model_config(updated))


@router.put("/custom/{name}/models/{model_id:path}", response_model=ModelConfigOut)
def upsert_provider_model(
    name: str, model_id: str, payload: ModelEntryIn
) -> ModelConfigOut:
    """Add or update one model under a provider (id, window, enabled)."""
    current = get_model_config()
    index = next(
        (i for i, m in enumerate(current.custom_models) if m.name == name), None
    )
    if index is None:
        raise HTTPException(status_code=404, detail=f"provider '{name}' not found")
    entry = current.custom_models[index]
    others = [e for e in entry.catalog if e.id != model_id]
    catalog = [
        *others,
        ModelEntry(id=model_id, context_window=payload.context_window, enabled=payload.enabled),
    ]
    updated_entry = entry.model_copy(
        update={"catalog": catalog, "models": [e.id for e in catalog]}
    )
    models = [
        updated_entry if i == index else m for i, m in enumerate(current.custom_models)
    ]
    updated = current.model_copy(update={"custom_models": models})
    return _config_out(save_model_config(updated))


@router.delete("/custom/{name}/models/{model_id:path}", response_model=ModelConfigOut)
def delete_provider_model(name: str, model_id: str) -> ModelConfigOut:
    """Remove one model from a provider."""
    current = get_model_config()
    index = next(
        (i for i, m in enumerate(current.custom_models) if m.name == name), None
    )
    if index is None:
        raise HTTPException(status_code=404, detail=f"provider '{name}' not found")
    entry = current.custom_models[index]
    catalog = [e for e in entry.catalog if e.id != model_id]
    updated_entry = entry.model_copy(
        update={"catalog": catalog, "models": [e.id for e in catalog]}
    )
    models = [
        updated_entry if i == index else m for i, m in enumerate(current.custom_models)
    ]
    updated = current.model_copy(update={"custom_models": models})
    return _config_out(save_model_config(updated))


@router.post("/custom/{name}/discover", response_model=ModelDiscoverOut)
async def discover_provider_models(name: str) -> ModelDiscoverOut:
    """Probe a SAVED provider's model list using its stored/effective key.

    The browser never holds the plaintext key, so this runs server-side: it
    resolves the key exactly as ``build_model`` would (page override, else the
    provider's env var) and lists what the endpoint offers — the data source for
    the page's 「探测添加」.
    """
    card = next((c for c in _endpoint_cards(get_model_config()) if c.name == name), None)
    if card is None:
        raise HTTPException(status_code=404, detail=f"provider '{name}' not found")
    stored = next((m for m in get_model_config().custom_models if m.name == name), None)
    env_var = PROVIDER_ENV_VARS.get(name)
    key = (stored.api_key if stored else None) or (os.environ.get(env_var) if env_var else None)
    return await _probe_models(card.base_url, card.api_format, key)


@router.post("/custom/{name}/models", response_model=ModelConfigOut)
def add_provider_models(name: str, payload: ProviderModelsAddRequest) -> ModelConfigOut:
    """Add several models at once (the 「探测添加」 batch).

    Existing ids are left untouched (so a re-probe never resets a window the
    user already set); new ids are appended with the given/default window.
    """
    current = get_model_config()
    index = next((i for i, m in enumerate(current.custom_models) if m.name == name), None)
    if index is None:
        raise HTTPException(status_code=404, detail=f"provider '{name}' not found")
    entry = current.custom_models[index]
    known = {e.id for e in entry.catalog}
    added = [
        ModelEntry(id=model_id, context_window=payload.context_window, enabled=True)
        for model_id in payload.models
        if model_id and model_id not in known
    ]
    if not added:
        return _config_out(current)
    catalog = [*entry.catalog, *added]
    updated_entry = entry.model_copy(
        update={"catalog": catalog, "models": [e.id for e in catalog]}
    )
    models = [updated_entry if i == index else m for i, m in enumerate(current.custom_models)]
    return _config_out(save_model_config(current.model_copy(update={"custom_models": models})))


@router.delete("/custom/{name}", response_model=ModelConfigOut)
def delete_custom_model(name: str) -> ModelConfigOut:
    """Remove a custom provider registration."""
    current = get_model_config()
    if not any(m.name == name for m in current.custom_models):
        raise HTTPException(status_code=404, detail=f"custom model '{name}' not found")
    updated = current.model_copy(
        update={"custom_models": [m for m in current.custom_models if m.name != name]}
    )
    return _config_out(save_model_config(updated))
