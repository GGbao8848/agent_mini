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

from pydantic import BaseModel, Field

from agent_core.persistence.store import SqliteStore

_KIND = "model_config"
_KEY = "default"
_MASK_TAIL = 4


class ModelConfig(BaseModel):
    """Console-provided model configuration; every field optional."""

    model: str | None = None
    """Default model spec (``provider:model``) overriding ``Settings.model``."""

    api_keys: dict[str, str] = Field(default_factory=dict)
    """Per-provider API keys (``openai`` / ``openrouter`` / ``local``)."""

    local_base_url: str | None = None
    """Self-hosted endpoint for the ``local`` provider (OpenAI-compatible)."""


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
