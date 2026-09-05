"""Built-in ``run_code`` tool: run a shell command inside the workspace.

This is what turns the agent from a talker into a maker: it can execute the
Python/shell scripts it writes (via the harness's file tools) — build a pptx,
run a data job, test code. The command runs with ``bash -lc`` in the
workspace dir, with a per-call timeout, and returns stdout/stderr so the
agent can iterate on failures.

Execution backends (``AGENT_CORE_SANDBOX``):

- ``host``   : on the host, but with package hygiene — PATH points at the
               agent-managed venv (system site-packages visible, so host
               libraries are reused, and agent installs land in the venv,
               never the system). Commands that drive a system package
               manager (apt/brew/...) are upgraded to human approval by an
               argument-level risk rule. ``none`` is a deprecated alias.
- ``podman`` : inside a rootless container with only the workspace mounted —
               the host's secrets, SSH keys and the rest of the filesystem are
               out of reach, and memory/CPU/pids are capped. The workspace is
               the single exchange point between the agent and the sandbox.

Risk: MEDIUM either way (workspace-confined, below the approval risk floor —
a personal avatar is expected to run code without a human in the loop); the
system-install rule can raise individual host commands to approval.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from agent_core.builtins.hostenv import detect_host_tools, ensure_host_env
from agent_core.builtins.packages import ENSURE_PACKAGES_TOOL, make_ensure_packages
from agent_core.config.settings import Settings
from agent_core.domain.action import RiskLevel
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import RegistryError, ToolError
from agent_core.registries import ToolRegistry
from agent_core.runtime.paths import current_task_dir

RUN_CODE_TOOL = "run_code"
_MAX_OUTPUT_CHARS = 8000
_MAX_TIMEOUT_SECONDS = 900.0

# Host backend: commands that reach the system package manager need a human.
# Same pattern is used by the argument-level approval rule below. Lookarounds
# instead of \b so dash flags (-S) match while "--installed" does not; false
# positives land in the approval queue, which is the safe side.
_SYSTEM_INSTALL_RE = re.compile(
    r"\b(?:apt|apt-get|aptitude|dnf|yum|zypper|pacman|apk|brew|port|"
    r"choco|winget|scoop|emerge|snap|flatpak|nix-env)\s[^;&|]*"
    r"(?:(?<![\w-])(?:install|add|in|rm|remove|upgrade|full-upgrade)(?![\w-])"
    r"|(?<![\w-])-[SRKB](?![\w-]))",
    re.IGNORECASE,
)


def is_system_install(command: str) -> bool:
    """True when the command drives a system package manager install/change."""
    return _SYSTEM_INSTALL_RE.search(command) is not None

_PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy")


def _proxy_env() -> dict[str, str]:
    """Proxy env vars worth passing through to the container (pip etc.)."""
    return {var: value for var in _PROXY_ENV_VARS if (value := os.environ.get(var))}


def build_sandbox_command(
    workspace: Path, settings: Settings, command: str, timeout: float
) -> list[str]:
    """Assemble the ``podman run`` argv for one command (pure, unit-testable)."""
    del timeout  # the host-side subprocess timeout is applied by the caller
    argv = [
        "podman", "run", "--rm",
        "--volume", f"{workspace}:/work",
        # Persistent pip cache across the ephemeral containers: ad-hoc installs
        # of packages outside the prebuilt toolbox are fast on repeat calls.
        "--volume", "agent-core-pip-cache:/root/.cache/pip",
        "--workdir", "/work",
        "--memory", f"{settings.sandbox_memory_mb}m",
        "--cpus", str(settings.sandbox_cpus),
        "--pids-limit", str(settings.sandbox_pids_limit),
        "--pull", "never",
        # Host networking: the sandbox runs on the same LAN as the local model
        # / TTS services (10.10.10.146, 10.10.10.169), and a default bridge
        # container cannot route back to the host's own LAN IP — the agent's
        # curl to those services failed with connection refused. Security is
        # enforced by the filesystem (only workspace mounted), so sharing the
        # host netstack restores those reachable endpoints without widening
        # what the agent can read or write.
        "--network", "host",
    ]
    for var, value in _proxy_env().items():
        argv.extend(["--env", f"{var}={value}"])
    argv.extend([settings.sandbox_image, "bash", "-lc", command])
    return argv


def _run_host(command: str, workspace: Path, timeout: float) -> str:
    """Legacy backend: run directly on the host, workspace as cwd."""
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
    return _report(process.returncode, process.stdout, process.stderr)


def _run_podman(workspace: Path, settings: Settings, command: str, timeout: float) -> str:
    """Sandbox backend: run inside the rootless container."""
    argv = build_sandbox_command(workspace, settings, command, timeout)
    try:
        process = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except subprocess.TimeoutExpired:
        raise ToolError(
            f"Command timed out after {timeout}s", details={"command": command[:200]}
        ) from None
    except OSError as exc:
        raise ToolError(f"Command failed to start: {exc}") from exc
    if process.returncode == 125 and "no such image" in (process.stderr or "").lower():
        raise ToolError(
            f"Sandbox image '{settings.sandbox_image}' not found — build it with "
            "`scripts/sandbox_build.sh` or set AGENT_CORE_SANDBOX=none",
            details={"image": settings.sandbox_image},
        )
    return _report(process.returncode, process.stdout, process.stderr)


def _report(returncode: int, stdout: str, stderr: str) -> str:
    parts = [f"exit_code={returncode}"]
    if stdout:
        parts.append(f"stdout:\n{stdout[:_MAX_OUTPUT_CHARS]}")
    if stderr:
        parts.append(f"stderr:\n{stderr[:_MAX_OUTPUT_CHARS]}")
    if returncode != 0:
        parts.append("(command failed; fix the problem and try again)")
    return "\n".join(parts)


def make_run_code(settings: Settings) -> tuple[ToolDefinition, Any]:
    workspace = Path(settings.workspace_dir).resolve()
    sandboxed = settings.sandbox == "podman"
    probe = detect_host_tools() if not sandboxed else None

    async def run_code(command: str, timeout_seconds: float = 300.0) -> str:
        # Run inside the current task's working directory (project dir when
        # bound) so files it creates land where the task's 产物 scope reads
        # them. Uses this handler's captured workspace (not the global
        # settings) for the default root so a task-context run always targets
        # the right workspace.
        cwd = current_task_dir(workspace)
        cwd.mkdir(parents=True, exist_ok=True)
        capped = min(max(timeout_seconds, 1.0), _MAX_TIMEOUT_SECONDS)
        if sandboxed:
            return await asyncio.to_thread(_run_podman, cwd, settings, command, capped)
        # Host backend: put the agent-managed venv first on PATH — its python
        # sees host site-packages (nothing the host already has is installed
        # twice) while agent installs land in the venv, not the system or the
        # project env. Created on first use, reused after.
        env_dir = await ensure_host_env(settings)
        env_bin = str(env_dir / "bin")
        full_command = f'export PATH="{env_bin}:$PATH"; {command}'
        return await asyncio.to_thread(_run_host, full_command, cwd, capped)

    if sandboxed:
        backend_note = (
            "Runs inside a rootless podman sandbox: only this workspace is "
            "mounted, with the prebuilt toolbox libraries installed."
        )
        metadata_extra: dict[str, Any] = {}
    else:
        backend_note = (
            "Runs on the host with the agent-managed Python environment: host "
            "site-packages are importable directly, and missing libraries should "
            f"be requested via {ENSURE_PACKAGES_TOOL} instead of raw pip install. "
            "System package managers (apt/brew/...) require human approval."
        )
        metadata_extra = {"host_tools": probe}
    definition = ToolDefinition(
        name=RUN_CODE_TOOL,
        description=(
            f"Run a shell command inside the agent workspace ({workspace}) with bash -lc. "
            f"{backend_note} Use it to execute scripts you wrote, build artifacts, inspect "
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
            "sandbox": "host" if not sandboxed else "podman",
            **metadata_extra,
        },
    )
    return definition, run_code


def register_builtin_tools(registry: ToolRegistry, settings: Settings) -> list[str]:
    """Register ``run_code`` (and, on the host backend, ``ensure_packages``)."""
    definition, handler = make_run_code(settings)
    try:
        registry.register(definition, handler)
    except RegistryError:
        registry.set_handler(definition.name, handler)
    registered = [definition.name]

    if settings.sandbox != "podman":
        pkg_definition, pkg_handler = make_ensure_packages(settings)
        try:
            registry.register(pkg_definition, pkg_handler)
        except RegistryError:
            registry.set_handler(pkg_definition.name, pkg_handler)
        registered.append(pkg_definition.name)
    return registered
