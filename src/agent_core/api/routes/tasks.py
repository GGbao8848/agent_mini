"""Conversation (task) endpoints.

A task is one conversation: ``POST /tasks`` starts one with the first user
message, ``POST /tasks/{id}/messages`` continues it. Every turn executes as a
root run that reuses the conversation's thread, so the agent always sees the
full history. ``status`` is the derived conversation state — the latest
non-terminal root run's status, or the last root run's when everything is
terminal.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from sse_starlette import EventSourceResponse

from agent_core.api.attachments import attachment_notes, mirror_attachments
from agent_core.api.deps import ServiceDep
from agent_core.api.routes.events import SSE_HEADERS
from agent_core.api.schemas import (
    EventOut,
    TaskCreateRequest,
    TaskMessageRequest,
    TaskOut,
    TaskStateOut,
    TaskUpdateRequest,
)
from agent_core.config.settings import get_settings
from agent_core.domain.task import RunStatus
from agent_core.workspace.layout import default_root

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _conversation_out(service: ServiceDep, task_id: str) -> TaskOut:
    task = service.get_task(task_id)
    active = service.runtime.task_active_run(task_id)
    status = active.status.value if active is not None else RunStatus.CREATED.value
    return TaskOut.of(task, status=status, active_run_id=active.id if active else None)


def _working_root(service: ServiceDep, task_id: str) -> Path:
    """A conversation's working folder (project dir, else the ``default`` folder)."""
    return service.task_root(task_id) or default_root(Path(get_settings().workspace_dir))


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    payload: TaskCreateRequest, service: ServiceDep, wait: bool = Query(default=False)
) -> TaskOut:
    task = await service.submit_run(
        payload.agent_id,
        _with_attachments(payload.input, payload.attachments),
        wait=wait,
        project_id=payload.project_id,
        model=payload.model,
        permission_mode=(
            payload.permission_mode.value if payload.permission_mode else None
        ),
    )
    # Attachments are staged at the workspace root (outside any working folder);
    # mirror the referenced batches into the folder the file tools are rooted at.
    mirror_attachments(
        Path(get_settings().workspace_dir),
        _working_root(service, task.id),
        payload.attachments,
    )
    return _conversation_out(service, task.id)


@router.post("/{task_id}/messages", response_model=TaskOut, status_code=201)
async def send_message(
    task_id: str,
    payload: TaskMessageRequest,
    service: ServiceDep,
    wait: bool = Query(default=False),
) -> TaskOut:
    """Continue a conversation; the agent sees the full prior history."""
    await service.send_message(
        task_id,
        _with_attachments(payload.input, payload.attachments),
        wait=wait,
        model=payload.model,
        permission_mode=(
            payload.permission_mode.value if payload.permission_mode else None
        ),
    )
    mirror_attachments(
        Path(get_settings().workspace_dir),
        _working_root(service, task_id),
        payload.attachments,
    )
    return _conversation_out(service, task_id)


def _with_attachments(input: str, attachments: list[str]) -> str:
    """Append a hint about uploaded files to the message the agent sees."""
    return input + attachment_notes(attachments)


@router.get("", response_model=list[TaskOut])
def list_tasks(service: ServiceDep, agent_id: str | None = Query(default=None)) -> list[TaskOut]:
    return [_conversation_out(service, task.id) for task in service.list_tasks(agent_id)]


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, service: ServiceDep) -> TaskOut:
    return _conversation_out(service, task_id)


@router.get("/{task_id}/artifacts", response_model=list[dict[str, Any]])
def task_artifacts(task_id: str, service: ServiceDep) -> list[dict[str, Any]]:
    """Every artifact a conversation has produced across all its runs.

    A follow-up message starts a fresh run whose own artifact list is empty at
    first — the 产物 panel must look at the whole conversation, not just the
    active run, or earlier turns' files vanish on each new message.
    """
    service.get_task(task_id)  # fail fast with 404 for unknown conversations
    return service.task_artifacts(task_id)


@router.get("/{task_id}/state", response_model=TaskStateOut)
def task_state(task_id: str, service: ServiceDep) -> TaskStateOut:
    """Recorded progress of a conversation (R21): plan, status, failures.

    ``exists`` is False for a conversation that has produced no progress events
    yet — the console shows nothing rather than an empty skeleton.
    """
    state = service.task_state(task_id)
    return TaskStateOut.of(state, task_id=task_id)


@router.get("/{task_id}/events")
async def stream_task_events(task_id: str, service: ServiceDep) -> EventSourceResponse:
    """Whole-conversation event stream.

    Replays every run of ``task_id`` and keeps streaming across follow-up
    messages, so a multi-turn conversation's timeline survives each new turn's
    fresh root run. Unlike the per-run stream it never closes on a terminal
    event — a conversation can always be continued.
    """
    service.get_task(task_id)  # fail fast with 404 before opening the stream

    async def generator() -> AsyncIterator[dict[str, str]]:
        stream = service.subscribe_events(task_id=task_id)
        try:
            stream.replay(service.trace_task_events(task_id))
            async for event in stream.events():
                yield {
                    "event": event.event_type.value,
                    "data": EventOut.of(event).model_dump_json(),
                }
        finally:
            service.unsubscribe_events(stream)

    return EventSourceResponse(generator(), headers=SSE_HEADERS)


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(task_id: str, payload: TaskUpdateRequest, service: ServiceDep) -> TaskOut:
    """Rename, pin/unpin, rebind or re-dial a conversation."""
    task = service.runtime.update_task(
        task_id,
        title=payload.title,
        pinned=payload.pinned,
        project_id=payload.project_id,
        permission_mode=(
            payload.permission_mode.value if payload.permission_mode else None
        ),
    )
    return _conversation_out(service, task.id)


@router.post("/{task_id}/compact")
async def compact_task(task_id: str, service: ServiceDep) -> dict[str, Any]:
    """Force-summarize the conversation thread (long-conversation rescue).

    Refused while the conversation is running; the raw history is offloaded
    to the task directory so nothing is lost.
    """
    return await service.runtime.compact_task(task_id)


@router.post("/{task_id}/read", response_model=TaskOut)
def mark_task_read(task_id: str, service: ServiceDep) -> TaskOut:
    """Advance the conversation's read marker to its latest turn."""
    task = service.mark_task_read(task_id)
    return _conversation_out(service, task.id)


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str, service: ServiceDep) -> None:
    """Delete a conversation, its runs and its checkpoints (409 while live)."""
    await service.runtime.delete_task(task_id)


@router.post("/{task_id}/cancel", response_model=TaskOut)
def cancel_task(task_id: str, service: ServiceDep) -> TaskOut:
    service.cancel_task(task_id)
    return _conversation_out(service, task_id)
