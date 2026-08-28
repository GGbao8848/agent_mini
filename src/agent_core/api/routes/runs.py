"""Run lifecycle endpoints.

POST /runs starts a run as a background task and returns immediately; pass
``?wait=true`` to block until a terminal state (handy for CLI and demos).
Live progress goes through the SSE event stream, not through polling.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import RunCreateRequest, RunOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", response_model=RunOut, status_code=201)
async def create_run(
    payload: RunCreateRequest, service: ServiceDep, wait: bool = Query(default=False)
) -> RunOut:
    run = await service.submit_run(
        payload.agent_id,
        payload.input,
        parent_run_id=payload.parent_run_id,
        wait=wait,
    )
    return RunOut.of(run, output=service.final_output(run.id))


@router.get("", response_model=list[RunOut])
def list_runs(service: ServiceDep, agent_id: str | None = Query(default=None)) -> list[RunOut]:
    return [
        RunOut.of(run, output=service.final_output(run.id))
        for run in service.list_runs(agent_id)
    ]


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: str, service: ServiceDep) -> RunOut:
    run = service.get_run(run_id)
    return RunOut.of(run, output=service.final_output(run.id))


@router.post("/{run_id}/cancel", response_model=RunOut)
def cancel_run(run_id: str, service: ServiceDep) -> RunOut:
    run = service.cancel_run(run_id)
    return RunOut.of(run, output=service.final_output(run.id))
