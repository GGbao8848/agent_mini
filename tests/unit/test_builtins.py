"""Tests for built-in tools (image generation + viewing) and their registration."""

import base64
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from agent_core.builtins.image import (
    GENERATE_IMAGE_TOOL,
    VIEW_IMAGE_TOOL,
    _clamp_area,
    make_generate_image,
    make_view_image,
    register_builtin_tools,
)
from agent_core.config.settings import Settings
from agent_core.errors.exceptions import ToolError
from agent_core.registries import ToolRegistry


def _solid_png(rgb: tuple[int, int, int], size: int = 8) -> bytes:
    row = b"\x00" + bytes(rgb) * size
    raw = row * size

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def image_settings(tmp_path: Path, *, with_image_api: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        workspace_dir=str(tmp_path / "workspace"),
        image_api_base_url="http://10.10.10.169:18542" if with_image_api else None,
    )


class TestGenerateImage:
    async def test_saves_png_and_reports_path(self, tmp_path: Path, monkeypatch: Any) -> None:
        png = _solid_png((30, 200, 60))
        captured: dict[str, Any] = {}

        async def fake_txt2img(base_url: str, **payload: Any) -> bytes:
            captured["base_url"] = base_url
            captured.update(payload)
            return png

        monkeypatch.setattr("agent_core.builtins.image._txt2img", fake_txt2img)
        _, handler = make_generate_image(image_settings(tmp_path))

        result = await handler(prompt="a red panda", width=256, height=256)

        assert captured["base_url"] == "http://10.10.10.169:18542"
        assert captured["prompt"] == "a red panda"
        assert captured["width"] == 256
        saved = Path(result.split("saved to ")[1].split(" ")[0])
        assert saved.read_bytes() == png
        assert VIEW_IMAGE_TOOL in result

    async def test_oversized_request_is_clamped(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """The local backend 500s above ~0.85MP — clamp 1024x1024 down."""
        captured: dict[str, Any] = {}

        async def fake_txt2img(base_url: str, **payload: Any) -> bytes:
            captured.update(payload)
            return _solid_png((10, 20, 30))

        monkeypatch.setattr("agent_core.builtins.image._txt2img", fake_txt2img)
        _, handler = make_generate_image(image_settings(tmp_path))

        result = await handler(prompt="big scene", width=1024, height=1024)

        assert captured["width"] * captured["height"] <= 768 * 768
        assert captured["width"] % 8 == 0 and captured["height"] % 8 == 0
        assert "clamped" in result
        saved = Path(result.split("saved to ")[1].split(" ")[0])
        assert saved.read_bytes() == _solid_png((10, 20, 30))

    def test_clamp_area_keeps_safe_aligned_bounds(self) -> None:
        for w, h in [(512, 512), (768, 768), (896, 896), (1024, 1024), (1920, 1080), (1536, 1024)]:
            cw, ch = _clamp_area(w, h)
            assert cw * ch <= 768 * 768
            assert cw % 8 == 0 and ch % 8 == 0
        # Safe sizes pass through untouched.
        assert _clamp_area(512, 512) == (512, 512)
        assert _clamp_area(768, 768) == (768, 768)

    async def test_unreachable_service_raises_tool_error(self, tmp_path: Path) -> None:
        # Port 1 on localhost: connection refused immediately, no real network.
        settings = Settings(
            _env_file=None,
            workspace_dir=str(tmp_path / "workspace"),
            image_api_base_url="http://127.0.0.1:1",
        )
        _, handler = make_generate_image(settings)
        with pytest.raises(ToolError):
            await handler(prompt="anything")

    async def test_gated_path_applies_handler_defaults(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Regression: gated tools used to receive None for omitted optionals."""
        from agent_core.domain.agent import AgentSpec
        from agent_core.domain.task import Run, RunStatus
        from agent_core.registries import AgentRegistry, SkillRegistry
        from agent_core.runtime.runtime import AgentRuntime

        captured: dict[str, Any] = {}

        async def fake_txt2img(base_url: str, **payload: Any) -> bytes:
            captured.update(payload)
            return _solid_png((0, 0, 0))

        monkeypatch.setattr("agent_core.builtins.image._txt2img", fake_txt2img)
        settings = image_settings(tmp_path)
        registry = ToolRegistry()
        register_builtin_tools(registry, settings)
        agents = AgentRegistry()
        agents.register(
            AgentSpec(id="helper", name="Helper", tools=[GENERATE_IMAGE_TOOL])
        )
        runtime = AgentRuntime(agents, registry, SkillRegistry())
        run = Run(task_id="t1", agent_id="helper")
        run.transition_to(RunStatus.RUNNING)

        result = await runtime.gate.execute(
            run=run, tool_name=GENERATE_IMAGE_TOOL, arguments={"prompt": "a cube"}
        )

        assert captured["width"] == 512 and captured["height"] == 512
        assert captured["steps"] == 8 and captured["cfg_scale"] == 1.0
        assert "512x512" in result


class TestViewImage:
    async def test_returns_text_and_image_blocks(self, tmp_path: Path) -> None:
        workspace = image_settings(tmp_path)
        _, handler = make_view_image(workspace)
        saved = Path(workspace.workspace_dir) / "pic.png"
        saved.parent.mkdir(parents=True)
        png = _solid_png((228, 40, 40))
        saved.write_bytes(png)

        blocks = await handler(path=str(saved))

        assert blocks[0]["type"] == "text"
        assert blocks[1]["type"] == "image_url"
        data_url = blocks[1]["image_url"]["url"]
        assert data_url.startswith("data:image/png;base64,")
        assert base64.b64decode(data_url.split(",", 1)[1]) == png

    async def test_relative_paths_resolve_against_workspace(self, tmp_path: Path) -> None:
        workspace = image_settings(tmp_path)
        _, handler = make_view_image(workspace)
        saved = Path(workspace.workspace_dir) / "images" / "gen.png"
        saved.parent.mkdir(parents=True)
        saved.write_bytes(_solid_png((0, 0, 255)))

        blocks = await handler(path="images/gen.png")

        assert "gen.png" in blocks[0]["text"]

    async def test_unsupported_or_missing_file_raises(self, tmp_path: Path) -> None:
        _, handler = make_view_image(image_settings(tmp_path))
        with pytest.raises(ToolError):
            await handler(path="missing.png")
        text_file = Path(tmp_path) / "notes.txt"
        text_file.write_text("not an image")
        with pytest.raises(ToolError):
            await handler(path=str(text_file))


class TestRegistration:
    def test_view_image_always_registered_generate_image_needs_endpoint(
        self, tmp_path: Path
    ) -> None:
        registry = ToolRegistry()
        added = register_builtin_tools(registry, image_settings(tmp_path))

        assert GENERATE_IMAGE_TOOL in added
        assert VIEW_IMAGE_TOOL in added
        assert registry.get(GENERATE_IMAGE_TOOL).metadata.get("endpoint")

    def test_generate_image_registered_but_unavailable_without_endpoint(
        self, tmp_path: Path
    ) -> None:
        registry = ToolRegistry()
        added = register_builtin_tools(registry, image_settings(tmp_path, with_image_api=False))

        assert GENERATE_IMAGE_TOOL in added  # registered so the console can show it
        definition = registry.get(GENERATE_IMAGE_TOOL)
        assert definition.metadata["available"] is False
        assert "image_api_base_url" in definition.metadata["availability_reason"]
        assert registry.get(VIEW_IMAGE_TOOL).metadata["available"] is True

    def test_reregistration_reattaches_handler(self, tmp_path: Path) -> None:
        settings = image_settings(tmp_path)
        registry = ToolRegistry()
        register_builtin_tools(registry, settings)
        # Simulate hydration from the persistence store: definition without a handler.
        registry._handlers.pop(GENERATE_IMAGE_TOOL)  # noqa: SLF001

        register_builtin_tools(registry, settings)

        registry.handler_for(GENERATE_IMAGE_TOOL)  # executable is back


class TestRunCode:
    def test_registered_via_register_builtin_tools(self, tmp_path: Path) -> None:
        from agent_core.builtins import register_builtin_tools

        settings = image_settings(tmp_path)
        registry = ToolRegistry()
        added = register_builtin_tools(registry, settings)

        assert "run_code" in added
        definition = registry.get("run_code")
        assert definition.risk_level.value == "medium"
        assert "workspace" in definition.description

    async def test_run_code_reports_exit_and_output(self, tmp_path: Path) -> None:
        from agent_core.builtins.code import make_run_code

        _, handler = make_run_code(image_settings(tmp_path))

        ok = await handler(command="echo hello-from-workspace")
        assert "exit_code=0" in ok and "hello-from-workspace" in ok

        failed = await handler(command="exit 3")
        assert "exit_code=3" in failed and "command failed" in failed

        # The venv python (not the system one) is what resolves first on PATH.
        venv_python = await handler(
            command="python -c 'import sys; print(sys.prefix != sys.base_prefix)'"
        )
        assert "exit_code=0" in venv_python and "True" in venv_python
