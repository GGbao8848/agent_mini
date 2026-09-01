"""Task-isolated artifact storage (feat/artifact-storage) behavior tests.

Covers the new contract: every task's artifacts live under
``workspace/tasks/<task_id>/``, downloads resolve against that task root,
explicit tool claims feed the manifest, and concurrent tasks cannot leak
files into each other's panel.
"""

from __future__ import annotations

from pathlib import Path

from tests.unit.test_console import make_client, make_service

from agent_core.artifacts import (
    register_artifact,
    scan_task_artifacts,
    task_workspace,
)
from agent_core.builtins.code import make_run_code
from agent_core.runtime.context import current_task_id


class TestTaskIsolation:
    async def test_artifacts_land_under_task_dir(self, tmp_path, monkeypatch) -> None:
        service = make_service(tmp_path, monkeypatch)
        run = service.runtime.create_run("helper", "produce a file")

        await service.runtime.execute_run(run)

        workspace = tmp_path / "workspace"
        task_dir = workspace / "tasks" / run.task_id
        assert (task_dir / "out" / "hello.md").is_file()
        # The task's manifest path is task-relative.
        paths = [a["path"] for a in run.metadata["artifacts"]]
        assert "out/hello.md" in paths

    async def test_concurrent_task_does_not_leak(self, tmp_path, monkeypatch) -> None:
        """A sibling task writing at the same moment must not show in ours."""
        service = make_service(tmp_path, monkeypatch)
        run_a = service.runtime.create_run("helper", "task a")
        run_b = service.runtime.create_run("helper", "task b")

        await service.runtime.execute_run(run_a)
        await service.runtime.execute_run(run_b)

        workspace = tmp_path / "workspace"
        # Each task's scan only sees its own directory.
        a_paths = [a["path"] for a in scan_task_artifacts(workspace, run_a.task_id, since_ts=0)]
        b_paths = [a["path"] for a in scan_task_artifacts(workspace, run_b.task_id, since_ts=0)]
        assert "out/hello.md" in a_paths
        assert "out/hello.md" in b_paths
        assert (workspace / "tasks" / run_a.task_id / "out" / "hello.md").is_file()
        assert (workspace / "tasks" / run_b.task_id / "out" / "hello.md").is_file()

    async def test_download_resolves_against_task_root(self, tmp_path, monkeypatch) -> None:
        service = make_service(tmp_path, monkeypatch)
        client = make_client(service)
        run = service.runtime.create_run("helper", "produce a file")

        await service.runtime.execute_run(run)

        response = await client.get(
            f"/v1/artifacts/{run.id}/download", params={"path": "out/hello.md"}
        )
        assert response.status_code == 200
        assert response.text == "# hi"
        # A file with the same name in another task must not resolve here.
        other = tmp_path / "workspace" / "tasks" / "some-other-task" / "out" / "hello.md"
        other.parent.mkdir(parents=True)
        other.write_text("other")
        assert (await client.get(
            f"/v1/artifacts/{run.id}/download", params={"path": "out/hello.md"}
        )).text == "# hi"  # still ours, not the sibling's
        await client.aclose()


class TestExplicitClaims:
    def test_register_and_claim(self, tmp_path: Path) -> None:
        from agent_core.artifacts import claimed_artifacts, clear_claims

        workspace = tmp_path / "workspace"
        task_root = task_workspace(workspace, "claim-a")
        (task_root / "ppt").mkdir(parents=True)
        deck = task_root / "ppt" / "a.pptx"
        deck.write_bytes(b"PK")

        register_artifact(workspace, "claim-a", deck)

        claims = claimed_artifacts("claim-a")
        assert [c["path"] for c in claims] == ["ppt/a.pptx"]
        assert claims[0]["size"] == 2
        clear_claims("claim-a")

    def test_claim_outside_task_dir_is_ignored(self, tmp_path: Path) -> None:
        from agent_core.artifacts import claimed_artifacts

        workspace = tmp_path / "workspace"
        outside = tmp_path / "secret.txt"
        outside.write_text("x")

        register_artifact(workspace, "claim-b", outside)

        assert claimed_artifacts("claim-b") == []

    def test_run_code_scopes_to_task_dir(self, tmp_path: Path) -> None:
        """run_code runs with cwd = the current task's directory."""
        from agent_core.config.settings import Settings

        settings = Settings(_env_file=None, workspace_dir=str(tmp_path / "workspace"))
        definition, handler = make_run_code(settings)

        async def run_in_task() -> str:
            token = current_task_id.set("task-xyz")
            try:
                return await handler(command="pwd")
            finally:
                current_task_id.reset(token)

        import asyncio

        output = asyncio.run(run_in_task())
        assert str(tmp_path / "workspace" / "tasks" / "task-xyz") in output


class TestAttachmentMirroring:
    def test_uploads_mirrored_into_task_dir(self, tmp_path: Path) -> None:
        from agent_core.api.attachments import mirror_attachments, save_attachments

        workspace = tmp_path / "workspace"
        saved = save_attachments(workspace, "batch1", [("report.pdf", b"PDF")])

        mirror_attachments(workspace, "task-1", [saved[0]["path"]])

        dest = workspace / "tasks" / "task-1" / saved[0]["path"]
        assert dest.is_file()
        assert dest.read_bytes() == b"PDF"

    def test_mirror_skips_missing_and_non_uploads(self, tmp_path: Path) -> None:
        from agent_core.api.attachments import mirror_attachments

        workspace = tmp_path / "workspace"
        # A non-upload path and a nonexistent batch are both ignored safely.
        mirror_attachments(workspace, "task-1", ["ppt/slides.pptx", "uploads/nope/x.pdf"])

        assert not (workspace / "tasks" / "task-1").exists() or not list(
            (workspace / "tasks" / "task-1").rglob("*")
        )
