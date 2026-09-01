"""Built-in image tools: local txt2img generation and image viewing.

``generate_image`` calls an A1111/Forge-compatible ``/sdapi/v1/txt2img``
endpoint and saves the PNG under the workspace; ``view_image`` returns the
file as multimodal content blocks so a vision-capable model can actually
look at it (including at its own generations — the autonomy verification
loop can then judge visual results). Handlers are async and go through the
normal Tool Registry → Action Gate path like any other tool.
"""

from __future__ import annotations

import base64
import binascii
import time
from pathlib import Path
from typing import Any

import httpx

from agent_core.artifacts import register_artifact, task_workspace
from agent_core.config.settings import Settings
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import RegistryError, ToolError
from agent_core.registries import ToolRegistry
from agent_core.runtime.context import get_current_task_id

GENERATE_IMAGE_TOOL = "generate_image"
VIEW_IMAGE_TOOL = "view_image"

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _png_data_url(raw: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(raw).decode()}"


async def _txt2img(
    base_url: str,
    *,
    prompt: str,
    width: int,
    height: int,
    steps: int,
    cfg_scale: float,
) -> bytes:
    """Call the txt2img endpoint and return the first image's PNG bytes."""
    payload = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": cfg_scale,
    }
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/sdapi/v1/txt2img", json=payload
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise ToolError(
            f"Image service unreachable: {exc}", details={"base_url": base_url}
        ) from exc
    images = data.get("images") or []
    if not images:
        raise ToolError("Image service returned no images", details={"base_url": base_url})
    try:
        return base64.b64decode(images[0])
    except (binascii.Error, ValueError) as exc:
        raise ToolError("Image service returned invalid base64 data") from exc


# The local Forge backend (z_image_turbo) fails with HTTP 500 once the request
# area exceeds ~0.85MP. ``_clamp_area`` scales oversized requests down to a safe
# area (keeping the aspect ratio and an 8px-aligned latent) so the tool never
# trips the backend limit.
_MAX_IMAGE_AREA = 768 * 768


def _clamp_area(width: int, height: int) -> tuple[int, int]:
    """Clamp width/height so the pixel area stays within ``_MAX_IMAGE_AREA``."""
    if width * height <= _MAX_IMAGE_AREA:
        return width, height
    scale = (_MAX_IMAGE_AREA / (width * height)) ** 0.5
    w = max(8, int(width * scale) - int(width * scale) % 8)
    h = max(8, int(height * scale) - int(height * scale) % 8)
    if w * h > _MAX_IMAGE_AREA:
        w -= 8
    return w, h


def make_generate_image(settings: Settings) -> tuple[ToolDefinition, Any]:
    """Handler for ``generate_image``; saves the PNG under the workspace.

    Registered even when ``image_api_base_url`` is unset, but marked
    unavailable so the console can show the missing configuration.
    """
    base_url = settings.image_api_base_url
    workspace = Path(settings.workspace_dir)
    available = bool(base_url)

    async def generate_image(
        prompt: str,
        width: int = 512,
        height: int = 512,
        steps: int = 8,
        cfg_scale: float = 1.0,
    ) -> str:
        if not base_url:
            raise ToolError(
                "generate_image is not available: image_api_base_url is not configured",
                details={"tool": GENERATE_IMAGE_TOOL},
            )
        actual_w, actual_h = _clamp_area(width, height)
        clamped = (actual_w, actual_h) != (width, height)
        raw = await _txt2img(
            base_url or "",
            prompt=prompt,
            width=actual_w,
            height=actual_h,
            steps=steps,
            cfg_scale=cfg_scale,
        )
        # Write into the running task's private directory so every task owns
        # its outputs; the console then shows the image under that task. Uses
        # this handler's captured workspace, not the global settings.
        task_id = get_current_task_id()
        if task_id is not None:
            out_dir = task_workspace(workspace, task_id) / "images"
        else:
            out_dir = workspace / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = (out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-txt2img.png").resolve()
        path.write_bytes(raw)
        if task_id is not None:
            register_artifact(workspace, task_id, path)
        size_note = (
            f" (requested {width}x{height}, clamped to {actual_w}x{actual_h} "
            f"because the local image backend rejects larger sizes)"
            if clamped
            else f" ({actual_w}x{actual_h}, {steps} steps, cfg {cfg_scale})"
        )
        return (
            f"Image generated and saved to {path}{size_note}. "
            f"Call {VIEW_IMAGE_TOOL} with this path to inspect it."
        )

    definition = ToolDefinition(
        name=GENERATE_IMAGE_TOOL,
        description=(
            "Generate an image from a text prompt with the local txt2img model. "
            "Returns the saved file path; use view_image to inspect the result."
        ),
        source=ToolSource.PYTHON,
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "What the image should show"},
                "width": {"type": "integer", "description": "Width in pixels"},
                "height": {"type": "integer", "description": "Height in pixels"},
                "steps": {"type": "integer", "description": "Sampling steps"},
                "cfg_scale": {"type": "number", "description": "Prompt adherence scale"},
            },
            "required": ["prompt"],
        },
        metadata={
            "builtin": True,
            "endpoint": base_url,
            "timeout_seconds": 300,
            "available": available,
            "availability_reason": "" if available else "未配置 image_api_base_url",
        },
    )
    return definition, generate_image


def make_view_image(settings: Settings) -> tuple[ToolDefinition, Any]:
    """Handler for ``view_image``; returns multimodal content blocks."""

    async def view_image(path: str) -> list[dict[str, Any]]:
        file_path = Path(path).expanduser()
        if not file_path.is_absolute() and not file_path.exists():
            # Relative paths may be meant against the task directory (or, for
            # legacy callers, the workspace root), not the process CWD.
            task_id = get_current_task_id()
            if task_id is not None:
                base = task_workspace(Path(settings.workspace_dir), task_id)
            else:
                base = Path(settings.workspace_dir)
            if (base / file_path).exists():
                file_path = base / file_path
            else:
                file_path = Path(settings.workspace_dir) / file_path
        mime = _IMAGE_MIME.get(file_path.suffix.lower())
        if mime is None or not file_path.is_file():
            raise ToolError(
                f"No readable image at '{path}' (supported: {', '.join(sorted(_IMAGE_MIME))})",
                details={"path": str(file_path)},
            )
        raw = file_path.read_bytes()
        data_url = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        return [
            {
                "type": "text",
                "text": f"Image {file_path} ({len(raw)} bytes, {mime})",
            },
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

    definition = ToolDefinition(
        name=VIEW_IMAGE_TOOL,
        description=(
            "Look at a local image file (png/jpg/webp/gif). Returns the picture so "
            "you can visually inspect screenshots, photos, or your own generated images."
        ),
        source=ToolSource.PYTHON,
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path, or relative to the workspace dir",
                },
            },
            "required": ["path"],
        },
        metadata={"builtin": True, "available": True, "availability_reason": ""},
    )
    return definition, view_image


def register_builtin_tools(registry: ToolRegistry, settings: Settings) -> list[str]:
    """Register built-in tools; returns the names that were added.

    ``generate_image`` is registered even without an image endpoint so the
    console can show its availability state; the handler raises a clear error
    until ``image_api_base_url`` is configured.
    """
    registered: list[str] = []
    definition, handler = make_generate_image(settings)
    _register(registry, definition, handler)
    registered.append(definition.name)
    definition, handler = make_view_image(settings)
    _register(registry, definition, handler)
    registered.append(definition.name)
    return registered


def _register(registry: ToolRegistry, definition: ToolDefinition, handler: Any) -> None:
    try:
        registry.register(definition, handler)
    except RegistryError:
        # Definition already present (e.g. hydrated from the persistence store,
        # or a previous boot): refresh its metadata and re-attach the handler
        # so availability flags track the current configuration.
        registry.replace_with_handler(definition, handler)
