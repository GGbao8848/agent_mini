"""Schedule endpoints.

A schedule is a persistent trigger: one-time, cron, or interval. Executing a
schedule (automatically, or via ``POST /{id}/run``) creates a fresh
conversation (Task) and starts it, so the resulting task appears in the
console and can be continued by hand.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import (
    ScheduleCreateRequest,
    ScheduleOut,
    ScheduleRunOut,
    ScheduleUpdateRequest,
)
from agent_core.domain.schedule import Schedule
from agent_core.errors.exceptions import AgentError, ScheduleError

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _to_model(schedule: Schedule) -> ScheduleOut:
    return ScheduleOut.of(schedule)


@router.get("", response_model=list[ScheduleOut])
def list_schedules(service: ServiceDep) -> list[ScheduleOut]:
    return [_to_model(s) for s in service.list_schedules()]


@router.post("", response_model=ScheduleOut, status_code=201)
def create_schedule(payload: ScheduleCreateRequest, service: ServiceDep) -> ScheduleOut:
    data = payload.model_dump()
    data["agent_id"] = service.default_agent()  # schedules always use the default agent
    schedule = Schedule(**data)
    try:
        return _to_model(service.create_schedule(schedule))
    except ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{schedule_id}", response_model=ScheduleOut)
def get_schedule(schedule_id: str, service: ServiceDep) -> ScheduleOut:
    return _to_model(service.get_schedule(schedule_id))


@router.put("/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: str, payload: ScheduleUpdateRequest, service: ServiceDep
) -> ScheduleOut:
    existing = service.get_schedule(schedule_id)
    data = payload.model_dump()
    data["agent_id"] = existing.agent_id  # agent is fixed at creation
    updated = existing.model_copy(update=data)
    try:
        return _to_model(service.update_schedule(updated))
    except ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str, service: ServiceDep) -> None:
    service.delete_schedule(schedule_id)


@router.post("/{schedule_id}/run", response_model=ScheduleRunOut)
async def run_schedule_now(schedule_id: str, service: ServiceDep) -> ScheduleRunOut:
    """Run a schedule immediately; returns the new conversation's task id."""
    task = await service.run_schedule_now(schedule_id)
    return ScheduleRunOut(schedule_id=schedule_id, task_id=task.id)
