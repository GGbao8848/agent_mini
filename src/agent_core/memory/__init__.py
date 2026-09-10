"""Long-term memory: durable, scoped, retrieved (not wholesale-injected).

This package is the second attempt at cross-session memory. The first was a
flat list injected in full into every prompt and auto-extracted every turn —
it was rolled back as noisy and low-value. The design here is the guide's R10:
explicit scopes and types, a write path that dedupes and supersedes, and
retrieval limited to the few entries relevant to the current request.
"""

from agent_core.memory.lesson import lesson_hint, looks_like_correction
from agent_core.memory.policy import MemoryOrigin, MemoryPolicy, ScopeRef, WriteDecision
from agent_core.memory.repository import MemoryRepository
from agent_core.memory.retriever import retrieve
from agent_core.memory.service import MemoryService, memory_prompt, normalize

__all__ = [
    "MemoryOrigin",
    "MemoryPolicy",
    "MemoryRepository",
    "MemoryService",
    "ScopeRef",
    "WriteDecision",
    "lesson_hint",
    "looks_like_correction",
    "memory_prompt",
    "normalize",
    "retrieve",
]
