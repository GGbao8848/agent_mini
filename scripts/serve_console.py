"""Serve the Agent Console on the LAN with the avatar agent pre-registered.

Usage:
  uv run --env-file .env python scripts/serve_console.py [--host 0.0.0.0] [--port 8000]

Then open http://<this-machine-ip>:<port>/console/ from any machine on the
LAN (the console token, if configured, is prompted once and remembered).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # reuse the e2e avatar spec

import uvicorn
from e2e_autonomy import avatar_spec

from agent_core.api.app import create_app
from agent_core.application.bootstrap import default_service


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    service = default_service()
    if "avatar" not in service.runtime.agents:
        service.runtime.agents.register(avatar_spec())
    app = create_app(service)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
