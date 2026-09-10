"""Skill discovery through the backend (invariant I-03 + R4 regression).

The file-tool backend mounts each skill read-only at ``/skills/<id>/``. The
framework's skill discovery lists the parent ``/skills/`` first, and the
composite backend has no route for that bare parent — so the listing used to
fall through to the task root and fail with ``path_not_found``, silently
leaving skill manifests out of the prompt. SkillsIndexBackend answers that one
listing from the registry.

These tests pin both halves: the parent lists the enabled skills, and the
individual skill directories still serve their real files.
"""

from __future__ import annotations

from pathlib import Path

from deepagents.backends import CompositeBackend, FilesystemBackend

from agent_core.workspace.backend import BoundaryBackend
from agent_core.workspace.skills_index import SkillsIndexBackend


def _backend(tmp_path: Path, skills: dict[str, Path]) -> BoundaryBackend:
    routes = {
        f"/skills/{sid}/": FilesystemBackend(root_dir=src, virtual_mode=True)
        for sid, src in skills.items()
    }
    composite = CompositeBackend(
        default=FilesystemBackend(root_dir=tmp_path), routes=routes
    )
    return BoundaryBackend(SkillsIndexBackend(list(skills), fallback=composite))


def _skill(tmp_path: Path, name: str) -> Path:
    directory = tmp_path / "src" / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} helper\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return directory


async def test_parent_skills_directory_is_listable(tmp_path: Path) -> None:
    skills = {"alpha": _skill(tmp_path, "alpha"), "beta": _skill(tmp_path, "beta")}
    backend = _backend(tmp_path, skills)

    result = await backend.als("/skills/")

    assert result.error is None
    assert {e["path"] for e in (result.entries or [])} == {"/skills/alpha", "/skills/beta"}


async def test_parent_listing_works_synchronously_too(tmp_path: Path) -> None:
    backend = _backend(tmp_path, {"alpha": _skill(tmp_path, "alpha")})
    assert backend.ls("/skills/").error is None


async def test_skill_directory_still_serves_real_files(tmp_path: Path) -> None:
    backend = _backend(tmp_path, {"alpha": _skill(tmp_path, "alpha")})

    result = await backend.als("/skills/alpha/")

    assert result.error is None
    assert any(e["path"].endswith("SKILL.md") for e in (result.entries or []))


async def test_readme_registry_names_load_through_the_backend(tmp_path: Path) -> None:
    """The framework's discovery routine finds every skill (no silent skip)."""
    from deepagents.middleware.skills import _alist_skills_with_errors

    skills = {"alpha": _skill(tmp_path, "alpha"), "beta": _skill(tmp_path, "beta")}
    backend = _backend(tmp_path, skills)

    metas, error = await _alist_skills_with_errors(backend, "/skills/")

    assert error is None
    assert {m.get("name") for m in metas} == {"alpha", "beta"}


async def test_unknown_path_delegates_to_fallback(tmp_path: Path) -> None:
    backend = _backend(tmp_path, {"alpha": _skill(tmp_path, "alpha")})
    # A task-root path still resolves via the composite fallback.
    (tmp_path / "outputs").mkdir(exist_ok=True)
    (tmp_path / "outputs" / "a.txt").write_text("hi", encoding="utf-8")
    result = await backend.als("/outputs/")
    assert result.error is None


def test_no_skills_lists_empty_not_error(tmp_path: Path) -> None:
    backend = _backend(tmp_path, {})
    result = backend.ls("/skills/")
    assert result.error is None
    assert result.entries == []
