"""Settings precedence: real environment variables beat the .env file."""

import pytest

from agent_core.config.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_real_env_var_beats_dotenv(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(
        "AGENT_CORE_DATABASE_URL=sqlite:///./from-dotenv.db\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_CORE_DATABASE_URL", "sqlite:///./from-real-env.db")

    settings = get_settings()

    assert settings.database_url == "sqlite:///./from-real-env.db"
    # The real environment variable is never popped by the .env loader.
    import os

    assert os.environ["AGENT_CORE_DATABASE_URL"] == "sqlite:///./from-real-env.db"


def test_dotenv_agent_core_keys_do_not_leak(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text(
        "AGENT_CORE_DATABASE_URL=sqlite:///./from-dotenv.db\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_CORE_DATABASE_URL", raising=False)

    settings = get_settings()

    assert settings.database_url == "sqlite:///./from-dotenv.db"
    import os

    assert "AGENT_CORE_DATABASE_URL" not in os.environ
