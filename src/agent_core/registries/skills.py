"""Skill Registry: an in-memory view over the skills *directory*.

The directory is the source of truth (see ``docs/skills-as-directory.md``): one
sub-directory per skill, each with a ``SKILL.md``. Production populates the
registry from that directory via :meth:`SkillRegistry.sync_from_dir`; nothing
registers a skill by hand any more. The versioned/register API that remains is
kept only for tests and tools that build a manifest in memory — ``sync_from_dir``
always returns the registry to the directory's contents.

The skill **id** is the directory name; ``name``/``description``/``version``
come from the ``SKILL.md`` frontmatter.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import yaml

from agent_core.domain.skill import SkillManifest
from agent_core.errors.exceptions import RegistryError
from agent_core.persistence.store import SqliteStore

# Alias keeps ``list``-returning annotations unambiguous even though the class
# defines a method named ``list`` (class-body scope would otherwise shadow the
# builtin for signatures declared after it).
ManifestList = list[SkillManifest]

_SKILL_MD = "SKILL.md"


class SkillRegistry:
    """Skills are versioned: one id may hold several registered versions.

    The most recently registered version of an id is the "latest" one and is
    what plain ``get``/``list`` return; specific versions stay addressable.
    """

    kind = "skill"

    def __init__(self, store: SqliteStore | None = None) -> None:
        self._versions: dict[str, dict[str, SkillManifest]] = {}
        self._store = store

    def _key(self, skill_id: str, version: str) -> str:
        return f"{skill_id}@{version}"

    def register(self, manifest: SkillManifest) -> None:
        """Register one version of a skill; exact id+version duplicates raise."""
        versions = self._versions.setdefault(manifest.id, {})
        if manifest.version in versions:
            raise RegistryError(
                kind=self.kind,
                key=self._key(manifest.id, manifest.version),
                detail="already registered",
            )
        versions[manifest.version] = manifest
        if self._store is not None:
            self._store.save_item(
                self.kind,
                self._key(manifest.id, manifest.version),
                manifest.model_dump_json(),
            )

    def update(self, manifest: SkillManifest) -> SkillManifest:
        """Persist edits to an existing manifest (e.g. the enabled toggle)."""
        versions = self._versions.get(manifest.id)
        if versions is None or manifest.version not in versions:
            raise RegistryError(kind=self.kind, key=manifest.id, detail="not found")
        versions[manifest.version] = manifest
        if self._store is not None:
            self._store.save_item(
                self.kind,
                self._key(manifest.id, manifest.version),
                manifest.model_dump_json(),
            )
        return manifest

    def get(self, skill_id: str, version: str | None = None) -> SkillManifest:
        """Return ``version`` of the skill, or the latest registered version."""
        versions = self._versions.get(skill_id)
        if not versions:
            raise RegistryError(kind=self.kind, key=skill_id, detail="not found")
        if version is not None:
            try:
                return versions[version]
            except KeyError:
                raise RegistryError(
                    kind=self.kind, key=f"{skill_id}@{version}", detail="version not found"
                ) from None
        return list(versions.values())[-1]

    def latest_version_of(self, skill_id: str) -> str:
        """Version string of the latest registered version of ``skill_id``."""
        return self.get(skill_id).version

    def list(self) -> ManifestList:
        """Latest version of every registered skill, in registration order."""
        return [list(versions.values())[-1] for versions in self._versions.values()]

    def list_versions(self, skill_id: str) -> ManifestList:
        """All registered versions of one skill, oldest first."""
        self.get(skill_id)
        return list(self._versions[skill_id].values())

    def remove(self, skill_id: str, version: str | None = None) -> SkillManifest:
        """Remove one version, or the whole skill when ``version`` is omitted."""
        versions = self._versions.get(skill_id)
        if not versions:
            raise RegistryError(kind=self.kind, key=skill_id, detail="not found")
        if version is None:
            removed = list(versions.values())[-1]
            self._forget(skill_id, list(versions))
            del self._versions[skill_id]
            return removed
        try:
            removed = versions.pop(version)
        except KeyError:
            raise RegistryError(
                kind=self.kind, key=f"{skill_id}@{version}", detail="version not found"
            ) from None
        self._forget(skill_id, [version])
        if not versions:
            del self._versions[skill_id]
        return removed

    def hydrate(self) -> None:
        """Load manifests persisted by a previous process (no-op without a store)."""
        if self._store is None:
            return
        for key, data in self._store.load_items(self.kind):
            skill_id, _, stored_version = key.rpartition("@")
            manifest = SkillManifest.model_validate_json(data)
            self._versions.setdefault(skill_id, {}).setdefault(stored_version, manifest)

    def sync_from_dir(self, root: Path) -> ManifestList:
        """Make the registry mirror ``root`` — the skills directory is the truth.

        Each immediate sub-directory that contains a ``SKILL.md`` becomes a
        skill; the directory name is the id. Sub-directories without a
        ``SKILL.md`` (a half-written skill, or a stray file) are skipped, not
        fatal — the agent may be mid-edit. This *replaces* the whole registry,
        so deleting a directory removes its skill. Returns the new contents.

        The registry is a read-through view, not a store: when it is backed by
        a ``SqliteStore`` this method writes nothing (a derived view must never
        become a second source of truth), it only reads the directory.
        """
        discovered: dict[str, dict[str, SkillManifest]] = {}
        if root.is_dir():
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                skill_md = child / _SKILL_MD
                if not skill_md.is_file():
                    continue
                discovered[child.name] = {
                    "0.1.0": _manifest_from_skill_md(child.name, skill_md, child)
                }
        self._versions = discovered
        return self.list()

    def _forget(self, skill_id: str, versions: Sequence[str]) -> None:
        if self._store is not None:
            for version in versions:
                self._store.delete_item(self.kind, self._key(skill_id, version))

    def __contains__(self, skill_id: object) -> bool:
        return skill_id in self._versions

    def __len__(self) -> int:
        return len(self._versions)


def _manifest_from_skill_md(skill_id: str, skill_md: Path, directory: Path) -> SkillManifest:
    """Build a manifest from one skill directory's ``SKILL.md``.

    name and description come from the frontmatter; a malformed ``SKILL.md``
    (bad YAML, no frontmatter) still yields a manifest, because an unreadable
    skill directory should not take down a run.
    """
    try:
        raw = skill_md.read_text("utf-8")
    except (OSError, UnicodeDecodeError):
        raw = ""
    frontmatter = _parse_frontmatter(raw)
    name = str(frontmatter.get("name") or skill_id).strip() or skill_id
    description = str(frontmatter.get("description") or "").strip()
    version = str(frontmatter.get("version") or "0.1.0").strip() or "0.1.0"
    return SkillManifest(
        id=skill_id,
        name=name,
        version=version,
        description=description,
        path=directory,
    )


def _parse_frontmatter(text: str) -> dict[str, object]:
    """Parse the YAML frontmatter block of a ``SKILL.md`` (empty dict if absent)."""
    if not text.startswith("---"):
        return {}
    body: list[str] = []
    for line in text.splitlines()[1:]:
        if line.strip() == "---":
            break
        body.append(line)
    try:
        parsed = yaml.safe_load("\n".join(body))
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
