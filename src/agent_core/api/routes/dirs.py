"""Host-directory browsing for the console's folder picker.

The sidebar "add project" flow needs a native folder picker, but the browser
has no access to the server's filesystem — this read-only endpoint lets the
console walk the host tree and register a directory as a project. Projects
must still be registered by a human; nothing here writes to disk.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/dirs", tags=["dirs"])


class DirEntry(BaseModel):
    name: str
    path: str


class DirBrowseOut(BaseModel):
    path: str
    parent: str | None
    entries: list[DirEntry]


@router.get("/browse", response_model=DirBrowseOut)
def browse_dir(
    path: str = Query(
        default="", description="Absolute path to list; empty lists the home directory"
    ),
) -> DirBrowseOut:
    """List the immediate subdirectories of ``path`` (read-only, no follow of symlinks).

    Returns directories only — the picker only ever selects a folder.
    """
    try:
        root = Path(path).expanduser() if path else Path.home()
        root = root.resolve()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid path: {exc}") from exc

    if not root.exists():
        raise HTTPException(status_code=404, detail=f"path does not exist: {root}")
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"not a directory: {root}")

    entries: list[DirEntry] = []
    try:
        for child in sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if not child.is_dir():
                continue
            if child.is_symlink():
                continue
            try:
                entries.append(DirEntry(name=child.name, path=str(child.resolve())))
            except OSError:
                continue
    except OSError as exc:
        raise HTTPException(status_code=403, detail=f"cannot list directory: {exc}") from exc

    parent = None
    if root != root.parent:
        try:
            parent = str(root.parent.resolve())
        except OSError:
            parent = None
    return DirBrowseOut(path=str(root), parent=parent, entries=entries)
