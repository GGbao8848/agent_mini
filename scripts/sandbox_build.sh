#!/usr/bin/env bash
# Build the agent-core sandbox image used by the run_code tool.
# Usage: scripts/sandbox_build.sh   (honours HTTP(S)_PROXY for the registry)
set -euo pipefail
cd "$(dirname "$0")/.."
exec podman build -f deploy/Containerfile -t localhost/agent-core-sandbox:latest .
