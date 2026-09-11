"""Project mode: host directories bound to conversations."""

from pathlib import Path

import pytest

from agent_core.domain.project import Project
from agent_core.registries import ProjectRegistry
from agent_core.runtime import context as run_context
from agent_core.runtime.paths import current_task_dir


@pytest.fixture()
def project(tmp_path: Path) -> Project:
    registry = ProjectRegistry()
    project = Project(id="proj-1", name="Demo", path=tmp_path / "proj")
    registry.register(project)
    return project


class TestProjectRegistry:
    def test_roundtrip_through_store(self, tmp_path: Path) -> None:
        from agent_core.persistence.store import SqliteStore

        first = ProjectRegistry(SqliteStore(f"sqlite:///{tmp_path / 'reg.db'}"))
        first.register(Project(id="p1", name="A", path=tmp_path / "a"))

        second = ProjectRegistry(SqliteStore(f"sqlite:///{tmp_path / 'reg.db'}"))
        second.hydrate()

        assert second.get("p1").path == (tmp_path / "a").resolve()

    def test_relative_path_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            Project(id="p", name="A", path=Path("relative/dir"))


class TestTaskRoot:
    def test_bound_task_uses_project_dir(self, tmp_path: Path, project: Project) -> None:
        from tests.unit.test_console import make_service

        service = make_service(tmp_path, pytest.MonkeyPatch())
        service.runtime.projects.register(project)
        task = service.runtime.create_conversation(
            "helper", "hello", project_id=project.id
        )

        assert task.project_id == project.id
        assert service.task_root(task.id) == project.path.resolve()

    def test_unbound_task_has_no_root(self, tmp_path: Path) -> None:
        from tests.unit.test_console import make_service

        service = make_service(tmp_path, pytest.MonkeyPatch())
        task = service.runtime.create_conversation("helper", "hello")

        assert task.project_id is None
        assert service.task_root(task.id) is None

    def test_deleted_project_falls_back(self, tmp_path: Path, project: Project) -> None:
        from tests.unit.test_console import make_service

        service = make_service(tmp_path, pytest.MonkeyPatch())
        service.runtime.projects.register(project)
        task = service.runtime.create_conversation(
            "helper", "hello", project_id=project.id
        )
        service.runtime.projects.remove(project.id)

        assert service.task_root(task.id) is None

    def test_unknown_project_rejected(self, tmp_path: Path) -> None:
        from tests.unit.test_console import make_service

        from agent_core.errors.exceptions import RegistryError

        service = make_service(tmp_path, pytest.MonkeyPatch())
        with pytest.raises(RegistryError):
            service.runtime.create_conversation("helper", "hello", project_id="ghost")


class TestTaskRebind:
    def test_rebind_clear_and_unknown(self, tmp_path: Path, project: Project) -> None:
        from tests.unit.test_console import make_service

        service = make_service(tmp_path, pytest.MonkeyPatch())
        service.runtime.projects.register(project)
        task = service.runtime.create_conversation(
            "helper", "hello", project_id=project.id
        )
        runtime = service.runtime

        # Unknown project fails fast.
        import pytest as _pytest

        from agent_core.errors.exceptions import RegistryError

        with _pytest.raises(RegistryError):
            runtime.update_task(task.id, project_id="ghost")

        # Empty string clears the binding.
        cleared = runtime.update_task(task.id, project_id="")
        assert cleared.project_id is None

        # Rebinding works.
        rebound = runtime.update_task(task.id, project_id=project.id)
        assert rebound.project_id == project.id


class TestProjectScopedExecution:
    async def test_run_code_cwd_is_project_dir(
        self, tmp_path: Path, project: Project
    ) -> None:
        from agent_core.builtins.code import make_run_code
        from agent_core.config.settings import Settings

        settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path / "workspace"),
            agent_env_dir=str(tmp_path / "agent-env"),
        )
        _, handler = make_run_code(settings)
        token = run_context.current_task_root.set(project.path)
        token_id = run_context.current_task_id.set("t1")
        try:
            result = await handler(command="pwd")
        finally:
            run_context.current_task_root.reset(token)
            run_context.current_task_id.reset(token_id)

        assert str(project.path) in result

    def test_current_task_dir_falls_back_to_the_shared_root(self, tmp_path: Path) -> None:
        """An unbound conversation shares the workspace root — no per-task folder."""
        token = run_context.current_task_root.set(None)
        token_id = run_context.current_task_id.set("t9")
        try:
            root = current_task_dir(tmp_path / "workspace")
        finally:
            run_context.current_task_root.reset(token)
            run_context.current_task_id.reset(token_id)

        assert root == tmp_path / "workspace"


class TestRunPublishesProjectRoot:
    async def test_execute_run_sets_project_root_context(
        self, tmp_path: Path, project: Project
    ) -> None:
        """A run bound to a project executes with the project dir as its root."""
        from langchain_core.messages import AIMessage
        from tests.unit.test_console import make_service

        service = make_service(tmp_path, pytest.MonkeyPatch())
        service.runtime.projects.register(project)

        seen: dict[str, object] = {}

        class _ProbeGraph:
            async def ainvoke(self, state: object, config: object = None) -> dict:
                seen["root"] = run_context.current_task_root.get()
                return {"messages": [AIMessage(content="done")]}

        class _ProbeBuilder:
            def build(self, spec: object) -> object:
                return _ProbeGraph()

        service.runtime.builder = _ProbeBuilder()  # type: ignore[assignment]
        task = await service.submit_run(
            "helper", "hello", project_id=project.id, wait=True
        )

        assert task.project_id == project.id
        assert seen["root"] == project.path.resolve()
        # Unbound tasks keep the default (None → workspace/tasks/<id>).
        seen.clear()
        await service.submit_run("helper", "again", wait=True)
        assert seen["root"] is None


class TestProjectApi:
    async def test_create_list_delete(self, tmp_path: Path) -> None:
        from tests.unit.test_console import make_client, make_service

        service = make_service(tmp_path, pytest.MonkeyPatch())
        async with make_client(service) as client:
            created = await client.post(
                "/v1/projects", json={"name": "My App", "path": str(tmp_path / "app")}
            )
            assert created.status_code == 201
            body = created.json()
            assert body["name"] == "My App"
            assert (tmp_path / "app").is_dir()  # created on demand

            listed = (await client.get("/v1/projects")).json()
            assert [p["id"] for p in listed] == [body["id"]]

            deleted = await client.delete(f"/v1/projects/{body['id']}")
            assert deleted.status_code == 200
            assert (await client.get("/v1/projects")).json() == []

    async def test_task_created_with_project(self, tmp_path: Path) -> None:
        from tests.unit.test_console import make_client, make_service

        service = make_service(tmp_path, pytest.MonkeyPatch())
        async with make_client(service) as client:
            project = (await client.post(
                "/v1/projects", json={"name": "P", "path": str(tmp_path / "p")}
            )).json()
            task = (await client.post(
                "/v1/tasks",
                json={"input": "hi", "project_id": project["id"]},
            )).json()
            assert task["project_id"] == project["id"]

            # Rebind via PATCH; "" clears.
            cleared = (await client.patch(
                f"/v1/tasks/{task['id']}", json={"project_id": ""}
            )).json()
            assert cleared["project_id"] is None


class TestRegistryWiring:
    def test_runtime_keeps_store_on_empty_projects_registry(self, tmp_path: Path) -> None:
        """Regression: an empty registry is falsy (BaseRegistry defines
        __len__) — `projects or default()` used to silently swap in a
        store-less registry, losing write-through persistence."""
        from agent_core.persistence.store import SqliteStore
        from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
        from agent_core.runtime.runtime import AgentRuntime

        store = SqliteStore(f"sqlite:///{tmp_path / 'wiring.db'}")
        projects = ProjectRegistry(store)
        runtime = AgentRuntime(
            AgentRegistry(), ToolRegistry(), SkillRegistry(),
            store=store, projects=projects,
        )

        assert runtime.projects is projects
        project = Project(id="p1", name="A", path=tmp_path / "a")
        runtime.projects.register(project)

        fresh = ProjectRegistry(SqliteStore(f"sqlite:///{tmp_path / 'wiring.db'}"))
        fresh.hydrate()
        assert fresh.get("p1").name == "A"
