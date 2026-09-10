"""Skill index backend: makes the parent ``/skills/`` mount listable.

The file-tool backend mounts each enabled skill read-only at ``/skills/<id>/``
through a :class:`~deepagents.backends.CompositeBackend` route. But the
framework's skill discovery lists the **parent** directory first:

    ls("/skills/")              -> the skill directories
    then reads /skills/<id>/SKILL.md

The composite backend routes by longest prefix, and no route matched the bare
``/skills/``, so that listing fell through to the default (task-root) backend
and failed with ``path_not_found``. The result was silent: skill manifests
never reached the prompt, and ``skills_metadata`` came back empty. (The agent
only knew skills existed because :mod:`agent_core.runtime.paths` names them in
the environment note — the framework's own listing was dead.)

:class:`SkillsIndexBackend` answers that one listing from the registry's
enabled skill ids. It copies nothing (invariant I-03: the skill source stays the
single source of truth) and does not read the skills itself — the longer
``/skills/<id>/`` routes still serve every real access. Only the parent lookup
lands here.
"""

from __future__ import annotations

from typing import Any

from deepagents.backends.protocol import FileInfo, LsResult

# The parent of the skill mounts. Both the bare and trailing-slash spellings
# arrive here (the composite strips the matched prefix, which is empty).
_PARENT_PATHS = frozenset({"", "/", "/skills", "/skills/", "skills", "skills/"})


class SkillsIndexBackend:
    """Lists the enabled skill directories under ``/skills/`` (read-only view)."""

    def __init__(self, skill_ids: list[str], *, fallback: Any | None = None) -> None:
        self._skill_ids = list(skill_ids)
        self._fallback = fallback

    def _entries(self) -> list[FileInfo]:
        return [
            FileInfo(path=f"/skills/{skill_id}", is_dir=True) for skill_id in self._skill_ids
        ]

    @staticmethod
    def _is_parent(path: str) -> bool:
        return path in _PARENT_PATHS

    def ls(self, path: str) -> LsResult:
        if self._is_parent(path):
            return LsResult(entries=self._entries())
        if self._fallback is not None:
            return self._fallback.ls(path)  # type: ignore[no-any-return]
        return LsResult(error=f"Path '{path}': path_not_found", entries=None)

    async def als(self, path: str) -> LsResult:
        if self._is_parent(path):
            return LsResult(entries=self._entries())
        if self._fallback is not None:
            return await self._fallback.als(path)  # type: ignore[no-any-return]
        return LsResult(error=f"Path '{path}': path_not_found", entries=None)

    def __getattr__(self, name: str) -> Any:
        # Any other operation (a stray read/write under a path that did not
        # match a skill route) goes to the fallback, preserving the previous
        # behaviour — and BoundaryBackend still blocks writes into /skills/**.
        fallback = object.__getattribute__(self, "_fallback")
        if fallback is None:
            raise AttributeError(name)
        return getattr(fallback, name)
