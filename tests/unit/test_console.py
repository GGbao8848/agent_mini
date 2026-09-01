"""Console (Phase 22) tests: artifact manifest, download safety, token auth."""

import os
import time
from collections.abc import AsyncIterator
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


def make_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mcp_opener: Any = None
) -> AgentCoreService:
    """Real service with a stub graph; workspace rooted inside tmp_path."""
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    agents = AgentRegistry()
    agents.register(AgentSpec(id="helper", name="Helper"))
    tracer = InMemoryTracer()
    runtime = AgentRuntime(agents, ToolRegistry(), SkillRegistry(), tracer=tracer,
                           builder=_StubBuilder())
    mcp_registry = MCPRegistry()
    mcp = MCPManager(mcp_registry, ToolRegistry(), credentials=None, opener=mcp_opener)
    broker = EventStreamBroker(runtime.bus)
    return AgentCoreService(runtime=runtime, mcp=mcp, mcp_registry=mcp_registry, broker=broker)


def toolbox_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> httpx.AsyncClient:
    """Console client whose MCP connects succeed against a fake session."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def opener(definition: Any, credential: str | None) -> AsyncIterator[Any]:
        from agent_core.domain.tool import ToolDefinition

        class FakeSession:
            async def list_tools(self) -> list[ToolDefinition]:
                return [
                    ToolDefinition(
                        name="demo_echo",
                        description="Echo",
                        input_schema={"type": "object"},
                        source="mcp",
                        metadata={"mcp_server": "demo", "mcp_tool": "echo"},
                    )
                ]

        yield FakeSession()

    service = make_service(tmp_path, monkeypatch, mcp_opener=opener)
    return make_client(service)


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
        hello = next(a for a in artifacts if a["path"] == "out/hello.md")
        assert hello["size"] > 0
        assert "mtime" in hello  # timestamp so the console can show when it appeared

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

    async def test_unicode_filename_downloads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Chinese artifact names must not break the response headers (regression:
        a hand-built Content-Disposition raised UnicodeEncodeError → 500)."""
        service = make_service(tmp_path, monkeypatch)
        client = make_client(service)
        workspace = tmp_path / "workspace"
        (workspace / "ppt").mkdir(parents=True)
        (workspace / "ppt" / "智能体科普扫盲.pptx").write_bytes(b"PK\x03\x04fake")
        run = service.runtime.create_run("helper", "make a deck")

        response = await client.get(
            f"/v1/artifacts/{run.id}/download", params={"path": "ppt/智能体科普扫盲.pptx"}
        )

        assert response.status_code == 200
        assert response.content.startswith(b"PK")
        disposition = response.headers["content-disposition"]
        assert "filename*=utf-8''" in disposition  # RFC 5987 encoded
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument"
        )
        await client.aclose()


class TestConsoleAuth:
    async def test_token_required_when_configured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGENT_CORE_CONSOLE_TOKEN", "s3cret")
        get_settings.cache_clear()
        client = make_client(make_service(tmp_path, monkeypatch))

        assert (await client.get("/v1/tasks")).status_code == 401
        # The page itself stays open (it holds no secrets and must be able to
        # collect the token in the browser).
        assert (await client.get("/console/", follow_redirects=False)).status_code == 200
        ok = await client.get("/v1/tasks", headers={"X-Console-Token": "s3cret"})
        assert ok.status_code == 200
        assert (await client.get("/v1/tasks?token=s3cret")).status_code == 200
        assert (await client.get("/healthz")).status_code == 200  # healthz stays open

        get_settings.cache_clear()
        await client.aclose()

    async def test_open_when_no_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("AGENT_CORE_CONSOLE_TOKEN", raising=False)
        get_settings.cache_clear()
        client = make_client(make_service(tmp_path, monkeypatch))

        assert (await client.get("/v1/tasks")).status_code == 200
        console = await client.get("/console/", follow_redirects=False)
        assert console.status_code == 200
        assert b"Agent Console" in console.content

        get_settings.cache_clear()
        await client.aclose()


class TestSkillInstallApi:
    async def test_install_list_delete_skill(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill_dir = tmp_path / "skills" / "greet"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Greet")
        client = toolbox_client(tmp_path, monkeypatch)

        created = await client.post("/v1/skills", json={
            "id": "greet", "name": "Greet", "description": "say hi",
            "path": str(skill_dir),
        })
        assert created.status_code == 201
        assert created.json()["path"].endswith("greet")

        listed = await client.get("/v1/skills")
        assert [s["id"] for s in listed.json()] == ["greet"]

        removed = await client.delete("/v1/skills/greet")
        assert removed.status_code == 200
        assert [s["id"] for s in (await client.get("/v1/skills")).json()] == []
        await client.aclose()

    async def test_duplicate_skill_maps_to_409(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill_dir = tmp_path / "skills" / "greet"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Greet")
        client = toolbox_client(tmp_path, monkeypatch)
        payload = {"id": "greet", "name": "Greet", "path": str(skill_dir)}

        assert (await client.post("/v1/skills", json=payload)).status_code == 201
        assert (await client.post("/v1/skills", json=payload)).status_code == 409
        await client.aclose()

    async def test_missing_directory_or_skillmd_maps_to_400(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = toolbox_client(tmp_path, monkeypatch)

        missing = await client.post("/v1/skills", json={
            "id": "x", "name": "X", "path": str(tmp_path / "nope"),
        })
        assert missing.status_code == 400
        assert "does not exist" in missing.json()["error"]["message"]

        empty = tmp_path / "skills" / "empty"
        empty.mkdir(parents=True)
        no_manifest = await client.post("/v1/skills", json={
            "id": "x", "name": "X", "path": str(empty),
        })
        assert no_manifest.status_code == 400
        assert "SKILL.md" in no_manifest.json()["error"]["message"]
        await client.aclose()


class TestMcpRemoveApi:
    async def test_remove_disconnected_server(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = toolbox_client(tmp_path, monkeypatch)
        created = await client.post("/v1/mcp/servers", json={
            "id": "demo", "name": "Demo", "transport": "streamable_http",
            "endpoint": "http://127.0.0.1:8931/mcp",
        })
        assert created.status_code == 201

        removed = await client.delete("/v1/mcp/servers/demo")
        assert removed.status_code == 200
        assert (await client.get("/v1/mcp/servers/demo")).status_code == 404
        await client.aclose()

    async def test_remove_connected_server_disconnects_then_removes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = toolbox_client(tmp_path, monkeypatch)
        await client.post("/v1/mcp/servers", json={
            "id": "demo", "name": "Demo", "transport": "streamable_http",
            "endpoint": "http://127.0.0.1:8931/mcp",
        })
        await client.post("/v1/mcp/servers/demo/connect")
        healthy = (await client.get("/v1/mcp/servers/demo")).json()
        assert healthy["status"] == "healthy"

        removed = await client.delete("/v1/mcp/servers/demo")
        assert removed.status_code == 200
        assert (await client.get("/v1/mcp/servers/demo")).status_code == 404
        await client.aclose()


class TestMcpMetadataAndStd:
    async def test_create_with_metadata_persists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = toolbox_client(tmp_path, monkeypatch)
        created = await client.post("/v1/mcp/servers", json={
            "id": "mem0", "name": "mem0", "transport": "streamable_http",
            "endpoint": "https://mcp.mem0.ai/mcp/",
            "metadata": {"headers": {"Authorization": "Token abc"}},
        })
        assert created.status_code == 201
        assert created.json()["metadata"]["headers"]["Authorization"] == "Token abc"
        await client.aclose()

    def test_http_headers_prefer_imported_and_fill_credential(self) -> None:
        from agent_core.domain.mcp import MCPServerDefinition, MCPTransport
        from agent_core.mcp.client import _http_headers

        definition = MCPServerDefinition(
            id="mem0", name="mem0", transport=MCPTransport.STREAMABLE_HTTP,
            endpoint="https://x/mcp/",
            metadata={"headers": {"Authorization": "Token abc"}},
        )
        headers = _http_headers(definition, credential=None)
        assert headers["Authorization"] == "Token abc"

        # No imported header → the auth_ref credential fills in.
        plain = MCPServerDefinition(
            id="x", name="X", transport=MCPTransport.STREAMABLE_HTTP, endpoint="https://x"
        )
        assert _http_headers(plain, "sk-1")["Authorization"] == "Bearer sk-1"

    def test_stdio_env_merges_host_auth_and_imported(self) -> None:
        from agent_core.domain.mcp import MCPServerDefinition, MCPTransport
        from agent_core.mcp.client import _stdio_env

        definition = MCPServerDefinition(
            id="fs", name="FS", transport=MCPTransport.STDIO, endpoint="mcp-server fs",
            metadata={"env": {"CUSTOM_VAR": "1"}},
        )
        env = _stdio_env(definition, credential=None)
        assert env["CUSTOM_VAR"] == "1"
        assert env["PATH"]  # host environment preserved


class TestAgentBinding:
    async def test_update_tools_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = toolbox_client(tmp_path, monkeypatch)

        updated = await client.put("/v1/agents/helper", json={
            "tools": ["demo_echo", "run_code"],
        })
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["tools"] == ["demo_echo", "run_code"]

        # Omitted fields keep their values.
        tools_only = await client.put("/v1/agents/helper", json={"tools": ["run_code"]})
        assert tools_only.json()["tools"] == ["run_code"]
        await client.aclose()

    async def test_skills_field_is_ignored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Skills are a shared pool loaded for every agent — a client sending
        # the legacy skills field must not error and must not change anything.
        client = toolbox_client(tmp_path, monkeypatch)
        resp = await client.put("/v1/agents/helper", json={"skills": ["greet"]})
        assert resp.status_code == 200, resp.text
        assert resp.json()["skills"] == []
        await client.aclose()

    async def test_binding_survives_restart(self, tmp_path: Path) -> None:
        from agent_core.application.bootstrap import default_service
        from agent_core.config.settings import Settings

        settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path / "workspace"),
            database_url=f"sqlite:///{tmp_path}/agent.db",
        )
        service = default_service(settings)
        if "helper" not in service.runtime.agents:
            service.runtime.agents.register(AgentSpec(id="helper", name="Helper"))
        service.update_agent("helper", tools=["demo_echo"])

        # New process, same database.
        service2 = default_service(settings)
        agent = service2.runtime.agents.get("helper")
        assert agent.tools == ["demo_echo"]
        service2.store.close()
        service.store.close()
