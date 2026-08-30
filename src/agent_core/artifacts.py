"""Artifact discovery: which files did a run leave in the workspace?

A run's "artifacts" are the workspace files created or modified after the run
started. This module is the single implementation shared by the runtime (which
records a manifest into ``run.metadata["artifacts"]`` at finish time) and the
API layer (which can re-scan for live runs).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

MAX_ARTIFACTS = 200


def scan_workspace_artifacts(
    workspace: Path, *, since_ts: float, limit: int = MAX_ARTIFACTS
) -> list[dict[str, Any]]:
    """Return ``[{path, size, mtime}]`` for files modified after ``since_ts``.

    Paths are workspace-relative (portable across hosts — a run started on
    the server can be inspected from any LAN browser later). ``mtime`` is the
    file's modification time as an ISO string so the console can show when the
    artifact appeared. Hidden entries (dotfiles) are skipped.
    """
    if not workspace.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for path in sorted(workspace.rglob("*")):
        if len(found) >= limit:
            break
        if not path.is_file():
            continue
        rel = path.relative_to(workspace).as_posix()
        if any(part.startswith(".") for part in Path(rel).parts):
            continue
        try:
            stat = path.stat()
        except OSError:  # raced with deletion — skip
            continue
        if stat.st_mtime >= since_ts:
            found.append(
                {
                    "path": rel,
                    "size": stat.st_size,
                    "mtime": _iso_mtime(stat.st_mtime),
                }
            )
    return found


def _iso_mtime(ts: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def artifact_abs_path(workspace: Path, relative: str) -> Path | None:
    """Resolve a workspace-relative artifact path; None unless safely inside.

    The workspace is the only place the API will serve files from: absolute
    paths, ``..`` traversal, symlink escapes and dotfiles are all rejected.
    """
    if not relative or relative.startswith(("/", "~")):
        return None
    candidate = (workspace / relative).resolve()
    try:
        candidate.relative_to(workspace.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    if any(part.startswith(".") for part in candidate.relative_to(workspace.resolve()).parts):
        return None
    return candidate


def guess_media_type(path: Path) -> str:
    import mimetypes

    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def inline_preview(media_type: str) -> bool:
    """Images render inline in the console; everything else downloads."""
    return media_type.startswith("image/") or media_type in {"text/plain", "application/json"}
