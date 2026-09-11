"""Host-directory browsing + folder creation for the console's folder picker.

A working folder is a real host directory, but the browser has no access to the
server's filesystem — this endpoint pair lets the console walk the host tree and
create a new folder while picking. Browsing is read-only; creation makes exactly
one directory under an existing parent (one path component, no traversal), and
nothing else on disk is touched.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

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


class DirCreateRequest(BaseModel):
    parent: str = Field(min_length=1, description="Existing directory to create inside")
    name: str = Field(min_length=1, description="New folder name (a single path component)")


@router.post("", response_model=DirEntry, status_code=201)
def create_dir(payload: DirCreateRequest) -> DirEntry:
    """Create one subfolder under ``parent`` and return it (folder picker's "新建")."""
    name = payload.name.strip()
    # A folder name is one path component: no separators, no traversal, no
    # absolute path, no shell-isms. This is the only write this router does.
    if not name or name in {".", ".."} or name.startswith("~"):
        raise HTTPException(status_code=400, detail="文件夹名不合法")
    if "/" in name or "\\" in name or "\0" in name:
        raise HTTPException(status_code=400, detail="文件夹名不能包含路径分隔符")

    try:
        parent = Path(payload.parent).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid parent path: {exc}") from exc
    if not parent.is_dir():
        raise HTTPException(status_code=404, detail=f"parent is not a directory: {parent}")

    target = (parent / name).resolve()
    if not target.is_relative_to(parent):  # defensive: resolve() should prevent this
        raise HTTPException(status_code=400, detail="文件夹名不合法")
    try:
        target.mkdir()
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"文件夹已存在：{name}") from exc
    except OSError as exc:
        raise HTTPException(status_code=403, detail=f"无法创建文件夹：{exc}") from exc
    return DirEntry(name=name, path=str(target))
