"""Execution-policy endpoint (R24).

Exposes the runtime's execution envelope — filesystem, network, environment,
resource limits — so the console can show what ``run_code`` is actually allowed
to touch, from the same object the argv builder uses.
"""

from __future__ import annotations

from fastapi import APIRouter

from agent_core.api.schemas import ExecutionPolicyOut
from agent_core.config.settings import get_settings
from agent_core.execution import build_execution_policy

router = APIRouter(prefix="/execution", tags=["execution"])


@router.get("/policy", response_model=ExecutionPolicyOut)
def execution_policy() -> ExecutionPolicyOut:
    """The current code-execution envelope (backend, network, env, resources)."""
    return ExecutionPolicyOut.of(build_execution_policy(get_settings()))
