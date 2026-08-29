"""Tests for the run_code sandbox backends (host legacy + podman)."""

from pathlib import Path
from typing import Any

import pytest

from agent_core.builtins.code import build_sandbox_command, make_run_code
from agent_core.config.settings import Settings
from agent_core.registries import ToolRegistry


def code_settings(tmp_path: Path, *, sandbox: str = "none") -> Settings:
    return Settings(_env_file=None, workspace_dir=str(tmp_path / "workspace"), sandbox=sandbox)  # type: ignore[arg-type]


class TestHostBackend:
    async def test_reports_exit_and_output(self, tmp_path: Path) -> None:
        _, handler = make_run_code(code_settings(tmp_path))

        ok = await handler(command="echo hello-from-workspace")
        assert "exit_code=0" in ok and "hello-from-workspace" in ok

        failed = await handler(command="exit 3")
        assert "exit_code=3" in failed and "command failed" in failed

    async def test_cwd_is_workspace(self, tmp_path: Path) -> None:
        _, handler = make_run_code(code_settings(tmp_path))

        result = await handler(command="pwd")
        assert str(tmp_path / "workspace") in result

    async def test_timeout_is_capped_and_enforced(self, tmp_path: Path) -> None:
        from agent_core.errors.exceptions import ToolError

        _, handler = make_run_code(code_settings(tmp_path))

        with pytest.raises(ToolError) as excinfo:
            await handler(command="sleep 30", timeout_seconds=2)
        assert "timed out after 2" in excinfo.value.message


class TestSandboxArgv:
    def test_podman_argv_shape(self, tmp_path: Path) -> None:
        settings = code_settings(tmp_path, sandbox="podman")
        workspace = tmp_path / "workspace"

        argv = build_sandbox_command(workspace, settings, "echo hi", timeout=60.0)

        assert argv[:2] == ["podman", "run"]
        assert "--rm" in argv
        volumes = [argv[i + 1] for i, item in enumerate(argv) if item == "--volume"]
        assert f"{workspace}:/work" in volumes
        assert "agent-core-pip-cache:/root/.cache/pip" in volumes
        assert argv[argv.index("--workdir") + 1] == "/work"
        assert argv[argv.index("--memory") + 1] == "2048m"
        assert argv[argv.index("--cpus") + 1] == "2.0"
        assert argv[argv.index("--pids-limit") + 1] == "256"
        assert argv[argv.index("--pull") + 1] == "never"
        assert argv[-4] == settings.sandbox_image
        assert argv[-3] == "bash"
        assert argv[-2] == "-lc"
        assert argv[-1] == "echo hi"

    def test_proxy_env_passthrough(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HTTPS_PROXY", "http://10.10.10.214:7890")
        monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,10.10.10.146")
        monkeypatch.delenv("HTTP_PROXY", raising=False)
        settings = code_settings(tmp_path, sandbox="podman")

        argv = build_sandbox_command(tmp_path, settings, "true", timeout=60.0)

        envs = [argv[i + 1] for i, item in enumerate(argv) if item == "--env"]
        assert "HTTPS_PROXY=http://10.10.10.214:7890" in envs
        assert any(e.startswith("NO_PROXY=localhost") for e in envs)

    def test_custom_limits_flow_into_argv(self, tmp_path: Path) -> None:
        settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path / "w"),
            sandbox="podman",
            sandbox_image="localhost/custom:dev",
            sandbox_memory_mb=512,
            sandbox_cpus=1.5,
            sandbox_pids_limit=64,
        )

        argv = build_sandbox_command(tmp_path / "w", settings, "true", timeout=60.0)

        assert argv[argv.index("--memory") + 1] == "512m"
        assert argv[argv.index("--cpus") + 1] == "1.5"
        assert argv[argv.index("--pids-limit") + 1] == "64"
        assert argv[-4] == "localhost/custom:dev"


class TestMetadata:
    def test_definition_carries_sandbox_mode(self, tmp_path: Path) -> None:
        settings = code_settings(tmp_path, sandbox="podman")
        definition, _ = make_run_code(settings)

        assert definition.metadata["sandbox"] == "podman"
        assert definition.metadata["timeout_seconds"] == 920.0

    def test_registration_unchanged(self, tmp_path: Path) -> None:
        from agent_core.builtins import register_builtin_tools

        registry = ToolRegistry()
        added: Any = register_builtin_tools(registry, code_settings(tmp_path, sandbox="podman"))
        assert "run_code" in added
