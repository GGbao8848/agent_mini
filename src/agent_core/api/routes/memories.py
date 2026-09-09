"""Long-term memory endpoints: list, add, edit, delete.

Memories are injected into every run's system prompt; the panel is the
human's curation surface, ``save_memory`` the agent's write path.
"""

from __future__ import annotations

from fastapi import APIRouter

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import MemoryCreateRequest, MemoryOut, MemoryUpdateRequest

router = APIRouter(prefix="/memories", tags=["memories"])


@router.get("", response_model=list[MemoryOut])
def list_memories(service: ServiceDep) -> list[MemoryOut]:
    return [MemoryOut.of(m) for m in service.runtime.list_memories()]


@router.post("", response_model=MemoryOut, status_code=201)
def create_memory(payload: MemoryCreateRequest, service: ServiceDep) -> MemoryOut:
    return MemoryOut.of(service.runtime.add_memory(payload.content))


@router.patch("/{memory_id}", response_model=MemoryOut)
def update_memory(memory_id: str, payload: MemoryUpdateRequest, service: ServiceDep) -> MemoryOut:
    return MemoryOut.of(service.runtime.update_memory(memory_id, payload.content))


@router.delete("/{memory_id}", response_model=MemoryOut)
def delete_memory(memory_id: str, service: ServiceDep) -> MemoryOut:
    runtime = service.runtime
    memory = next((m for m in runtime.list_memories() if m.id == memory_id), None)
    runtime.delete_memory(memory_id)
    return MemoryOut.of(memory)
