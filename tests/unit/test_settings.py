from agent_core.config.settings import Settings


def test_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.model == "openai:gpt-4o-mini"
    assert settings.log_level == "INFO"
    assert settings.environment.value == "development"


def test_env_prefix_parsing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("AGENT_CORE_MODEL", "anthropic:claude-sonnet-4")
    monkeypatch.setenv("AGENT_CORE_LOG_LEVEL", "DEBUG")
    settings = Settings(_env_file=None)
    assert settings.model == "anthropic:claude-sonnet-4"
    assert settings.log_level == "DEBUG"


def test_without_prefix_is_ignored(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MODEL", "should-be-ignored")
    settings = Settings(_env_file=None)
    assert settings.model == "openai:gpt-4o-mini"
