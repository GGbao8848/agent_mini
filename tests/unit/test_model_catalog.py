"""Model catalog: per-model windows, provider/model enable, API formats (R27).

The model-config page gained a provider + per-model catalog. These tests pin the
domain rules (catalog backfill, window resolution, enablement) and that
``build_model`` actually honors a provider's ``api_format`` and per-model window
— the parts a console-only change could silently get wrong.
"""

from __future__ import annotations

import pytest

from agent_core.config.model_config import (
    CustomModel,
    ModelConfig,
    ModelEntry,
    catalog_from_models,
    load_model_config,
    save_model_config,
)
from agent_core.errors.exceptions import ConfigurationError
from agent_core.runtime.model import build_model


@pytest.fixture(autouse=True)
def _reset_overrides():
    load_model_config(None)
    yield
    load_model_config(None)


# --------------------------------------------------------------- catalog


def test_legacy_models_backfill_into_catalog() -> None:
    """A row stored before the catalog existed gets a per-model view."""
    endpoint = CustomModel(
        name="legacy", base_url="http://h/v1", models=["a", "b"], context_window=8000
    )
    assert [e.id for e in endpoint.catalog] == ["a", "b"]
    assert all(e.context_window == 8000 for e in endpoint.catalog)
    assert endpoint.models == ["a", "b"]  # flat list kept in step


def test_per_model_window_wins_over_provider_default() -> None:
    endpoint = CustomModel(
        name="p",
        base_url="http://h/v1",
        context_window=1000,
        catalog=[ModelEntry(id="big", context_window=5000), ModelEntry(id="small")],
    )
    assert endpoint.window_for("big") == 5000
    assert endpoint.window_for("small") == 1000  # falls back to provider default


def test_window_for_unknown_model_uses_provider_default() -> None:
    endpoint = CustomModel(name="p", base_url="http://h/v1", context_window=777, catalog=[])
    assert endpoint.window_for("whatever") == 777


def test_enabled_models_respects_provider_and_model_flags() -> None:
    endpoint = CustomModel(
        name="p",
        base_url="http://h/v1",
        catalog=[
            ModelEntry(id="on", enabled=True),
            ModelEntry(id="off", enabled=False),
        ],
    )
    assert endpoint.enabled_models() == ["on"]
    assert endpoint.model_ids() == ["on", "off"]  # disabled still registered

    disabled_provider = endpoint.model_copy(update={"enabled": False})
    assert disabled_provider.enabled_models() == []


def test_catalog_from_models_preserves_existing_values() -> None:
    existing = [ModelEntry(id="a", context_window=111, enabled=False)]
    catalog = catalog_from_models(["a", "c"], existing=existing, default_window=999)
    assert catalog[0].context_window == 111
    assert catalog[0].enabled is False
    assert catalog[1].id == "c" and catalog[1].context_window == 999


# ------------------------------------------------------------ build_model


def test_build_model_uses_custom_endpoint_base_url() -> None:
    save_model_config(
        ModelConfig(
            custom_models=[
                CustomModel(
                    name="myvllm", base_url="http://10.0.0.5:8000/v1", models=["m"]
                )
            ]
        )
    )
    model = build_model("myvllm:m")
    assert str(model.openai_api_base).rstrip("/") == "http://10.0.0.5:8000/v1"


def test_build_model_applies_per_model_context_window() -> None:
    save_model_config(
        ModelConfig(
            custom_models=[
                CustomModel(
                    name="p",
                    base_url="http://h/v1",
                    catalog=[ModelEntry(id="ctxmodel", context_window=32000)],
                )
            ]
        )
    )
    model = build_model("p:ctxmodel")
    assert model.profile.get("max_input_tokens") == 32000


def test_responses_format_sets_use_responses_api() -> None:
    save_model_config(
        ModelConfig(
            custom_models=[
                CustomModel(
                    name="r",
                    base_url="http://h/v1",
                    api_format="responses",
                    models=["m"],
                )
            ]
        )
    )
    model = build_model("r:m")
    assert model.use_responses_api is True


def test_anthropic_format_builds_anthropic_client() -> None:
    save_model_config(
        ModelConfig(
            custom_models=[
                CustomModel(
                    name="anth",
                    base_url="https://api.anthropic.com",
                    api_format="anthropic",
                    models=["claude-x"],
                )
            ]
        )
    )
    model = build_model("anth:claude-x")
    # ChatAnthropic, not ChatOpenAI — the wire format is actually different.
    assert type(model).__name__ == "ChatAnthropic"


def test_default_format_stays_chat_completions() -> None:
    save_model_config(
        ModelConfig(
            custom_models=[
                CustomModel(name="d", base_url="http://h/v1", models=["m"])
            ]
        )
    )
    model = build_model("d:m")
    assert model.use_responses_api is False


def test_missing_anthropic_package_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment without langchain-anthropic gets a config error, not ImportError."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object):
        if name == "langchain_anthropic":
            raise ImportError("no module named langchain_anthropic")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    save_model_config(
        ModelConfig(
            custom_models=[
                CustomModel(
                    name="anth",
                    base_url="https://api.anthropic.com",
                    api_format="anthropic",
                    models=["claude-x"],
                )
            ]
        )
    )
    with pytest.raises(ConfigurationError, match="langchain-anthropic"):
        build_model("anth:claude-x")
