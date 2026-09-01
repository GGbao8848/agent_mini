"""Artifact discovery: which files did a task leave in the workspace?

Artifacts live under per-task directories — ``<workspace>/tasks/<task_id>/`` —
so a conversation's deliverables are isolated from every other task and from
the shared root. Two mechanisms feed the console's 产物 panel:

- **Explicit claim** (preferred): tools that produce files (``generate_image``,
  ``run_code``) record them via :func:`register_artifact` as they are written,
  so nothing depends on timing heuristics.
- **Fallback scan**: :func:`scan_task_artifacts` walks a task's own directory
  for files modified since a timestamp, used for live runs that have no
  manifest yet.

The download endpoint re-resolves and rejects anything that escapes the
workspace (absolute paths, ``..`` traversal, symlink escapes, dotfiles).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_core.config.settings import Settings, get_settings

MAX_ARTIFACTS = 200

_TASKS_DIR_NAME = "tasks"


def task_dir_name(task_id: str) -> str:
    """The on-disk subdirectory that isolates one conversation's artifacts."""
    return _TASKS_DIR_NAME


def task_workspace(workspace: Path, task_id: str) -> Path:
    """The private directory for ``task_id`` (created on demand)."""
    root = workspace / _TASKS_DIR_NAME / task_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_task_workspace(task_id: str) -> Path:
    """The current task's directory from the app settings (created on demand)."""
    return task_workspace(Path(get_settings().workspace_dir), task_id)


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


def scan_task_artifacts(
    workspace: Path, task_id: str, *, since_ts: float, limit: int = MAX_ARTIFACTS
) -> list[dict[str, Any]]:
    """Artifacts of one task only: scan its own directory, skip the shared root.

    This is what keeps concurrent tasks from bleeding into each other's panel:
    the window is bounded by the task's own directory, not the whole workspace.
    """
    root = workspace / _TASKS_DIR_NAME / task_id
    return scan_workspace_artifacts(root, since_ts=since_ts, limit=limit)


def register_artifact(
    workspace: Path, task_id: str, path: Path, *, limit: int = MAX_ARTIFACTS
) -> None:
    """Explicitly mark ``path`` as an artifact of ``task_id``.

    ``path`` must live inside the task's private directory. The claim is kept
    in-memory only — it is persisted when the run finishes (the runtime folds
    all claims into ``run.metadata["artifacts"]``). ``limit`` is a soft cap so
    a runaway producer cannot bloat the manifest.
    """
    root = (workspace / _TASKS_DIR_NAME / task_id).resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        return  # outside the task dir: not claimable as a task artifact
    if not resolved.is_file():
        return
    rel = resolved.relative_to(root).as_posix()
    claims = _CLAIMS.setdefault(task_id, [])
    if any(c["path"] == rel for c in claims):
        return
    if len(claims) >= limit:
        return
    claims.append(
        {
            "path": rel,
            "size": resolved.stat().st_size,
            "mtime": _iso_mtime(resolved.stat().st_mtime),
        }
    )


def claimed_artifacts(task_id: str) -> list[dict[str, Any]]:
    """The explicitly claimed (not yet persisted) artifacts for ``task_id``."""
    return list(_CLAIMS.get(task_id, []))


def clear_claims(task_id: str) -> None:
    """Drop in-memory artifact claims for ``task_id`` (run finished, persisted)."""
    _CLAIMS.pop(task_id, None)


# In-memory claim store: keyed by task_id, drained into run.metadata at run
# finish. Process-local like the run registry — restored runs have their
# manifest persisted already.
_CLAIMS: dict[str, list[dict[str, Any]]] = {}


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


def _task_workspace_for(settings: Settings, task_id: str) -> Path:
    """Task directory under a given settings workspace (helper for tests)."""
    return task_workspace(Path(settings.workspace_dir), task_id)
