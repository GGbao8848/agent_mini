"""Skill Registry: versioned store of SkillManifest metadata."""

from __future__ import annotations

from agent_core.domain.skill import SkillManifest
from agent_core.errors.exceptions import RegistryError

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

    def __init__(self) -> None:
        self._versions: dict[str, dict[str, SkillManifest]] = {}

    def register(self, manifest: SkillManifest) -> None:
        """Register one version of a skill; exact id+version duplicates raise."""
        versions = self._versions.setdefault(manifest.id, {})
        if manifest.version in versions:
            raise RegistryError(
                kind=self.kind,
                key=f"{manifest.id}@{manifest.version}",
                detail="already registered",
            )
        versions[manifest.version] = manifest

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
            del self._versions[skill_id]
            return removed
        try:
            removed = versions.pop(version)
        except KeyError:
            raise RegistryError(
                kind=self.kind, key=f"{skill_id}@{version}", detail="version not found"
            ) from None
        if not versions:
            del self._versions[skill_id]
        return removed

    def __contains__(self, skill_id: object) -> bool:
        return skill_id in self._versions

    def __len__(self) -> int:
        return len(self._versions)
