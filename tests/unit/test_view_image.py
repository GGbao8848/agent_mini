"""Tests for view_image's path resolution (task-dir + basename fallback)."""

from __future__ import annotations

from pathlib import Path

from agent_core.builtins.image import _resolve_image_path
from agent_core.config.settings import Settings
from agent_core.runtime.context import current_task_id


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, workspace_dir=str(tmp_path / "workspace"))


def _setup(tmp_path: Path) -> tuple[Settings, Path]:
    settings = _settings(tmp_path)
    task_root = tmp_path / "workspace" / "tasks" / "task-1" / "work" / "video" / "video" / "slides"
    task_root.mkdir(parents=True)
    (task_root / "slide_01.png").write_bytes(b"PNG")
    return settings, task_root


def test_exact_relative_path_resolves(tmp_path: Path) -> None:
    settings, task_root = _setup(tmp_path)
    token = current_task_id.set("task-1")
    try:
        resolved = _resolve_image_path(settings, "work/video/video/slides/slide_01.png")
    finally:
        current_task_id.reset(token)
    assert resolved == (task_root / "slide_01.png").resolve()


def test_task_relative_path_resolves(tmp_path: Path) -> None:
    settings, task_root = _setup(tmp_path)
    token = current_task_id.set("task-1")
    try:
        resolved = _resolve_image_path(settings, "video/slides/slide_01.png")
    finally:
        current_task_id.reset(token)
    assert resolved is not None
    assert resolved.name == "slide_01.png"


def test_host_absolute_path_resolves_into_task_dir(tmp_path: Path) -> None:
    """Agent passes /home/.../workspace/video/slides/x.png; under task
    isolation the file lives in the task dir, so strip the workspace prefix
    and re-resolve against the task root."""
    settings, task_root = _setup(tmp_path)
    token = current_task_id.set("task-1")
    try:
        host_path = str((tmp_path / "workspace" / "video" / "slides" / "slide_01.png").resolve())
        resolved = _resolve_image_path(settings, host_path)
    finally:
        current_task_id.reset(token)
    assert resolved is not None
    assert resolved.name == "slide_01.png"


def test_basename_fallback_finds_relocated_file(tmp_path: Path) -> None:
    """Wrong prefix (e.g. work/video/video/...) still resolves by basename."""
    settings, task_root = _setup(tmp_path)
    token = current_task_id.set("task-1")
    try:
        resolved = _resolve_image_path(settings, "video/slides/slide_01.png")
    finally:
        current_task_id.reset(token)
    assert resolved is not None
    assert resolved.name == "slide_01.png"


def test_missing_file_returns_none(tmp_path: Path) -> None:
    settings, _ = _setup(tmp_path)
    token = current_task_id.set("task-1")
    try:
        resolved = _resolve_image_path(settings, "nope/missing.png")
    finally:
        current_task_id.reset(token)
    assert resolved is None
