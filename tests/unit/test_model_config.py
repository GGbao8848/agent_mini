"""Console-editable model configuration: overrides, persistence and API."""

import pytest

from agent_core.config.model_config import (
    ModelConfig,
    get_model_config,
    load_model_config,
    mask_secret,
    save_model_config,
)
from agent_core.config.settings import Settings
from agent_core.persistence.store import SqliteStore
from agent_core.runtime.model import OPENROUTER_BASE_URL, build_model


@pytest.fixture(autouse=True)
def _reset_overrides():
    """Isolate the process-global override state between tests."""
    load_model_config(None)
    yield
    load_model_config(None)


class TestBuildModelOverrides:
    async def test_page_key_used_without_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        save_model_config(ModelConfig(api_keys={"openai": "sk-page-key-9999"}))

        model = build_model("openai:gpt-4o-mini")

        assert model.openai_api_key.get_secret_value() == "sk-page-key-9999"

    def test_page_model_spec_beats_settings(self) -> None:
        save_model_config(ModelConfig(model="openrouter:page-model"))

        model = build_model(None, settings=Settings(_env_file=None))

        assert model.model_name == "page-model"
        assert model.openai_api_base == OPENROUTER_BASE_URL

    async def test_env_key_still_works_without_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key")
        model = build_model("openai:gpt-4o-mini")
        assert model.openai_api_key.get_secret_value() == "sk-env-key"

    async def test_local_endpoint_from_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LOCAL_LLM_BASE_URL", raising=False)
        save_model_config(
            ModelConfig(local_base_url="http://10.0.0.9:8000/v1")
        )

        model = build_model("local:qwen-test")

        assert model.openai_api_base == "http://10.0.0.9:8000/v1"


class TestPersistence:
    def test_roundtrip_through_store(self, tmp_path) -> None:
        # Boot binds the store first, then the page saves (real ordering).
        load_model_config(SqliteStore(f"sqlite:///{tmp_path / 'cfg.db'}"))
        save_model_config(
            ModelConfig(model="openai:persisted", api_keys={"openai": "sk-keep"})
        )
        # Bind a fresh store (as a new process would) and reload.
        load_model_config(SqliteStore(f"sqlite:///{tmp_path / 'cfg.db'}"))

        config = get_model_config()

        assert config.model == "openai:persisted"
        assert config.api_keys["openai"] == "sk-keep"

    def test_mask_secret(self) -> None:
        assert mask_secret("sk-abcdef1234") == "••••1234"
        assert mask_secret("abcd") == "••••"


class TestApi:
    async def test_put_then_get_masks_key_and_persists(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.unit.test_console import make_client, make_service

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        service = make_service(tmp_path, monkeypatch)
        # Bind a store so the PUT exercises the write-through path too.
        load_model_config(SqliteStore(f"sqlite:///{tmp_path / 'api.db'}"))

        async with make_client(service) as client:
            put = await client.put(
                "/v1/model-config",
                json={"model": "openai:from-page", "api_keys": {"openai": "sk-secret-4321"}},
            )
            assert put.status_code == 200
            body = put.json()
            assert body["model"] == "openai:from-page"
            assert body["effective_model"] == "openai:from-page"
            openai = next(k for k in body["api_keys"] if k["provider"] == "openai")
            assert openai["set"] is True and openai["source"] == "page"
            assert openai["hint"] == "••••4321"
            assert "sk-secret-4321" not in put.text

            got = (await client.get("/v1/model-config")).json()
            assert got["model_source"] == "page"

        # New "process": reload from the store — the page config survives.
        load_model_config(SqliteStore(f"sqlite:///{tmp_path / 'api.db'}"))
        assert get_model_config().model == "openai:from-page"

    async def test_empty_string_clears_override(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.unit.test_console import make_client, make_service

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        save_model_config(ModelConfig(model="openai:old", api_keys={"openai": "sk-old"}))
        service = make_service(tmp_path, monkeypatch)

        async with make_client(service) as client:
            put = await client.put(
                "/v1/model-config", json={"model": "", "api_keys": {"openai": ""}}
            )
            assert put.status_code == 200
            assert put.json()["model"] is None
            assert put.json()["model_source"] == "env"
            openai = next(k for k in put.json()["api_keys"] if k["provider"] == "openai")
            assert openai["set"] is False

    async def test_unknown_provider_ignored(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.unit.test_console import make_client, make_service

        service = make_service(tmp_path, monkeypatch)
        async with make_client(service) as client:
            put = await client.put(
                "/v1/model-config", json={"api_keys": {"not-a-provider": "sk-x"}}
            )
            assert put.status_code == 200
            assert get_model_config().api_keys == {}

    async def test_verify_reports_failure_without_raising(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.unit.test_console import make_client, make_service

        service = make_service(tmp_path, monkeypatch)
        async with make_client(service) as client:
            response = await client.post(
                "/v1/model-config/verify", json={"model": "nosuch:x"}
            )
            assert response.status_code == 200
            body = response.json()
            assert body["ok"] is False
            assert body["error"]


class TestProviderAndModelApi:
    """The provider + per-model catalog endpoints (R27)."""

    async def test_upsert_provider_with_catalog(self, tmp_path, monkeypatch) -> None:
        from tests.unit.test_console import make_client, make_service

        service = make_service(tmp_path, monkeypatch)
        async with make_client(service) as client:
            response = await client.put(
                "/v1/model-config/custom/mine",
                json={
                    "base_url": "http://10.0.0.9:8000/v1",
                    "api_format": "openai",
                    "api_key": "sk-secret-8888",
                    "catalog": [
                        {"id": "m1", "context_window": 32768, "enabled": True},
                        {"id": "m2", "enabled": False},
                    ],
                },
            )
            assert response.status_code == 200
            body = response.json()
            card = next(c for c in body["custom_models"] if c["name"] == "mine")
            assert [e["id"] for e in card["catalog"]] == ["m1", "m2"]
            assert card["key_hint"] == "••••8888"
            assert "sk-secret-8888" not in response.text
            # Only the enabled model is offered to the picker.
            assert [m["spec"] for m in body["available_models"] if m["provider"] == "mine"] == [
                "mine:m1"
            ]
            assert body["available_models"][0]["context_window"] == 32768

    async def test_disable_provider_removes_its_models_from_picker(
        self, tmp_path, monkeypatch
    ) -> None:
        from tests.unit.test_console import make_client, make_service

        service = make_service(tmp_path, monkeypatch)
        async with make_client(service) as client:
            await client.put(
                "/v1/model-config/custom/mine",
                json={"base_url": "http://h/v1", "models": ["m1"]},
            )
            patched = await client.patch(
                "/v1/model-config/custom/mine", json={"enabled": False}
            )
            assert patched.status_code == 200
            card = next(c for c in patched.json()["custom_models"] if c["name"] == "mine")
            assert card["enabled"] is False
            assert all(m["provider"] != "mine" for m in patched.json()["available_models"])

    async def test_patch_adds_and_removes_models(self, tmp_path, monkeypatch) -> None:
        from tests.unit.test_console import make_client, make_service

        service = make_service(tmp_path, monkeypatch)
        async with make_client(service) as client:
            await client.put(
                "/v1/model-config/custom/p",
                json={"base_url": "http://h/v1", "models": []},
            )
            added = await client.put(
                "/v1/model-config/custom/p/models/alpha", json={"context_window": 4096}
            )
            assert added.status_code == 200
            card = next(c for c in added.json()["custom_models"] if c["name"] == "p")
            assert [e["id"] for e in card["catalog"]] == ["alpha"]

            removed = await client.delete("/v1/model-config/custom/p/models/alpha")
            assert removed.status_code == 200
            card = next(c for c in removed.json()["custom_models"] if c["name"] == "p")
            assert card["catalog"] == []

    async def test_builtin_provider_cannot_be_renamed(self, tmp_path, monkeypatch) -> None:
        from tests.unit.test_console import make_client, make_service

        service = make_service(tmp_path, monkeypatch)
        async with make_client(service) as client:
            response = await client.patch(
                "/v1/model-config/custom/openai", json={"name": "renamed"}
            )
            assert response.status_code == 422

    async def test_unsupported_api_format_rejected(self, tmp_path, monkeypatch) -> None:
        from tests.unit.test_console import make_client, make_service

        service = make_service(tmp_path, monkeypatch)
        async with make_client(service) as client:
            response = await client.put(
                "/v1/model-config/custom/x",
                json={"base_url": "http://h/v1", "api_format": "gemini", "models": []},
            )
            assert response.status_code == 422

    async def test_anthropic_format_accepted(self, tmp_path, monkeypatch) -> None:
        from tests.unit.test_console import make_client, make_service

        service = make_service(tmp_path, monkeypatch)
        async with make_client(service) as client:
            response = await client.put(
                "/v1/model-config/custom/anth",
                json={
                    "base_url": "https://api.anthropic.com",
                    "api_format": "anthropic",
                    "catalog": [{"id": "claude-x"}],
                },
            )
            assert response.status_code == 200
            card = next(c for c in response.json()["custom_models"] if c["name"] == "anth")
            assert card["api_format"] == "anthropic"

    async def test_reveal_key_returns_plaintext_on_demand(
        self, tmp_path, monkeypatch
    ) -> None:
        """The key is not in the list payload but IS available explicitly."""
        from tests.unit.test_console import make_client, make_service

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        service = make_service(tmp_path, monkeypatch)
        async with make_client(service) as client:
            await client.put(
                "/v1/model-config/custom/rev",
                json={"base_url": "http://h/v1", "api_key": "sk-reveal-7777", "models": ["m"]},
            )
            listing = await client.get("/v1/model-config")
            # The list payload must not carry the plaintext.
            assert "sk-reveal-7777" not in listing.text

            revealed = await client.get("/v1/model-config/custom/rev/key")
            assert revealed.status_code == 200
            assert revealed.json()["api_key"] == "sk-reveal-7777"
            assert revealed.json()["source"] == "page"

    async def test_reveal_key_unknown_provider_404(self, tmp_path, monkeypatch) -> None:
        from tests.unit.test_console import make_client, make_service

        service = make_service(tmp_path, monkeypatch)
        async with make_client(service) as client:
            response = await client.get("/v1/model-config/custom/nope/key")
            assert response.status_code == 404
