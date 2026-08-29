"""Shared pytest configuration.

Tests are hermetic against the developer's real ``.env`` (which carries live
tokens, sandbox and database settings on a deployment machine): an autouse
fixture replaces the cached ``get_settings`` used by the composition root,
the API layer and the runtime with one that ignores ``.env`` entirely.
Individual tests can still set environment variables explicitly.
"""

from __future__ import annotations

import pytest

from agent_core.api import app as api_app
from agent_core.application import bootstrap as bootstrap_mod
from agent_core.config.settings import Settings, get_settings
from agent_core.runtime import builder as builder_mod
from agent_core.runtime import runtime as runtime_mod

# Modules that imported ``get_settings`` by name and resolve settings lazily.
_SETTINGS_SITES = (api_app, bootstrap_mod, runtime_mod, builder_mod)


@pytest.fixture(autouse=True)
def hermetic_settings(monkeypatch: pytest.MonkeyPatch):
    def _fresh() -> Settings:
        return Settings(_env_file=None)

    for site in _SETTINGS_SITES:
        monkeypatch.setattr(site, "get_settings", _fresh)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
