"""Chat attachment upload: safe persistence of files the user drops in the box.

The console composer lets a user drag files / paste screenshots to hand them
to the agent. Files land under ``<workspace>/uploads/<task_id>/`` with a
sanitized basename (never overwriting, deduped on collision). ``.zip``
archives are extracted in place so the agent can read every member directly
with its file tools; every other file is stored as-is. Only the ``uploads``
subtree is writable this way — a malformed name can never escape it.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any

from agent_core.errors.exceptions import ToolError

_MAX_ATTACHMENT_BYTES = 64 * 1024 * 1024  # 64 MiB per file
_MAX_ATTACHMENTS = 20

_SAFE_BASENAME = re.compile(r"^[^/\\]*$")


def save_attachments(
    workspace: Path,
    task_id: str,
    uploads: list[tuple[str, bytes]],
    *,
    max_bytes: int = _MAX_ATTACHMENT_BYTES,
    max_count: int = _MAX_ATTACHMENTS,
) -> list[dict[str, Any]]:
    """Persist uploaded files for ``task_id``; returns ``[{path, name, size}]``.

    ``uploads`` is ``[(filename, bytes)]`` as parsed from the multipart form.
    Each file is written to ``<workspace>/uploads/<task_id>/<basename>``; a
    ``.zip`` archive is extracted under ``<workspace>/uploads/<task_id>/<name>/``
    (members become sibling attachments). A collision gets a numeric suffix so
    nothing is ever silently overwritten. Paths are workspace-relative and
    ``..``-free by construction.
    """
    if not uploads:
        return []
    if len(uploads) > max_count:
        raise ToolError(
            f"Too many attachments ({len(uploads)}); at most {max_count} per message",
            details={"tool": "chat_attachment"},
        )
    target_dir = workspace / "uploads" / task_id
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, Any]] = []
    for filename, content in uploads:
        if not filename or not _SAFE_BASENAME.match(filename):
            raise ToolError(
                f"Unsafe attachment filename: {filename!r}",
                details={"tool": "chat_attachment"},
            )
        if len(content) > max_bytes:
            raise ToolError(
                f"Attachment '{filename}' exceeds {max_bytes // (1024 * 1024)} MiB",
                details={"tool": "chat_attachment", "file": filename},
            )
        if filename.lower().endswith(".zip"):
            saved.extend(_save_zip(workspace, target_dir, filename, content))
        else:
            target = _dedupe(target_dir / filename)
            target.write_bytes(content)
            rel = target.relative_to(workspace).as_posix()
            saved.append({"path": rel, "name": target.name, "size": len(content)})
    return saved


def _save_zip(
    workspace: Path, target_dir: Path, filename: str, content: bytes
) -> list[dict[str, Any]]:
    """Extract ``content`` (a zip) under ``target_dir/<name>/``; zip-slip safe.

    Returns one ``{path, name, size}`` per member, paths workspace-relative.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ToolError(
            f"Attachment '{filename}' is not a valid zip archive",
            details={"tool": "chat_attachment", "file": filename},
        ) from exc
    members = [info for info in zf.infolist() if not info.is_dir()]
    if not members:
        raise ToolError(
            f"Attachment '{filename}' is an empty zip archive",
            details={"tool": "chat_attachment", "file": filename},
        )
    # A zip bomb guard: refuse to unpack past the per-attachment byte budget.
    total = sum(info.file_size for info in members)
    if total > _MAX_ATTACHMENT_BYTES:
        raise ToolError(
            f"Attachment '{filename}' unpacks to more than "
            f"{_MAX_ATTACHMENT_BYTES // (1024 * 1024)} MiB",
            details={"tool": "chat_attachment", "file": filename},
        )

    stem = Path(filename).stem
    root = _dedupe(target_dir / stem)
    saved: list[dict[str, Any]] = []
    for info in members:
        name = info.filename
        parts = Path(name).parts
        if not name or ".." in parts or name.startswith("/") or (
            len(parts) > 1 and parts[0] in ("..", "")
        ):
            raise ToolError(
                f"Attachment '{filename}' contains an unsafe path: {name}",
                details={"tool": "chat_attachment"},
            )
        dest = (root / name).resolve()
        if not dest.is_relative_to(root.resolve()):
            raise ToolError(
                f"Attachment '{filename}' contains an unsafe path: {name}",
                details={"tool": "chat_attachment"},
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(dest, "wb") as out:
            while chunk := src.read(64 * 1024):
                out.write(chunk)
        saved.append(
            {
                "path": dest.relative_to(workspace.resolve()).as_posix(),
                "name": name,
                "size": info.file_size,
            }
        )
    return saved


def _dedupe(path: Path) -> Path:
    """Return ``path``, or ``name-2.ext`` etc. if the plain name is taken."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}-{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise ToolError(f"Cannot store attachment '{path.name}'", details={"tool": "chat_attachment"})


def attachment_notes(paths: list[str]) -> str:
    """Render the attachment list as a hint the agent can act on.

    Appended to the user message so the agent knows which files were handed to
    it and that they are readable through its workspace-rooted file tools.
    """
    if not paths:
        return ""
    lines = ["", "本消息附带以下文件（在 workspace 内，用文件工具读取）："]
    for path in paths:
        lines.append(f"- {path}")
    return "\n".join(lines)
