"""Migrate pre-isolation artifacts into per-task directories.

Before task isolation (feat/artifact-storage), every task's outputs landed in
the shared workspace root (``images/``, ``ppt/``, ``album/``, stray full
``home/user/.../workspace/...`` paths) and the run manifest recorded
workspace-relative paths. The console now resolves downloads against
``workspace/tasks/<task_id>/``, so those old manifests must be re-homed:

1. resolve each recorded file on disk (tolerating the stray ``home/...`` prefix)
2. move it into ``workspace/tasks/<task_id>/<path>`` (deduping on collision)
3. rewrite the run's manifest path to the task-relative path and persist

Run once with the server stopped:  ``python scripts/migrate_artifacts.py``
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from agent_core.config.settings import get_settings

_WORKSPACE_MARKER = "/workspace/"


def _rel_from_stray(path: str) -> str:
    """Strip a ``home/.../workspace/`` prefix left by a stray cwd.

    Returns the path unchanged when it was already workspace-relative.
    """
    if _WORKSPACE_MARKER in path:
        return path.split(_WORKSPACE_MARKER, 1)[1]
    return path


def _dedupe(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    for i in range(2, 1000):
        candidate = dest.with_name(f"{stem}-{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot dedupe {dest}")


def migrate(workspace: Path, database: Path, *, dry_run: bool = False) -> int:
    """Move every recorded artifact into its task dir; returns files moved."""
    if dry_run:
        print(f"[dry-run] database={database} workspace={workspace}")
    con = sqlite3.connect(database)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    moved = 0
    # Per (task_id, rel) destination already chosen this pass, so several runs
    # of one task that reference the same file reuse one destination instead of
    # creating -2 copies.
    migrated: dict[tuple[str, str], str] = {}
    for row in cur.execute("SELECT id, data FROM runs"):
        data = json.loads(row["data"])
        artifacts = data.get("metadata", {}).get("artifacts") or []
        task_id = data.get("task_id")
        if not artifacts or not task_id:
            continue
        task_root = workspace / "tasks" / task_id
        changed = False
        for artifact in artifacts:
            raw = str(artifact["path"])
            rel = _rel_from_stray(raw)
            if rel.startswith("tasks/"):
                continue  # already migrated
            if (task_id, rel) in migrated:
                artifact["path"] = migrated[(task_id, rel)]
                changed = True
                continue
            source = (workspace / rel).resolve()
            if not source.is_file():
                print(f"  [skip] missing: {raw}")
                continue
            dest = task_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            # A different task may already hold this rel path (same-named file
            # in two conversations): dedupe, then remember for this task.
            dest = _dedupe(dest)
            if not dry_run:
                shutil.move(str(source), str(dest))
            rel_path = dest.relative_to(task_root).as_posix()
            artifact["path"] = rel_path
            migrated[(task_id, rel)] = rel_path
            changed = True
            moved += 1
        if changed and not dry_run:
            cur.execute(
                "UPDATE runs SET data=? WHERE id=?",
                (json.dumps(data, ensure_ascii=False), row["id"]),
            )
    if not dry_run:
        con.commit()
    con.close()
    return moved


if __name__ == "__main__":
    settings = get_settings()
    workspace = Path(settings.workspace_dir)
    db_url = settings.database_url or "sqlite:///./agent_core.db"
    database = Path(db_url.replace("sqlite:///", ""))
    count = migrate(workspace, database, dry_run="--dry-run" in __import__("sys").argv)
    print(f"migrated {count} files into {workspace / 'tasks'}")
