"""Built-in ``ensure_packages`` tool: check-then-install Python dependencies.

The agent-facing half of the host backend's package hygiene (see
:mod:`agent_core.builtins.hostenv`): the agent lists distributions it needs;
already-available ones are reported as usable and only the missing ones are
installed — into the agent-managed venv, never the system or the project env.
Registered only for the ``host`` sandbox backend; in the podman sandbox the
agent installs inside the container as usual (ephemeral, pip-cached).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from agent_core.builtins.hostenv import (
    check_packages,
    detect_host_tools,
    ensure_host_env,
    install_packages,
)
from agent_core.domain.action import RiskLevel
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import ToolInvalidArgumentsError

if TYPE_CHECKING:
    from agent_core.config.settings import Settings

ENSURE_PACKAGES_TOOL = "ensure_packages"


def make_ensure_packages(settings: Settings) -> tuple[ToolDefinition, Any]:
    probe = detect_host_tools()

    async def ensure_packages(packages: list[str]) -> str:
        if not packages:
            raise ToolInvalidArgumentsError(
                ENSURE_PACKAGES_TOOL,
                "packages must be a non-empty list of distribution names",
            )
        env_dir = await ensure_host_env(settings)
        status = await asyncio.to_thread(check_packages, env_dir, packages)
        missing = [name for name, ok in status.items() if not ok]
        lines = [
            f"{name}: already available"
            for name, ok in status.items()
            if ok
        ]
        if missing:
            await asyncio.to_thread(install_packages, env_dir, missing)
            lines.extend(f"{name}: newly installed into the agent env" for name in missing)
        installer = probe["installer"]
        return (
            f"installer={installer}, env={env_dir}\n" + "\n".join(lines)
            + "\nAll requested packages are importable now."
        )

    definition = ToolDefinition(
        name=ENSURE_PACKAGES_TOOL,
        description=(
            "Make Python packages importable: checks each distribution first and "
            "installs ONLY the missing ones into the agent's Python environment. "
            "Already-installed packages are never touched. Use this instead of raw "
            f"`pip install` when a script needs a library. Host tools available: "
            f"{', '.join(probe['available']) or '(none probed)'}."
        ),
        risk_level=RiskLevel.MEDIUM,
        source=ToolSource.PYTHON,
        input_schema={
            "type": "object",
            "properties": {
                "packages": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Distribution names, e.g. ['python-pptx', 'beautifulsoup4']",
                },
            },
            "required": ["packages"],
        },
        metadata={
            "builtin": True,
            "installer": probe["installer"],
            "host_tools": probe,
        },
    )
    return definition, ensure_packages
