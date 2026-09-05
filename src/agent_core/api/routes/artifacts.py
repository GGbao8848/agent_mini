"""Artifact endpoints: list and download the files a run produced.

Everything is confined to the agent workspace (Phase 20/21): the manifest is
recorded by the runtime at run finish; the download endpoint re-resolves and
rejects anything that escapes the workspace directory. Paths in the manifest
are task-relative (they live under ``workspace/tasks/<task_id>/``), so the
download URL is ``<run_id>/download?path=<task-relative-path>``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from agent_core.api.deps import ServiceDep
from agent_core.artifacts import (
    artifact_abs_path,
    guess_media_type,
    inline_preview,
    scan_task_artifacts,
)
from agent_core.config.settings import get_settings
from agent_core.errors.exceptions import RegistryError

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _task_root(service: ServiceDep, task_id: str) -> Path:
    """The directory holding a conversation's artifacts (project dir if bound)."""
    return service.task_root(task_id) or (
        Path(get_settings().workspace_dir) / "tasks" / task_id
    )


@router.get("/{run_id}", response_model=list[dict[str, Any]])
def list_artifacts(run_id: str, service: ServiceDep) -> list[dict[str, Any]]:
    """Files created/modified by this run, task-relative (inside its task dir)."""
    run = service.get_run(run_id)  # 404 for unknown runs
    manifest: list[dict[str, Any]] | None = run.metadata.get("artifacts")
    if manifest:
        return manifest
    # Live fallback: the run may still be executing (no manifest yet). Scan
    # only the run's own task root so other tasks never leak in.
    return scan_task_artifacts(
        Path(get_settings().workspace_dir),
        run.task_id,
        since_ts=run.created_at.timestamp() - 2.0,
        root=_task_root(service, run.task_id),
    )


@router.get("/{run_id}/download")
def download_artifact(
    run_id: str, service: ServiceDep, path: str = Query(min_length=1)
) -> FileResponse:
    """Serve one artifact file: images/text inline, everything else as download."""
    run = service.get_run(run_id)
    task_root = _task_root(service, run.task_id).resolve()
    target = artifact_abs_path(task_root, path)
    if target is None:
        raise RegistryError(
            kind="artifact", key=path, detail="not found in workspace"
        )
    media_type = guess_media_type(target)
    # Starlette emits an RFC 5987 filename* for non-ASCII names (Chinese
    # filenames are the norm here) — never build the header by hand, an
    # encoded latin-1 header raises UnicodeEncodeError and 500s the download.
    return FileResponse(
        target,
        media_type=media_type,
        filename=target.name,
        content_disposition_type="inline" if inline_preview(media_type) else "attachment",
    )


_PREVIEW_TEXT_SUFFIXES = frozenset(
    {".md", ".txt", ".json", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css",
     ".csv", ".yaml", ".yml", ".toml", ".sh", ".bash", ".log", ".xml", ".svg", ".ini", ".cfg"}
)
_PREVIEW_MAX_BYTES = 512_000
_PREVIEW_MAX_CHARS = 200_000


@router.get("/{run_id}/preview")
def preview_artifact(
    run_id: str, service: ServiceDep, path: str = Query(min_length=1)
) -> dict[str, Any]:
    """Content payload for the console's right-hand preview panel.

    Images return ``kind=image`` (the browser renders the download URL); text
    files return decoded content (Markdown renders as Markdown in the panel);
    anything else is ``kind=binary`` with a download link instead.
    """
    run = service.get_run(run_id)
    task_root = _task_root(service, run.task_id).resolve()
    target = artifact_abs_path(task_root, path)
    if target is None:
        raise RegistryError(
            kind="artifact", key=path, detail="not found in workspace"
        )
    media_type = guess_media_type(target)
    size = target.stat().st_size
    suffix = target.suffix.lower()
    is_text = media_type.startswith("text/") or suffix in _PREVIEW_TEXT_SUFFIXES
    if suffix == ".svg":
        is_text, media_type = True, "text/plain"  # never render uploaded SVG as image
    if is_text and size <= _PREVIEW_MAX_BYTES:
        content = target.read_text("utf-8", errors="replace")[:_PREVIEW_MAX_CHARS]
        return {
            "kind": "text", "media_type": media_type, "size": size,
            "path": path, "content": content,
        }
    if media_type.startswith("image/"):
        return {"kind": "image", "media_type": media_type, "size": size, "path": path}
    return {"kind": "binary", "media_type": media_type, "size": size, "path": path}
