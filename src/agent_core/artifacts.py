"""Artifact discovery: which files did a run leave in its working folder?

Every unbound conversation works in the workspace's ``default`` folder, and a
conversation bound to a project works in that project's directory (see
:mod:`agent_core.runtime.paths`). Either way a run's deliverables are the files
it created there, discovered two ways:

- **Explicit claim** (preferred): a tool that produces files records them via
  :func:`register_artifact` as they are written, so nothing depends on timing
  heuristics.
- **Fallback scan**: :func:`scan_run_artifacts` walks the root for files
  modified since the run started, used for live runs that have no manifest yet.

The download endpoint re-resolves and rejects anything that escapes the
workspace (absolute paths, ``..`` traversal, symlink escapes, dotfiles).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_core.config.settings import Settings, get_settings
from agent_core.workspace.layout import default_root

MAX_ARTIFACTS = 200

# Directory under a working root that never holds deliverables: ``uploads/`` is
# where a conversation's mirrored attachments live. Excluded from the scan.
_NON_ARTIFACT_DIRS: frozenset[str] = frozenset({"uploads"})


def default_workspace_root(settings: Settings | None = None) -> Path:
    """The ``default`` working folder every unbound conversation uses."""
    resolved = settings or get_settings()
    return default_root(Path(resolved.workspace_dir))


def scan_workspace_artifacts(
    workspace: Path,
    *,
    since_ts: float,
    limit: int = MAX_ARTIFACTS,
    skip_dirs: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Return ``[{path, size, mtime}]`` for files modified after ``since_ts``.

    Paths are workspace-relative (portable across hosts — a run started on
    the server can be inspected from any LAN browser later). ``mtime`` is the
    file's modification time as an ISO string so the console can show when the
    artifact appeared. Hidden entries (dotfiles) and top-level ``skip_dirs``
    are skipped.
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
        parts = Path(rel).parts
        if any(part.startswith(".") for part in parts):
            continue
        if parts and parts[0] in skip_dirs:
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


def scan_run_artifacts(
    root: Path, *, since_ts: float, limit: int = MAX_ARTIFACTS
) -> list[dict[str, Any]]:
    """Artifacts of one run, bounded to ``root`` (shared workspace or project).

    ``skills/`` and ``uploads/`` are excluded: a skill the agent edited is a
    capability, not a deliverable, and an upload may belong to another
    conversation sharing the same root.
    """
    return scan_workspace_artifacts(
        root, since_ts=since_ts, limit=limit, skip_dirs=_NON_ARTIFACT_DIRS
    )


def register_artifact(
    root: Path, task_id: str, path: Path, *, limit: int = MAX_ARTIFACTS
) -> None:
    """Mark ``path`` as an artifact of ``task_id`` produced under filesystem ``root``.

    ``root`` is the run's working root (the shared workspace, or a bound project
    directory); ``task_id`` is the logical claimant, so claims stay per-run even
    when conversations share one root. ``path`` must live inside ``root``. The
    claim is in-memory only — it is persisted when the run finishes (the runtime
    folds all claims into ``run.metadata["artifacts"]``). The record carries the
    explicit contract (guide R8): a stable ``artifact_id``, ``path``, ``size``,
    ``mime_type`` and a content ``sha256``, so a download can be verified
    against the manifest instead of trusting a directory scan.
    """
    resolved_root = root.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(resolved_root):
        return  # outside the root: not claimable as an artifact
    if not resolved.is_file():
        return
    rel = resolved.relative_to(resolved_root).as_posix()
    claims = _CLAIMS.setdefault(task_id, [])
    if any(c["path"] == rel for c in claims):
        return
    if len(claims) >= limit:
        return
    stat = resolved.stat()
    claims.append(
        {
            "artifact_id": f"{task_id}:{rel}",
            "path": rel,
            "size": stat.st_size,
            "mtime": _iso_mtime(stat.st_mtime),
            "mime_type": guess_media_type(resolved),
            "sha256": _sha256(resolved),
        }
    )


def _sha256(path: Path) -> str:
    """Streaming content hash of ``path`` (empty string when unreadable)."""
    import hashlib

    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(65536):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def enrich_artifact(
    record: dict[str, Any], root: Path, *, task_id: str, run_id: str | None = None
) -> dict[str, Any]:
    """Complete an artifact record so it satisfies the explicit contract (R8).

    Directory scans produce only ``{path,size,mtime}``; nothing in production
    calls :func:`register_artifact`, so every artifact used to reach the console
    without an id/mime/hash. This fills the missing fields in place from the
    on-disk file, giving every artifact the same contract regardless of how it
    was discovered.
    """
    record.setdefault("task_id", task_id)
    if run_id is not None:
        record.setdefault("run_id", run_id)
    path = root / str(record["path"])
    if not path.is_file():
        return record
    stat = path.stat()
    record.setdefault("artifact_id", f"{task_id}:{record['path']}")
    record.setdefault("size", stat.st_size)
    record.setdefault("mime_type", guess_media_type(path))
    record.setdefault("sha256", _sha256(path))
    return record


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
