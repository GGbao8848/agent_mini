"""A filesystem backend that enforces read-only logical prefixes.

``FilesystemPermission`` (see :mod:`.permissions`) is checked by DeepAgents'
filesystem *middleware* — the tool wrappers. That protects ``write_file`` &
friends, but any code path that reaches the backend directly (a future tool,
a test, an internal helper) would slip past. This wrapper re-asserts the same
boundary at the data layer, so ``/inputs/**`` and ``/skills/**`` are immutable
no matter who calls in.

Write-ish operations on a read-only prefix return the backend's own error
result (``WriteResult`` / ``EditResult`` / ``DeleteResult`` /
``FileUploadResponse``) — callers see a normal "permission denied", not an
exception. Everything else delegates untouched.
"""

from __future__ import annotations

from typing import Any, cast

from deepagents.backends.protocol import (
    DeleteResult,
    EditResult,
    FileUploadResponse,
    WriteResult,
)

READ_ONLY_PREFIXES: tuple[str, ...] = ("/inputs", "/skills")
_WRITE_OP_ERROR = "permission denied: path is read-only"


def is_read_only(path: str) -> bool:
    """True when ``path`` falls under a read-only logical mount."""
    normalized = "/" + path.lstrip("/")
    return any(
        normalized == prefix or normalized.startswith(prefix + "/")
        for prefix in READ_ONLY_PREFIXES
    )


class BoundaryBackend:
    """Delegate to ``inner`` but deny writes under the read-only prefixes."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def write(self, path: str, content: str) -> WriteResult:
        if is_read_only(path):
            return WriteResult(error=_WRITE_OP_ERROR, path=path)
        return cast(WriteResult, self._inner.write(path, content))

    async def awrite(self, path: str, content: str) -> WriteResult:
        if is_read_only(path):
            return WriteResult(error=_WRITE_OP_ERROR, path=path)
        return cast(WriteResult, await self._inner.awrite(path, content))

    def edit(self, path: str, *args: Any, **kwargs: Any) -> EditResult:
        if is_read_only(path):
            return EditResult(error=_WRITE_OP_ERROR, path=path)
        return cast(EditResult, self._inner.edit(path, *args, **kwargs))

    async def aedit(self, path: str, *args: Any, **kwargs: Any) -> EditResult:
        if is_read_only(path):
            return EditResult(error=_WRITE_OP_ERROR, path=path)
        return cast(EditResult, await self._inner.aedit(path, *args, **kwargs))

    def delete(self, path: str) -> DeleteResult:
        if is_read_only(path):
            return DeleteResult(error=_WRITE_OP_ERROR, path=path)
        return cast(DeleteResult, self._inner.delete(path))

    async def adelete(self, path: str) -> DeleteResult:
        if is_read_only(path):
            return DeleteResult(error=_WRITE_OP_ERROR, path=path)
        return cast(DeleteResult, await self._inner.adelete(path))

    def upload_files(self, files: Any) -> list[FileUploadResponse]:
        out: list[FileUploadResponse] = []
        for entry in files:
            if is_read_only(entry[0]):
                out.append(FileUploadResponse(path=entry[0], error="permission_denied"))
            else:
                out.extend(self._inner.upload_files([entry]))
        return out

    async def aupload_files(self, files: Any) -> list[FileUploadResponse]:
        out: list[FileUploadResponse] = []
        for entry in files:
            if is_read_only(entry[0]):
                out.append(FileUploadResponse(path=entry[0], error="permission_denied"))
            else:
                out.extend(await self._inner.aupload_files([entry]))
        return out

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
