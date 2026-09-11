"""Shared-workspace artifact behavior tests.

Every unbound conversation works in the one shared workspace root (no
per-conversation folder), so a run's deliverables are discovered relative to
that root; a run bound to a project resolves against the project directory.
Explicit tool claims feed the manifest, and ``skills/`` / ``uploads/`` are
never reported as deliverables.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tests.unit.test_console import make_service

from agent_core.artifacts import register_artifact, scan_run_artifacts
from agent_core.builtins.code import make_run_code
from agent_core.runtime.context import current_task_id


class TestSharedWorkspace:
    async def test_artifacts_land_in_the_shared_root(self, tmp_path, monkeypatch) -> None:
        service = make_service(tmp_path, monkeypatch)
        run = service.runtime.create_run("helper", "produce a file")

        await service.runtime.execute_run(run)

        workspace = tmp_path / "workspace" / "default"
        assert (workspace / "out" / "hello.md").is_file()
        # The manifest path is relative to the run root (the shared workspace).
        paths = [a["path"] for a in run.metadata["artifacts"]]
        assert "out/hello.md" in paths

    async def test_a_second_conversation_sees_the_first_ones_files(
        self, tmp_path, monkeypatch
    ) -> None:
        """The whole point: no per-conversation sandbox, files persist."""
        service = make_service(tmp_path, monkeypatch)
        first = service.runtime.create_run("helper", "make a script")
        await service.runtime.execute_run(first)

        second = service.runtime.create_run("helper", "reuse the script")
        second_root = service.runtime.task_root(second.task_id) or Path("workspace") / "default"

        # The second conversation's folder is the same shared `default` folder as
        # the first's, and the file the first one wrote is still there.
        assert second_root.resolve() == (tmp_path / "workspace" / "default").resolve()
        assert (second_root / "out" / "hello.md").is_file()

    async def test_scan_skips_mirrored_uploads(self, tmp_path, monkeypatch) -> None:
        workspace = tmp_path / "workspace" / "default"
        for rel in (
            "uploads/batch/x.pdf",
            "out/deck.pptx",
        ):
            path = workspace / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")

        found = {a["path"] for a in scan_run_artifacts(workspace, since_ts=0)}

        assert "out/deck.pptx" in found
        assert "uploads/batch/x.pdf" not in found


class TestExplicitClaims:
    def test_register_and_claim(self, tmp_path: Path) -> None:
        from agent_core.artifacts import claimed_artifacts, clear_claims

        workspace = tmp_path / "workspace"
        (workspace / "ppt").mkdir(parents=True)
        deck = workspace / "ppt" / "a.pptx"
        deck.write_bytes(b"PK")

        register_artifact(workspace, "claim-a", deck)

        claims = claimed_artifacts("claim-a")
        assert [c["path"] for c in claims] == ["ppt/a.pptx"]
        assert claims[0]["size"] == 2
        clear_claims("claim-a")

    def test_claim_outside_root_is_ignored(self, tmp_path: Path) -> None:
        from agent_core.artifacts import claimed_artifacts

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "secret.txt"
        outside.write_text("x")

        register_artifact(workspace, "claim-b", outside)

        assert claimed_artifacts("claim-b") == []

    def test_run_code_scopes_to_the_shared_workspace(self, tmp_path: Path) -> None:
        """run_code runs with cwd = the shared workspace root (no task folder)."""
        from agent_core.config.settings import Settings

        settings = Settings(_env_file=None, workspace_dir=str(tmp_path / "workspace"))
        definition, handler = make_run_code(settings)

        async def run_in_task() -> str:
            token = current_task_id.set("task-xyz")
            try:
                return await handler(command="pwd")
            finally:
                current_task_id.reset(token)

        output = asyncio.run(run_in_task())
        assert str(tmp_path / "workspace") in output
        assert "tasks/task-xyz" not in output


class TestAttachmentMirroring:
    def test_uploads_are_mirrored_into_the_working_folder(self, tmp_path: Path) -> None:
        """Uploads are staged at the workspace root (outside the working folder),
        so the referenced batch is mirrored into the folder the file tools see."""
        from agent_core.api.attachments import mirror_attachments, save_attachments
        from agent_core.workspace.layout import default_root

        workspace = tmp_path / "workspace"
        saved = save_attachments(workspace, "batch1", [("report.pdf", b"PDF")])

        mirror_attachments(workspace, default_root(workspace), [saved[0]["path"]])

        dest = workspace / "default" / saved[0]["path"]
        assert dest.is_file()
        assert dest.read_bytes() == b"PDF"

    def test_mirror_skips_non_uploads_and_missing_batches(self, tmp_path: Path) -> None:
        from agent_core.api.attachments import mirror_attachments
        from agent_core.workspace.layout import default_root

        workspace = tmp_path / "workspace"
        root = default_root(workspace)
        mirror_attachments(workspace, root, ["ppt/slides.pptx", "uploads/nope/x.pdf"])

        assert not list(root.rglob("*"))


class TestPreviewEndpoint:
    async def test_text_image_and_binary_kinds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tests.unit.test_console import make_client

        service = make_service(tmp_path, monkeypatch)
        task = service.runtime.create_conversation("helper", "hi")
        root = tmp_path / "workspace" / "default"
        root.mkdir(parents=True, exist_ok=True)
        (root / "notes.md").write_text("# 标题\n正文", encoding="utf-8")
        (root / "pic.png").write_bytes(b"\x89PNG fake")
        (root / "data.bin").write_bytes(b"\x00\x01\x02")

        run = service.runtime.create_run("helper", "hi", task=task)

        async with make_client(service) as client:
            base = f"/v1/artifacts/{run.id}/preview"
            text = (await client.get(base, params={"path": "notes.md"})).json()
            assert text["kind"] == "text" and "# 标题" in text["content"]

            image = (await client.get(base, params={"path": "pic.png"})).json()
            assert image["kind"] == "image"

            binary = (await client.get(base, params={"path": "data.bin"})).json()
            assert binary["kind"] == "binary" and "content" not in binary

            missing = await client.get(base, params={"path": "../escape.md"})
            assert missing.status_code == 404
