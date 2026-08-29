"""Artifact endpoints: list and download the files a run produced.

Everything is confined to the agent workspace (Phase 20/21): the manifest is
recorded by the runtime at run finish; the download endpoint re-resolves and
rejects anything that escapes the workspace directory.
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
    scan_workspace_artifacts,
)
from agent_core.config.settings import get_settings
from agent_core.errors.exceptions import RegistryError

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{run_id}", response_model=list[dict[str, Any]])
def list_artifacts(run_id: str, service: ServiceDep) -> list[dict[str, Any]]:
    """Files created/modified in the workspace by this run (workspace-relative)."""
    run = service.get_run(run_id)  # 404 for unknown runs
    manifest: list[dict[str, Any]] | None = run.metadata.get("artifacts")
    if manifest:
        return manifest
    # Live fallback: the run may still be executing (no manifest yet).
    settings = get_settings()
    workspace = Path(settings.workspace_dir)
    return scan_workspace_artifacts(workspace, since_ts=run.created_at.timestamp() - 2.0)


@router.get("/{run_id}/download")
def download_artifact(
    run_id: str, service: ServiceDep, path: str = Query(min_length=1)
) -> FileResponse:
    """Serve one artifact file: images/text inline, everything else as download."""
    service.get_run(run_id)
    settings = get_settings()
    workspace = Path(settings.workspace_dir).resolve()
    target = artifact_abs_path(workspace, path)
    if target is None:
        raise RegistryError(kind="artifact", key=path, detail="not found in workspace")
    media_type = guess_media_type(target)
    disposition = "inline" if inline_preview(media_type) else "attachment"
    return FileResponse(
        target,
        media_type=media_type,
        filename=target.name if disposition == "attachment" else None,
        headers={"Content-Disposition": f'{disposition}; filename="{target.name}"'},
    )
