"""Host sandbox backend: agent env, ensure_packages, system-install approval."""

from pathlib import Path

import pytest

from agent_core.builtins import hostenv
from agent_core.builtins.code import is_system_install, make_run_code
from agent_core.builtins.packages import make_ensure_packages
from agent_core.config.settings import Settings
from agent_core.permissions import arg_risk


def host_settings(tmp_path: Path, *, sandbox: str = "host") -> Settings:
    return Settings(
        _env_file=None,
        workspace_dir=str(tmp_path / "workspace"),
        sandbox=sandbox,  # type: ignore[arg-type]
        agent_env_dir=str(tmp_path / "agent-env"),
    )


@pytest.fixture(autouse=True)
def _clean_arg_rules():
    arg_risk.clear_argument_risk_rules()
    yield
    arg_risk.clear_argument_risk_rules()


class TestAgentEnv:
    async def test_venv_created_once_and_reused(self, tmp_path: Path) -> None:
        settings = host_settings(tmp_path)
        env_dir = await hostenv.ensure_host_env(settings)
        assert (env_dir / "pyvenv.cfg").exists()
        # Second call (and a sync one) reuses it without recreating.
        assert await hostenv.ensure_host_env(settings) == env_dir
        assert hostenv.ensure_agent_env(settings) == env_dir

    async def test_none_alias_behaves_as_host(self, tmp_path: Path) -> None:
        settings = host_settings(tmp_path, sandbox="none")
        assert settings.sandbox == "none"
        # not podman → host backend: agent env is used, ensure_packages registered.
        env_dir = await hostenv.ensure_host_env(settings)
        assert (env_dir / "pyvenv.cfg").exists()

    def test_system_site_packages_visible(self, tmp_path: Path) -> None:
        settings = host_settings(tmp_path)
        env_dir = hostenv.ensure_agent_env(settings)
        # Stdlib modules resolve through the base interpreter without
        # installing anything (the venv deliberately does NOT inherit the
        # project venv's packages — only the host python's own).
        assert hostenv.check_packages(env_dir, ["json"])["json"] is True
        assert hostenv.check_packages(env_dir, ["no-such-dist-anywhere-xyz"]) == {
            "no-such-dist-anywhere-xyz": False
        }


class TestEnsurePackages:
    async def test_already_available_never_installs(self, tmp_path: Path) -> None:
        _, handler = make_ensure_packages(host_settings(tmp_path))

        result = await handler(packages=["json"])

        assert "already available" in result
        assert "newly installed" not in result

    async def test_missing_packages_installed(self, tmp_path: Path, monkeypatch) -> None:
        installed: list[list[str]] = []

        def fake_install(env_dir: Path, packages: list[str], timeout: float = 600.0) -> str:
            installed.append(packages)
            return "Successfully installed fake-lib"

        import agent_core.builtins.packages as packages_module

        monkeypatch.setattr(packages_module, "install_packages", fake_install)
        monkeypatch.setattr(
            packages_module,
            "check_packages",
            lambda env_dir, packages: {name: False for name in packages},
        )
        _, handler = make_ensure_packages(host_settings(tmp_path))

        result = await handler(packages=["fake-lib"])

        assert installed == [["fake-lib"]]
        assert "newly installed into the agent env" in result

    async def test_empty_packages_rejected(self, tmp_path: Path) -> None:
        from agent_core.errors.exceptions import ToolInvalidArgumentsError

        _, handler = make_ensure_packages(host_settings(tmp_path))
        with pytest.raises(ToolInvalidArgumentsError):
            await handler(packages=[])


class TestHostBackendPath:
    async def test_run_code_python_is_agent_env(self, tmp_path: Path) -> None:
        settings = host_settings(tmp_path)
        _, handler = make_run_code(settings)

        result = await handler(command="python -c 'import sys; print(sys.prefix)'")

        assert str(settings.agent_env_dir) in result


class TestSystemInstallRule:
    @pytest.mark.parametrize(
        "command,expected",
        [
            ("apt-get install -y ffmpeg", True),
            ("sudo apt install python3-tk", True),
            ("brew install ffmpeg", True),
            ("dnf install -y jq", True),
            ("apk add curl", True),
            ("pacman -S ffmpeg", True),
            ("choco install ffmpeg -y", True),
            ("pip install requests", False),
            ("uv pip install python-pptx", False),
            ("apt list --installed", False),
            # Heuristic, not a parser: "echo apt-get install" reads like an
            # install to the pattern — it lands in the approval queue, which
            # is the safe side for a guardrail.
            ("echo apt-get install", True),
            ("python -m pip install pandas", False),
        ],
    )
    def test_pattern(self, command: str, expected: bool) -> None:
        assert is_system_install(command) is expected

    async def test_gate_escalates_system_install_to_approval(self, tmp_path: Path) -> None:
        import asyncio

        from agent_core.domain.action import ApprovalStatus, RiskLevel
        from agent_core.domain.agent import AgentSpec
        from agent_core.domain.task import Run, RunStatus
        from agent_core.domain.tool import ToolDefinition
        from agent_core.observability.emitter import EventFanout
        from agent_core.observability.events import EventBus
        from agent_core.observability.trace import InMemoryTracer
        from agent_core.permissions import ActionGate, ActionPolicy
        from agent_core.permissions.approval import ApprovalManager
        from agent_core.registries import AgentRegistry, ToolRegistry
        from agent_core.runtime.tool_executor import ToolExecutor

        arg_risk.register_argument_risk_rule(
            "run_code", lambda args: is_system_install(str(args.get("command", "")))
        )
        definition = ToolDefinition(
            name="run_code",
            description="run a command",
            risk_level=RiskLevel.MEDIUM,
            input_schema={
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        )
        agents = AgentRegistry()
        agents.register(AgentSpec(id="helper", name="Helper"))
        tools = ToolRegistry()
        tools.register(definition, lambda command: f"ran: {command}")
        tracer = InMemoryTracer()
        approvals = ApprovalManager()
        gate = ActionGate(
            agents, tools, ActionPolicy(), approvals,
            ToolExecutor(), EventFanout(tracer, EventBus()),
        )
        run = Run(task_id="t1", agent_id="helper")
        run.transition_to(RunStatus.RUNNING)

        task = asyncio.create_task(
            gate.execute(
                run=run, tool_name="run_code",
                arguments={"command": "apt-get install -y ffmpeg"},
            )
        )
        await asyncio.sleep(0.05)
        # MEDIUM is below the approval floor, but the argument rule escalated it.
        pending = approvals.list_pending()
        assert len(pending) == 1
        assert run.status is RunStatus.WAITING_APPROVAL
        approvals.resolve(pending[0].id, ApprovalStatus.APPROVED)
        assert await task == "ran: apt-get install -y ffmpeg"

        # A normal command sails through with no approval round-trip.
        run2 = Run(task_id="t2", agent_id="helper")
        run2.transition_to(RunStatus.RUNNING)
        assert (
            await gate.execute(
                run=run2, tool_name="run_code", arguments={"command": "echo hi"}
            )
            == "ran: echo hi"
        )
        assert approvals.list_pending() == []
