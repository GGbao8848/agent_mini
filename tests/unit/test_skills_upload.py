"""Unit tests for skill zip upload (extraction + registry install)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from agent_core.api.skills_upload import install_skill_from_zip
from agent_core.errors.exceptions import SkillError
from agent_core.registries.skills import SkillRegistry

FRONTMATTER = """\
---
name: my-skill
description: 演示技能
---

# My Skill

Do the thing.
"""


def _zip_bytes(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _make_skill_zip() -> bytes:
    return _zip_bytes(
        {
            "SKILL.md": FRONTMATTER,
            "scripts/tool.py": "print('hi')\n",
        }
    )


def test_install_from_root_skill_md(tmp_path: Path) -> None:
    registry = SkillRegistry()
    manifest = install_skill_from_zip(_make_skill_zip(), registry, tmp_path)

    assert manifest.id == "my-skill"
    assert manifest.name == "my-skill"
    assert manifest.description == "演示技能"
    assert (manifest.path / "SKILL.md").is_file()
    assert (manifest.path / "scripts" / "tool.py").is_file()
    # Extracted under <workspace>/.skills-upload/<id>/
    assert manifest.path == (tmp_path / ".skills-upload" / "my-skill").resolve()
    assert "my-skill" in registry


def test_install_from_single_top_folder(tmp_path: Path) -> None:
    data = _zip_bytes(
        {
            "my-skill/SKILL.md": FRONTMATTER,
            "my-skill/scripts/tool.py": "print('hi')\n",
        }
    )
    manifest = install_skill_from_zip(data, SkillRegistry(), tmp_path)

    assert manifest.id == "my-skill"
    assert (manifest.path / "scripts" / "tool.py").is_file()
    # The top folder is stripped; files land directly under the target.
    assert not (manifest.path / "my-skill").exists()


def test_skill_id_form_field_overrides_frontmatter(tmp_path: Path) -> None:
    manifest = install_skill_from_zip(
        _make_skill_zip(), SkillRegistry(), tmp_path, skill_id="custom-id"
    )
    assert manifest.id == "custom-id"
    assert (tmp_path / ".skills-upload" / "custom-id").is_dir()


def test_non_zip_raises(tmp_path: Path) -> None:
    with pytest.raises(SkillError, match="not a zip"):
        install_skill_from_zip(b"not a zip file", SkillRegistry(), tmp_path)


def test_missing_skill_md_raises(tmp_path: Path) -> None:
    data = _zip_bytes({"README.md": "no skill here"})
    with pytest.raises(SkillError, match="SKILL.md"):
        install_skill_from_zip(data, SkillRegistry(), tmp_path)


def test_zip_slip_rejected(tmp_path: Path) -> None:
    data = _zip_bytes({"../evil.txt": "bad", "SKILL.md": FRONTMATTER})
    with pytest.raises(SkillError, match="unsafe path"):
        install_skill_from_zip(data, SkillRegistry(), tmp_path)


def test_duplicate_install_raises_and_keeps_original(tmp_path: Path) -> None:
    registry = SkillRegistry()
    first = install_skill_from_zip(_make_skill_zip(), registry, tmp_path)
    target = tmp_path / ".skills-upload" / "my-skill"

    with pytest.raises(Exception, match="already registered"):
        install_skill_from_zip(_make_skill_zip(), registry, tmp_path)
    # The original install stays intact and registered.
    assert target.is_dir()
    assert (target / "SKILL.md").is_file()
    assert registry.get("my-skill").id == first.id


def test_empty_zip_raises(tmp_path: Path) -> None:
    with pytest.raises(SkillError):
        install_skill_from_zip(_zip_bytes({}), SkillRegistry(), tmp_path)
