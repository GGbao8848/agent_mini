"""Console (Phase 22) tests: artifact manifest, download safety, token auth."""

import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage

from agent_core.api.app import create_app
from agent_core.application.service import AgentCoreService
from agent_core.artifacts import artifact_abs_path, scan_workspace_artifacts
from agent_core.config.settings import get_settings
from agent_core.domain.agent import AgentSpec
from agent_core.mcp.manager import MCPManager
from agent_core.observability.stream import EventStreamBroker
from agent_core.observability.trace import InMemoryTracer
from agent_core.registries import AgentRegistry, MCPRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.runtime import AgentRuntime


class _StubBuilder:
    class _Graph:
        async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
            # The "agent" produces a file inside the workspace during the run.
            out = Path("workspace/out/hello.md")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("# hi")
            return {"messages": [AIMessage(content="done")]}

    def build(self, spec: Any) -> Any:
        return self._Graph()


def make_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentCoreService:
    """Real service with a stub graph; workspace rooted inside tmp_path."""
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    agents = AgentRegistry()
    agents.register(AgentSpec(id="helper", name="Helper"))
    tracer = InMemoryTracer()
    runtime = AgentRuntime(agents, ToolRegistry(), SkillRegistry(), tracer=tracer,
                           builder=_StubBuilder())
    mcp_registry = MCPRegistry()
    mcp = MCPManager(mcp_registry, ToolRegistry(), credentials=None)
    broker = EventStreamBroker(runtime.bus)
    return AgentCoreService(runtime=runtime, mcp=mcp, mcp_registry=mcp_registry, broker=broker)


def make_client(service: AgentCoreService) -> httpx.AsyncClient:
    app = create_app(service)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


class TestArtifactManifest:
    async def test_run_records_artifacts_in_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        run = service.runtime.create_run("helper", "produce a file")

        await service.runtime.execute_run(run)

        artifacts = run.metadata["artifacts"]
        assert any(a["path"] == "out/hello.md" for a in artifacts)

    async def test_files_from_before_the_run_are_excluded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        workspace = tmp_path / "workspace"
        (workspace / "out").mkdir(parents=True)
        old = workspace / "out" / "before.txt"
        old.write_text("old")
        os.utime(old, (time.time() - 100, time.time() - 100))  # genuinely old
        run = service.runtime.create_run("helper", "produce a file")

        await service.runtime.execute_run(run)

        assert all("before.txt" not in a["path"] for a in run.metadata["artifacts"])

    def test_scan_skips_dotfiles_and_missing_dirs(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        (workspace / ".hidden").mkdir(parents=True)
        (workspace / ".hidden" / "secret.txt").write_text("x")
        assert scan_workspace_artifacts(workspace, since_ts=0) == []
        assert scan_workspace_artifacts(tmp_path / "nope", since_ts=0) == []


class TestDownloadSafety:
    def test_traversal_is_rejected(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "keep.txt").write_text("ok")
        secret = tmp_path / ".env"
        secret.write_text("SECRETS")

        assert artifact_abs_path(workspace, "../.env") is None
        assert artifact_abs_path(workspace, str(secret)) is None
        assert artifact_abs_path(workspace, "") is None
        assert artifact_abs_path(workspace, "/etc/passwd") is None
        assert artifact_abs_path(workspace, "missing.txt") is None

    def test_hidden_files_are_never_served(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True)
        (workspace / ".env").write_text("SECRETS")
        assert artifact_abs_path(workspace, ".env") is None


class TestArtifactApi:
    async def test_list_download_and_traversal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = make_service(tmp_path, monkeypatch)
        client = make_client(service)
        run = service.runtime.create_run("helper", "produce a file")

        await service.runtime.execute_run(run)

        listing = await client.get(f"/v1/artifacts/{run.id}")
        assert listing.status_code == 200
        assert listing.json()[0]["path"] == "out/hello.md"

        downloaded = await client.get(
            f"/v1/artifacts/{run.id}/download", params={"path": "out/hello.md"}
        )
        assert downloaded.status_code == 200
        assert downloaded.text == "# hi"

        escape = await client.get(
            f"/v1/artifacts/{run.id}/download", params={"path": "../agent.db"}
        )
        assert escape.status_code == 404
        await client.aclose()


class TestConsoleAuth:
    async def test_token_required_when_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_CORE_CONSOLE_TOKEN", "s3cret")
        get_settings.cache_clear()
        client = make_client(make_service(tmp_path, monkeypatch))

        assert (await client.get("/v1/runs")).status_code == 401
        # The page itself stays open (it holds no secrets and must be able to
        # collect the token in the browser).
        assert (await client.get("/console/", follow_redirects=False)).status_code == 200
        ok = await client.get("/v1/runs", headers={"X-Console-Token": "s3cret"})
        assert ok.status_code == 200
        assert (await client.get("/v1/runs?token=s3cret")).status_code == 200
        assert (await client.get("/healthz")).status_code == 200  # healthz stays open

        get_settings.cache_clear()
        await client.aclose()

    async def test_open_when_no_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENT_CORE_CONSOLE_TOKEN", raising=False)
        get_settings.cache_clear()
        client = make_client(make_service(tmp_path, monkeypatch))

        assert (await client.get("/v1/runs")).status_code == 200
        console = await client.get("/console/", follow_redirects=False)
        assert console.status_code == 200
        assert b"Agent Console" in console.content

        get_settings.cache_clear()
        await client.aclose()
