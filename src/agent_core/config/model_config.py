"""Console-editable model configuration overrides.

Precedence in :func:`agent_core.runtime.model.build_model`: overrides set
from the console (this module, persisted to SQLite) → environment / ``.env``
variables → ``Settings`` defaults. The state is process-global because model
building happens lazily deep inside the runtime, far from any request scope.

API keys are write-only secrets: they are stored in the database alongside the
console's other facts but never returned by the API — responses carry only a
masked hint of the active key.
"""

from __future__ import annotations

import threading

from pydantic import BaseModel, Field, model_validator

from agent_core.persistence.store import SqliteStore

_KIND = "model_config"
_KEY = "default"
_MASK_TAIL = 4


class ModelEntry(BaseModel):
    """One model id within a provider, with its own context window.

    The window is per-model (not per-provider) because a single endpoint often
    serves models with very different windows — the console's context gauge and
    the summarization trigger both key off it.
    """

    id: str = Field(min_length=1)
    context_window: int | None = Field(default=None, gt=0)
    enabled: bool = True
    """Disabled models stay registered but are not offered in the chat picker."""


class CustomModel(BaseModel):
    """A provider endpoint registered from the console (built-in or custom)."""

    name: str = Field(min_length=1)
    """Display name; doubles as the provider id in ``provider:model`` specs."""
    base_url: str = Field(min_length=1)
    """Endpoint root, e.g. ``http://host:8000/v1``."""
    api_format: str = "openai"
    """Wire format: ``openai`` | ``responses`` | ``anthropic``."""
    api_key: str | None = None
    """Write-only secret; never returned by the API (masked hint only)."""
    models: list[str] = Field(default_factory=list)
    """Model ids kept for backward compatibility (see :attr:`catalog`)."""
    catalog: list[ModelEntry] = Field(default_factory=list)
    """Per-model entries (id + context window + enabled)."""
    context_window: int | None = None
    """Provider-level default window, used for models without their own."""
    enabled: bool = True
    """The whole provider is on/off (disabled ⇒ its models leave the picker)."""
    builtin: bool = False
    """True for the built-in providers (openai/openrouter/local)."""

    def window_for(self, model_id: str) -> int | None:
        """The configured context window for ``model_id`` (model → provider)."""
        for entry in self.catalog:
            if entry.id == model_id and entry.context_window is not None:
                return entry.context_window
        return self.context_window

    def enabled_models(self) -> list[str]:
        """Model ids offered to the picker (respecting per-model + provider flags)."""
        if not self.enabled:
            return []
        if self.catalog:
            return [m.id for m in self.catalog if m.enabled]
        return list(self.models)

    def model_ids(self) -> list[str]:
        """All model ids, enabled or not (catalog when present, else ``models``)."""
        return [m.id for m in self.catalog] if self.catalog else list(self.models)

    @model_validator(mode="after")
    def _backfill_catalog(self) -> CustomModel:
        """Give configs stored before the catalog existed a per-model view.

        Older rows (and older API clients) only carry ``models`` and a
        provider-level ``context_window``; lift them into ``catalog`` so the
        page has one consistent shape to render.
        """
        if not self.catalog and self.models:
            self.catalog = [
                ModelEntry(id=model_id, context_window=self.context_window)
                for model_id in self.models
            ]
        if self.catalog and not self.models:
            # Keep the flat list in step for any caller still reading it.
            self.models = [m.id for m in self.catalog]
        return self


def catalog_from_models(
    model_ids: list[str],
    *,
    existing: list[ModelEntry] | None = None,
    default_window: int | None = None,
) -> list[ModelEntry]:
    """Build a catalog from a flat id list, preserving existing per-model values.

    Used when an older client (or the discover flow) sends ``models: [id, ...]``
    without per-model metadata: known ids keep their window/enabled, new ids get
    ``default_window``.
    """
    prior = {entry.id: entry for entry in (existing or [])}
    catalog: list[ModelEntry] = []
    for model_id in model_ids:
        if model_id in prior:
            catalog.append(prior[model_id])
        else:
            catalog.append(ModelEntry(id=model_id, context_window=default_window))
    return catalog


class ModelConfig(BaseModel):
    """Console-provided model configuration; every field optional."""

    model: str | None = None
    """Default model spec (``provider:model``) overriding ``Settings.model``."""

    api_keys: dict[str, str] = Field(default_factory=dict)
    """Per-provider API keys (``openai`` / ``openrouter`` / ``local``)."""

    local_base_url: str | None = None
    """Self-hosted endpoint for the ``local`` provider (OpenAI-compatible)."""

    custom_models: list[CustomModel] = Field(default_factory=list)
    """User-added endpoints from the 模型配置 page's 添加模型 dialog."""


_lock = threading.Lock()
_config = ModelConfig()
_store: SqliteStore | None = None


def mask_secret(value: str) -> str:
    """Masked hint safe to return from the API (last few chars only)."""
    if len(value) <= _MASK_TAIL:
        return "••••"
    return f"••••{value[-_MASK_TAIL:]}"


def load_model_config(store: SqliteStore | None) -> ModelConfig:
    """Bind the persistence store and load persisted overrides (boot time)."""
    global _store, _config
    with _lock:
        _store = store
        _config = ModelConfig()
        if store is not None:
            for key, data in store.load_items(_KIND):
                if key == _KEY:
                    _config = ModelConfig.model_validate_json(data)
        return _config.model_copy()


def get_model_config() -> ModelConfig:
    with _lock:
        return _config.model_copy()


def save_model_config(config: ModelConfig) -> ModelConfig:
    """Replace the active config and persist it (write-through)."""
    with _lock:
        global _config
        _config = config.model_copy()
        if _store is not None:
            _store.save_item(_KIND, _KEY, _config.model_dump_json())
        return _config.model_copy()
