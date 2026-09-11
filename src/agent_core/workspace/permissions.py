"""Filesystem permission rules for the DeepAgents filesystem middleware.

The engine (``FilesystemMiddleware._permissions`` / ``FilesystemPermission``)
already denies matching calls; this module only states the project's policy:

- ``/inputs/**`` — read-only: user-provided material is immutable.

Writes elsewhere (workspace / outputs / scratch / **skills**) are allowed.
``/skills`` is deliberately writable: a skill is a directory the agent owns and
edits with its ordinary file tools (see ``docs/skills-as-directory.md``). Keep
this list the single place the boundary is expressed so tests and the builder
cannot drift.
"""

from __future__ import annotations

from typing import Any, Literal

_READ_ONLY_PATTERNS: tuple[str, ...] = ("/inputs/**",)
_WRITE_OPS: list[Literal["read", "write"]] = ["write"]


def filesystem_permissions() -> list[Any]:
    """Build the ``FilesystemPermission`` list for ``create_deep_agent``."""
    from deepagents.middleware.filesystem import FilesystemPermission

    return [
        FilesystemPermission(operations=_WRITE_OPS, paths=list(_READ_ONLY_PATTERNS), mode="deny")
    ]
