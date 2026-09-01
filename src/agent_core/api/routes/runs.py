"""Run read endpoint.

Conversations (tasks) are the write-side resource: creating a task or sending
a follow-up message goes through ``/v1/tasks``. Runs remain readable for the
execution-level views the console needs (single-run detail, events, artifacts);
a run's ``task_id`` points back at the conversation it belongs to.
"""

from __future__ import annotations

from fastapi import APIRouter

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import RunOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: str, service: ServiceDep) -> RunOut:
    run = service.get_run(run_id)
    # Live usage for an executing run (the run's own usage field is final-only);
    # the console's top stats stay populated while a task is in flight.
    return RunOut.of(
        run,
        output=service.final_output(run.id),
        input=service.task_input(run.id),
        usage=service.run_usage(run.id),
    )
