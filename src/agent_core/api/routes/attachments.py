"""Chat attachment upload: files dropped/pasted into the composer.

One endpoint, no task id: the client uploads first (getting workspace-relative
paths back), then sends them as the ``attachments`` field on task create or
follow-up. Files land under ``<workspace>/uploads/<uuid>/`` so they are unique
per batch and stay inside the workspace the agent's file tools are rooted on.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, UploadFile

from agent_core.api.attachments import save_attachments
from agent_core.config.settings import get_settings

router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.post("", response_model=list[dict[str, Any]])
async def upload_attachments(
    files: Annotated[list[UploadFile], File()],
) -> list[dict[str, Any]]:
    """Persist chat attachments; returns ``[{path, name, size}]``."""
    workspace = Path(get_settings().workspace_dir)
    batch_id = uuid.uuid4().hex[:12]
    uploads = [
        (file.filename or "attachment", await file.read())
        for file in files
    ]
    return save_attachments(workspace, batch_id, uploads)
