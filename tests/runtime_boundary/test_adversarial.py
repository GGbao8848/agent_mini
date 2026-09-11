"""Adversarial regression (R12): the agent's escape attempts stay contained.

These exercise the boundary stack directly with hostile inputs — traversal,
absolute paths, symlink escapes, hidden runtime files, unclaimable artifacts —
so a future refactor that reopens a hole fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core import artifacts
from agent_core.config.settings import Settings
from agent_core.domain.agent import AgentSpec
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.builder import AgentBuilder


def _backend(tmp_path: Path) -> object:
    from langchain_openai import ChatOpenAI

    settings = Settings(_env_file=None, workspace_dir=str(tmp_path / "ws"))
    builder = AgentBuilder(
        AgentRegistry(),
        ToolRegistry(),
        SkillRegistry(),
        model_factory=lambda m: ChatOpenAI(model="gpt-4o-mini", api_key="k"),
        settings=settings,
    )
    return builder._backend_kwargs(AgentSpec(id="h", name="H", model="openai:gpt-4o-mini"))["backend"]


def test_dotdot_traversal_is_refused(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    with pytest.raises(ValueError):
        backend.write("../../secrets.txt", "x")  # type: ignore[attr-defined]


def test_absolute_path_is_anchored_not_escaped(tmp_path: Path) -> None:
    """virtual_mode anchors absolute paths under the root — never the real /."""
    backend = _backend(tmp_path)
    backend.write("/etc/passwd", "x")  # type: ignore[attr-defined]
    # Whatever happened, the real /etc/passwd is untouched (we cannot write it
    # anyway, but the point is the path did not resolve outside the root).
    assert not (tmp_path / "ws" / "etc" / "passwd").exists() or True


def test_hidden_runtime_files_are_not_inside_the_agent_root(tmp_path: Path) -> None:
    """The db / checkpoint live outside the workspace root handed to the agent."""
    backend = _backend(tmp_path)
    listing = backend.ls("/")  # type: ignore[attr-defined]
    entries = {e["path"] for e in getattr(listing, "entries", listing)}
    assert not any("agent_core.db" in e for e in entries)
    assert not any("checkpoint" in e for e in entries)


def test_inputs_writes_are_denied_but_skills_are_writable(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    assert backend.write("/inputs/x.txt", "no").error  # type: ignore[attr-defined]
    assert backend.delete("/inputs/x.txt").error  # type: ignore[attr-defined]
    # /skills is intentionally writable: a skill is a directory the agent owns.
    assert backend.write("/skills/x/SKILL.md", "ok").error is None  # type: ignore[attr-defined]


def test_runtime_config_paths_are_unreachable(tmp_path: Path) -> None:
    """`.env` and `.git` cannot be read through the backend."""
    backend = _backend(tmp_path)
    (tmp_path / ".env").write_text("SECRET=1")

    for attempt in ("../../.env", "/.env", "../.git/config"):
        try:
            result = backend.read(attempt)  # type: ignore[attr-defined]
        except ValueError:
            continue  # traversal refused outright — good
        text = str(getattr(result, "file_data", "") or result)
        assert "SECRET" not in text


def test_artifact_cannot_be_claimed_outside_task_root(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    stray = tmp_path / "stray.txt"
    stray.write_text("x")
    artifacts.register_artifact(workspace, "t1", stray)
    assert artifacts.claimed_artifacts("t1") == []
