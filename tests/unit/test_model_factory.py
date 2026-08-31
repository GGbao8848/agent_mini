"""Unit tests for the model factory (no network access)."""

import os

import pytest
from langchain_openai import ChatOpenAI

from agent_core.config.settings import Settings
from agent_core.errors.exceptions import ConfigurationError
from agent_core.runtime.model import build_model, parse_model_spec


class TestParseModelSpec:
    def test_provider_and_model(self) -> None:
        assert parse_model_spec("openrouter:minimax/minimax-m3:free") == (
            "openrouter",
            "minimax/minimax-m3:free",
        )

    def test_bare_model_defaults_to_openai(self) -> None:
        assert parse_model_spec("gpt-4o-mini") == ("openai", "gpt-4o-mini")

    def test_model_containing_colons(self) -> None:
        assert parse_model_spec("openai:gpt-4o-mini:latest") == ("openai", "gpt-4o-mini:latest")

    @pytest.mark.parametrize("spec", [":missing-provider", "openai:"])
    def test_malformed_spec_raises(self, spec: str) -> None:
        with pytest.raises(ConfigurationError):
            parse_model_spec(spec)


class TestBuildModel:
    def test_openai_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        model = build_model("openai:gpt-4o-mini")

        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "gpt-4o-mini"

    def test_openrouter_model_uses_openai_compatible_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        model = build_model("openrouter:minimax/minimax-m3:free")

        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "minimax/minimax-m3:free"
        assert model.openai_api_base == "https://openrouter.ai/api/v1"

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        with pytest.raises(ConfigurationError) as excinfo:
            build_model("openai:gpt-4o-mini")
        assert excinfo.value.details["env_var"] == "OPENAI_API_KEY"

    def test_unsupported_provider_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        with pytest.raises(ConfigurationError) as excinfo:
            build_model("anthropic:claude-3")
        assert excinfo.value.details["provider"] == "anthropic"


class TestLocalProvider:
    def test_local_model_uses_configured_base_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://10.0.0.5:8000/v1")
        monkeypatch.setenv("LOCAL_LLM_API_KEY", "local-secret")

        model = build_model("local:qwen3.8-27b")

        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "qwen3.8-27b"
        assert model.openai_api_base == "http://10.0.0.5:8000/v1"

    def test_local_model_without_key_uses_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://10.0.0.5:8000/v1")
        monkeypatch.delenv("LOCAL_LLM_API_KEY", raising=False)

        model = build_model("local:qwen3.8-27b")

        assert isinstance(model, ChatOpenAI)  # builds fine: key is optional locally

    def test_local_model_without_base_url_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)

        with pytest.raises(ConfigurationError) as excinfo:
            build_model("local:qwen3.8-27b")
        assert excinfo.value.details["env_var"] == "LOCAL_LLM_BASE_URL"

    def test_local_model_does_not_inject_base_url_from_env_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Building with a hermetic Settings must not leak .env into os.environ.

        Regression guard: get_settings() (patched away here) injects non-
        AGENT_CORE_ .env keys into os.environ; build_model must not re-run that
        injection when given explicit settings.
        """
        monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)

        with pytest.raises(ConfigurationError):
            build_model("local:qwen3.8-27b", settings=Settings(_env_file=None))
        assert "LOCAL_LLM_BASE_URL" not in os.environ
