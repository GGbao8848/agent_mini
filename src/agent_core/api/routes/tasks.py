"""Conversation (task) endpoints.

A task is one conversation: ``POST /tasks`` starts one with the first user
message, ``POST /tasks/{id}/messages`` continues it. Every turn executes as a
root run that reuses the conversation's thread, so the agent always sees the
full history. ``status`` is the derived conversation state — the latest
non-terminal root run's status, or the last root run's when everything is
terminal.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import TaskCreateRequest, TaskMessageRequest, TaskOut
from agent_core.domain.task import RunStatus

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _conversation_out(service: ServiceDep, task_id: str) -> TaskOut:
    task = service.get_task(task_id)
    active = service.runtime.task_active_run(task_id)
    status = active.status.value if active is not None else RunStatus.CREATED.value
    return TaskOut.of(task, status=status, active_run_id=active.id if active else None)


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    payload: TaskCreateRequest, service: ServiceDep, wait: bool = Query(default=False)
) -> TaskOut:
    task = await service.submit_run(payload.agent_id, payload.input, wait=wait)
    return _conversation_out(service, task.id)


@router.post("/{task_id}/messages", response_model=TaskOut, status_code=201)
async def send_message(
    task_id: str,
    payload: TaskMessageRequest,
    service: ServiceDep,
    wait: bool = Query(default=False),
) -> TaskOut:
    """Continue a conversation; the agent sees the full prior history."""
    await service.send_message(task_id, payload.input, wait=wait)
    return _conversation_out(service, task_id)


@router.get("", response_model=list[TaskOut])
def list_tasks(service: ServiceDep, agent_id: str | None = Query(default=None)) -> list[TaskOut]:
    return [_conversation_out(service, task.id) for task in service.list_tasks(agent_id)]


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, service: ServiceDep) -> TaskOut:
    return _conversation_out(service, task_id)


@router.post("/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: str, service: ServiceDep) -> TaskOut:
    service.cancel_task(task_id)
    return _conversation_out(service, task_id)
