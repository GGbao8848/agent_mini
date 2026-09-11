"""Tests for the run_code sandbox backends (host legacy + podman)."""

from pathlib import Path
from typing import Any

import pytest

from agent_core.builtins.code import build_sandbox_command, make_run_code
from agent_core.config.settings import Settings
from agent_core.registries import ToolRegistry


def code_settings(tmp_path: Path, *, sandbox: str = "none") -> Settings:
    return Settings(
        _env_file=None,
        workspace_dir=str(tmp_path / "workspace"),
        sandbox=sandbox,  # type: ignore[arg-type]
        # Host backend creates the agent venv here, not in ~/.agent_core.
        agent_env_dir=str(tmp_path / "agent-env"),
    )


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
        # Host networking so the sandbox can reach LAN model/TTS services —
        # a default bridge cannot route back to the host's own LAN IP.
        assert argv[argv.index("--network") + 1] == "host"
        assert argv[-4] == settings.sandbox_image
        assert argv[-3] == "bash"
        assert argv[-2] == "-lc"
        assert argv[-1] == "echo hi"

    def test_skill_root_mounts_read_write_at_skills(self, tmp_path: Path) -> None:
        """run_code must see the same writable /skills view the file tools do.

        One mount of the whole skills directory keeps the two namespaces in
        lockstep: a skill script's documented path runs in the sandbox, and a
        skill written from the shell is visible to the file tools immediately.
        """
        settings = code_settings(tmp_path, sandbox="podman")
        workspace = tmp_path / "workspace"

        argv = build_sandbox_command(
            workspace,
            settings,
            "echo hi",
            timeout=60.0,
            skill_root="/opt/skills",
        )

        volumes = [argv[i + 1] for i, item in enumerate(argv) if item == "--volume"]
        assert "/opt/skills:/skills" in volumes

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


class TestEnvironmentNote:
    def test_host_note_teaches_the_virtual_root_and_hygiene_rules(self, tmp_path: Path) -> None:
        from agent_core.runtime.paths import environment_note

        settings = code_settings(tmp_path)
        root = tmp_path / "proj"
        note = environment_note(root, settings)

        # The file tools' root is the virtual /; the note must NOT name the
        # host path (the model copies it into file-tool calls → not found).
        assert "虚拟根 `/`" in note
        assert str(root) not in note
        assert "find /" in note  # full-disk scans are explicitly banned
        assert "ensure_packages" in note

    def test_podman_note_keeps_work_mapping(self, tmp_path: Path) -> None:
        from agent_core.runtime.paths import environment_note

        settings = code_settings(tmp_path, sandbox="podman")
        note = environment_note(tmp_path, settings)

        assert "/work" in note
        assert str(tmp_path) not in note

    def test_host_note_reads_skills_via_the_file_tool_path(self, tmp_path: Path) -> None:
        """Regression: the note must point read_file at /skills, not a host path.

        The old note named the on-disk skill path and told the agent to
        ``read_file`` it — which the file tools cannot reach, so every run burned
        its first calls failing to read a skill it had just been told about. The
        note now separates the two views: /skills for the file tools, the real
        path only for run_code.
        """
        from agent_core.runtime.paths import environment_note

        settings = code_settings(tmp_path)
        skills_dir = tmp_path / "workspace" / "skills"
        note = environment_note(tmp_path, settings, skills_dir)

        assert "/skills/<技能名>/SKILL.md" in note  # file-tool path is named
        assert str(skills_dir) in note  # the real path is given for run_code

    def test_podman_note_uses_the_container_mount(self, tmp_path: Path) -> None:
        from agent_core.runtime.paths import environment_note

        settings = code_settings(tmp_path, sandbox="podman")
        skills_dir = tmp_path / "workspace" / "skills"
        note = environment_note(tmp_path, settings, skills_dir)

        assert "/skills/<技能名>/SKILL.md" in note
        assert "/skills/<技能名>/scripts/xxx.py" in note

    def test_note_omits_skills_when_no_root(self, tmp_path: Path) -> None:
        from agent_core.runtime.paths import environment_note

        note = environment_note(tmp_path, code_settings(tmp_path))
        assert "/skills" not in note
