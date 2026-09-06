"""Agent-managed host Python environment (the ``sandbox=host`` backend).

Not every machine has Podman; this module makes the host backend *hygienic*
instead of raw:

- One shared venv (``--system-site-packages``) is created on first use, so
  libraries already installed on the host are importable directly and are
  never installed a second time.
- ``ensure_packages`` checks importability first and installs only what is
  missing — always into the agent venv, never the system site-packages or the
  project venv.
- Installs prefer ``uv pip`` (fast, resolvable) and fall back to pip; both
  share one cache directory so re-installs and env rebuilds don't re-download.
- A one-shot host-tool probe (``detect_host_tools``) tells the agent up front
  which CLIs exist, so it doesn't install things that are already there.

Security note: the host backend still runs with the process user's full
permissions — this module improves *package hygiene*, not isolation. Use the
``podman`` backend when isolation matters.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent_core.config.settings import Settings
from agent_core.errors.exceptions import ToolError

_DEFAULT_ENV_DIR = Path.home() / ".agent_core" / "agent-env"
_DEFAULT_CACHE_DIR = Path.home() / ".agent_core" / "cache"

_PROBED_TOOLS = (
    "python3", "pip", "uv", "git", "node", "npx", "ffmpeg", "ffprobe",
    "libreoffice", "pandoc", "curl", "wget",
)

# Installed once when the agent env is first created. Without this, every
# fresh deployment's first document task pays a pip install round-trip (or,
# worse, wanders into `pip install` from run_code). Best-effort: a failed
# seed never breaks env creation — the agent can ensure_packages later.
_SEED_PACKAGES = (
    "python-pptx", "openpyxl", "matplotlib", "pandas", "requests",
    "beautifulsoup4", "pillow",
)

# Probe result cache: the host's CLI inventory doesn't change within a process.
_probe_cache: dict[str, Any] | None = None


def agent_env_dir(settings: Settings) -> Path:
    if settings.agent_env_dir:
        return Path(settings.agent_env_dir).expanduser().resolve()
    return _DEFAULT_ENV_DIR.resolve()


def _cache_dir() -> Path:
    _DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _DEFAULT_CACHE_DIR


def ensure_agent_env(settings: Settings) -> Path:
    """Return the agent venv, creating it on first use (idempotent)."""
    env_dir = agent_env_dir(settings)
    if (env_dir / "pyvenv.cfg").exists():
        return env_dir
    env_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", "--system-site-packages", str(env_dir)],
            check=True, capture_output=True, text=True, timeout=120,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise ToolError(
            f"Failed to create the agent Python environment at {env_dir}: {exc}",
            details={"env_dir": str(env_dir)},
        ) from exc
    try:
        install_packages(env_dir, list(_SEED_PACKAGES), timeout=300.0)
    except Exception:
        # Seed is a convenience; the env itself is valid without it.
        pass
    return env_dir


@lru_cache(maxsize=64)
def _env_python(env_dir_str: str) -> str:
    """Absolute path of the venv's python (venv python is a symlink — no resolve)."""
    env_dir = Path(env_dir_str)
    python = env_dir / "bin" / "python"
    if not python.exists():
        python = env_dir / "Scripts" / "python.exe"  # windows venvs
    return str(python)


def _dist_check_script(packages: list[str]) -> str:
    return (
        "import importlib.util, json, sys\n"
        "from importlib.metadata import distribution\n"
        "names = json.loads(sys.argv[1])\n"
        "def ok(n):\n"
        "    try:\n"
        "        distribution(n)\n"
        "        return True\n"
        "    except Exception:\n"
        "        try:\n"
        "            mod = n.replace('-', '_').split('[')[0].strip()\n"
        "            return importlib.util.find_spec(mod) is not None\n"
        "        except Exception:\n"
        "            return False\n"
        "print(json.dumps({n: ok(n) for n in names}))\n"
    )


def check_packages(env_dir: Path, packages: list[str]) -> dict[str, bool]:
    """Which of ``packages`` are already importable in the agent env."""
    result = subprocess.run(
        [
            _env_python(str(env_dir)), "-c", _dist_check_script(packages),
            json.dumps(packages),
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise ToolError(
            f"Package check failed: {result.stderr.strip()[:300]}",
            details={"packages": packages},
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _install_command(env_dir: Path, packages: list[str]) -> list[str]:
    cache = str(_cache_dir())
    if shutil.which("uv"):
        return [
            "uv", "pip", "install", "--python", _env_python(str(env_dir)),
            "--cache-dir", cache, *packages,
        ]
    return [
        _env_python(str(env_dir)), "-m", "pip", "install",
        "--cache-dir", cache, *packages,
    ]


def install_packages(env_dir: Path, packages: list[str], timeout: float = 600.0) -> str:
    """Install ``packages`` into the agent venv; returns trimmed combined output."""
    result = subprocess.run(
        _install_command(env_dir, packages),
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "PYTHONUNBUFFERED": "1",
             "UV_CACHE_DIR": str(_cache_dir())},
    )
    tail = (result.stdout + "\n" + result.stderr).strip()[-1500:]
    if result.returncode != 0:
        raise ToolError(
            f"Failed to install {', '.join(packages)}:\n{tail}",
            details={"packages": packages},
        )
    return tail


def detect_host_tools() -> dict[str, Any]:
    """One-shot probe of the host's CLI inventory (cached for the process)."""
    global _probe_cache
    if _probe_cache is not None:
        return dict(_probe_cache)
    available = sorted(name for name in _PROBED_TOOLS if shutil.which(name))
    _probe_cache = {
        "available": available,
        "missing": sorted(set(_PROBED_TOOLS) - set(available)),
        "python": platform.python_version(),
        "has_uv": "uv" in available,
        "installer": "uv" if shutil.which("uv") else "pip",
    }
    return dict(_probe_cache)


async def ensure_host_env(settings: Settings) -> Path:
    """Async wrapper: create/reuse the agent venv off the event loop."""
    return await asyncio.to_thread(ensure_agent_env, settings)
