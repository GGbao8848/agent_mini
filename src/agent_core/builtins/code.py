"""Built-in ``run_code`` tool: run a shell command inside the workspace.

This is what turns the agent from a talker into a maker: it can execute the
Python/shell scripts it writes (via the harness's file tools) — build a pptx,
run a data job, test code. The command runs with ``bash -lc`` in the
workspace dir, with a per-call timeout, and returns stdout/stderr so the
agent can iterate on failures.

Risk: MEDIUM (arbitrary code on the host machine, but confined to the
workspace cwd and below the approval risk floor — a personal avatar is
expected to run code without a human in the loop for every step).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_core.config.settings import Settings
from agent_core.domain.action import RiskLevel
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import RegistryError, ToolError
from agent_core.registries import ToolRegistry

RUN_CODE_TOOL = "run_code"
_MAX_OUTPUT_CHARS = 8000
_MAX_TIMEOUT_SECONDS = 900.0


def _run_command(command: str, workspace: Path, timeout: float) -> str:
    """Run one shell command synchronously; returns a formatted report."""
    try:
        process = subprocess.run(
            ["bash", "-lc", command],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired:
        raise ToolError(
            f"Command timed out after {timeout}s", details={"command": command[:200]}
        ) from None
    except OSError as exc:
        raise ToolError(f"Command failed to start: {exc}") from exc

    parts = [f"exit_code={process.returncode}"]
    if process.stdout:
        parts.append(f"stdout:\n{process.stdout[:_MAX_OUTPUT_CHARS]}")
    if process.stderr:
        parts.append(f"stderr:\n{process.stderr[:_MAX_OUTPUT_CHARS]}")
    if process.returncode != 0:
        parts.append("(command failed; fix the problem and try again)")
    return "\n".join(parts)


def make_run_code(settings: Settings) -> tuple[ToolDefinition, Any]:
    workspace = Path(settings.workspace_dir).resolve()
    # No resolve(): the venv python is usually a symlink to the system
    # interpreter, and resolving it would point PATH at the wrong bin dir.
    venv_bin = Path(sys.executable).parent

    async def run_code(command: str, timeout_seconds: float = 300.0) -> str:
        workspace.mkdir(parents=True, exist_ok=True)
        # The running interpreter's bin dir leads PATH so `python`/`uv` resolve
        # to this project's venv — agent scripts see the installed libraries.
        full_command = f'export PATH="{venv_bin}:$PATH"; {command}'
        capped = min(max(timeout_seconds, 1.0), _MAX_TIMEOUT_SECONDS)
        return await asyncio.to_thread(_run_command, full_command, workspace, capped)

    definition = ToolDefinition(
        name=RUN_CODE_TOOL,
        description=(
            f"Run a shell command inside the agent workspace ({workspace}) with bash -lc. "
            "Use it to execute scripts you wrote (this project's venv python is first on "
            "PATH, so installed libraries are importable), build artifacts, inspect "
            "files. Returns exit code + stdout/stderr; long output is truncated."
        ),
        risk_level=RiskLevel.MEDIUM,
        source=ToolSource.PYTHON,
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "timeout_seconds": {
                    "type": "number",
                    "description": (
                        "Max seconds for this command "
                        f"(default 300, max {int(_MAX_TIMEOUT_SECONDS)})"
                    ),
                },
            },
            "required": ["command"],
        },
        metadata={
            "builtin": True,
            "workspace": str(workspace),
            # Above the handler's own 900s cap so the handler's timeout wins.
            "timeout_seconds": 920.0,
        },
    )
    return definition, run_code


def register_builtin_tools(registry: ToolRegistry, settings: Settings) -> list[str]:
    """Register ``run_code``; workspace-backed code execution."""
    definition, handler = make_run_code(settings)
    try:
        registry.register(definition, handler)
    except RegistryError:
        registry.set_handler(definition.name, handler)
    return [definition.name]
