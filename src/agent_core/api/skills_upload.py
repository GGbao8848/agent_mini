"""Skill zip upload: safe extraction into the workspace + registry install.

The console lets a user drop a skill archive (zip) instead of pre-placing
files on the server disk. The archive follows the skill directory convention
(a top-level ``SKILL.md``, optional ``references/ scripts/ assets/``). This
module extracts it under ``<workspace>/.skills-upload/<skill_id>/`` with
zip-slip protection, validates the layout, reads the manifest from the
``SKILL.md`` frontmatter, and registers it with the SkillRegistry.
"""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path

import yaml

from agent_core.domain.skill import SkillManifest
from agent_core.errors.exceptions import SkillError
from agent_core.registries.skills import SkillRegistry

# Skill ids are registry keys and directory names: keep them filesystem-safe.
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# A zip bomb guard: refuse to unpack more than this many bytes or entries.
_MAX_TOTAL_BYTES = 256 * 1024 * 1024  # 256 MiB uncompressed
_MAX_ENTRIES = 10_000


def install_skill_from_zip(
    archive: bytes,
    registry: SkillRegistry,
    workspace_dir: str | Path,
    *,
    skill_id: str | None = None,
    version: str = "0.1.0",
) -> SkillManifest:
    """Extract ``archive`` (a skill zip) into the workspace and register it.

    ``skill_id`` overrides the id read from the ``SKILL.md`` frontmatter; when
    omitted the frontmatter ``name`` is used. Returns the registered
    ``SkillManifest``.
    """
    workspace = Path(workspace_dir).expanduser().resolve()
    try:
        zf = zipfile.ZipFile(io.BytesIO(archive))
    except zipfile.BadZipFile as exc:
        raise SkillError("Uploaded file is not a zip archive") from exc

    # Sanity-scan the archive before writing anything.
    names = _safe_members(zf)

    top, frontmatter = _locate_skill_md(names)
    if top is None or frontmatter is None:
        raise SkillError(
            "Skill zip must contain a SKILL.md at the archive root "
            "(or in a single top-level folder)"
        )

    meta = _parse_frontmatter(zf.read(frontmatter))
    resolved_id = skill_id or str(meta.get("name") or "").strip()
    if not resolved_id or not _SAFE_ID.match(resolved_id):
        raise SkillError(
            f"Invalid skill id '{resolved_id}'; use letters/digits/dot/dash/underscore"
        )
    name = str(meta.get("name") or resolved_id).strip() or resolved_id
    description = str(meta.get("description") or "").strip()

    target = workspace / ".skills-upload" / resolved_id
    existed = target.exists()
    try:
        _extract(zf, names, top, target)
        manifest = SkillManifest(
            id=resolved_id,
            name=name,
            version=version,
            description=description,
            path=target,
        )
        registry.register(manifest)
    except Exception:
        # On failure leave no partial extraction behind — but never delete a
        # directory that already held a previously registered skill (a
        # duplicate id+version install must not destroy the installed copy).
        if not existed:
            shutil.rmtree(target, ignore_errors=True)
        raise
    return manifest


def _safe_members(zf: zipfile.ZipFile) -> list[str]:
    """Return member names after a zip-slip / size sanity scan."""
    names: list[str] = []
    total = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        # Normalize separators and reject any path escaping the target dir.
        parts = Path(name).parts
        if ".." in parts or name.startswith("/") or (len(parts) > 1 and parts[0] in ("..", "")):
            raise SkillError(f"Skill zip contains an unsafe path: {name}")
        total += info.file_size
        if total > _MAX_TOTAL_BYTES or len(names) >= _MAX_ENTRIES:
            raise SkillError("Skill zip is too large")
        names.append(name)
    if not names:
        raise SkillError("Skill zip is empty")
    return names


def _locate_skill_md(names: list[str]) -> tuple[str | None, str | None]:
    """Find the root dir ('' or the single top-level folder) and SKILL.md path.

    Returns ``(top_dir, skill_md_path)``. The archive root ``SKILL.md`` wins;
    otherwise a single top-level folder containing ``SKILL.md`` is accepted.
    """
    if "SKILL.md" in names:
        return "", "SKILL.md"
    tops: set[str] = set()
    for name in names:
        head = name.split("/", 1)[0]
        tops.add(head)
    if len(tops) == 1:
        top = next(iter(tops))
        md = f"{top}/SKILL.md"
        if md in names:
            return top, md
    return None, None


def _parse_frontmatter(text: bytes) -> dict[str, object]:
    """Parse the YAML frontmatter block of a SKILL.md (empty dict if absent)."""
    try:
        raw = text.decode("utf-8")
    except UnicodeDecodeError:
        return {}
    if not raw.startswith("---"):
        return {}
    # Split on the closing --- (first line that is exactly --- after the opener).
    lines = raw.splitlines()
    body: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        body.append(line)
    try:
        parsed = yaml.safe_load("\n".join(body))
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract(zf: zipfile.ZipFile, names: list[str], top: str, target: Path) -> None:
    """Extract members under ``target``, stripping the optional top folder."""
    target.mkdir(parents=True, exist_ok=True)
    for name in names:
        rel = name[len(top) :].lstrip("/") if top else name
        dest = (target / rel).resolve()
        if not dest.is_relative_to(target):
            raise SkillError(f"Skill zip contains an unsafe path: {name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(name) as src, open(dest, "wb") as out:
            while chunk := src.read(64 * 1024):
                out.write(chunk)
