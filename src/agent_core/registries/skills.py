"""Skill Registry: versioned store of SkillManifest metadata."""

from __future__ import annotations

from collections.abc import Sequence

from agent_core.domain.skill import SkillManifest
from agent_core.errors.exceptions import RegistryError
from agent_core.persistence.store import SqliteStore

# Alias keeps ``list``-returning annotations unambiguous even though the class
# defines a method named ``list`` (class-body scope would otherwise shadow the
# builtin for signatures declared after it).
ManifestList = list[SkillManifest]


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

    def _forget(self, skill_id: str, versions: Sequence[str]) -> None:
        if self._store is not None:
            for version in versions:
                self._store.delete_item(self.kind, self._key(skill_id, version))

    def __contains__(self, skill_id: object) -> bool:
        return skill_id in self._versions

    def __len__(self) -> int:
        return len(self._versions)
