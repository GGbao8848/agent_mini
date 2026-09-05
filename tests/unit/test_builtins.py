"""Tests for built-in tools and their registration."""

from pathlib import Path

from agent_core.config.settings import Settings
from agent_core.registries import ToolRegistry


def base_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        workspace_dir=str(tmp_path / "workspace"),
        agent_env_dir=str(tmp_path / "agent-env"),
    )


class TestRegistration:
    def test_reregistration_reattaches_handler(self, tmp_path: Path) -> None:
        from agent_core.builtins import register_builtin_tools

        settings = base_settings(tmp_path)
        registry = ToolRegistry()
        register_builtin_tools(registry, settings)
        # Simulate hydration from the persistence store: definition without a handler.
        registry._handlers.pop("run_code")  # noqa: SLF001

        register_builtin_tools(registry, settings)

        registry.handler_for("run_code")  # executable is back


class TestRunCode:
    def test_registered_via_register_builtin_tools(self, tmp_path: Path) -> None:
        from agent_core.builtins import register_builtin_tools

        settings = base_settings(tmp_path)
        registry = ToolRegistry()
        added = register_builtin_tools(registry, settings)

        assert "run_code" in added
        definition = registry.get("run_code")
        assert definition.risk_level.value == "medium"
        assert "workspace" in definition.description

    async def test_run_code_reports_exit_and_output(self, tmp_path: Path) -> None:
        from agent_core.builtins.code import make_run_code

        _, handler = make_run_code(base_settings(tmp_path))

        ok = await handler(command="echo hello-from-workspace")
        assert "exit_code=0" in ok and "hello-from-workspace" in ok

        failed = await handler(command="exit 3")
        assert "exit_code=3" in failed and "command failed" in failed

        # The venv python (not the system one) is what resolves first on PATH.
        venv_python = await handler(
            command="python -c 'import sys; print(sys.prefix != sys.base_prefix)'"
        )
        assert "exit_code=0" in venv_python and "True" in venv_python
