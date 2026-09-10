"""Long-term memory endpoints: list, add, edit, forget.

The console's memory panel is the human curation surface; the agent writes
through the ``remember`` tool. Retrieval (not wholesale injection) decides what
reaches a run's prompt — see :mod:`agent_core.memory`.
"""

from __future__ import annotations

from fastapi import APIRouter

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import MemoryCreateRequest, MemoryOut, MemoryUpdateRequest
from agent_core.domain.memory import MemoryScope, MemoryType

router = APIRouter(prefix="/memories", tags=["memories"])


def _scope(value: str | None, default: MemoryScope) -> MemoryScope:
    return next((s for s in MemoryScope if s.value == value), default)


def _type(value: str | None, default: MemoryType) -> MemoryType:
    return next((t for t in MemoryType if t.value == value), default)


@router.get("", response_model=list[MemoryOut])
def list_memories(service: ServiceDep) -> list[MemoryOut]:
    return [MemoryOut.of(m) for m in service.runtime.memories.list()]


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(payload: MemoryCreateRequest, service: ServiceDep) -> MemoryOut:
    memory = service.runtime.memories.add(
        payload.content,
        scope=_scope(payload.scope, MemoryScope.USER),
        type=_type(payload.type, MemoryType.FACT),
    )
    return MemoryOut.of(memory)


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(
    memory_id: str, payload: MemoryUpdateRequest, service: ServiceDep
) -> MemoryOut:
    memory = service.runtime.memories.get(memory_id)
    if payload.content is not None:
        memory.content = payload.content
    if payload.scope is not None:
        memory.scope = _scope(payload.scope, memory.scope)
    if payload.type is not None:
        memory.type = _type(payload.type, memory.type)
    return MemoryOut.of(service.runtime.memories.upsert(memory))


@router.delete("/{memory_id}", response_model=MemoryOut)
def delete_memory(memory_id: str, service: ServiceDep) -> MemoryOut:
    memory = service.runtime.memories.get(memory_id)
    service.runtime.memories.forget(memory_id)
    return MemoryOut.of(memory)
