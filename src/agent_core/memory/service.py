"""Memory governance: the single write path that keeps the store clean.

Every write goes through :class:`MemoryService` so the failure modes that sank
the first memory attempt cannot recur:

- **Duplicates** — the old design stored the same fact three times. ``add``
  normalizes the content and refreshes an existing live entry in place instead
  of appending a twin.
- **Unbounded growth** — entries carry importance/confidence; retrieval (not
  wholesale injection) decides what reaches the prompt.
- **Stale facts** — ``supersede`` marks the old entry and links the new one, so
  retrieval only ever surfaces the current truth.

Writes are explicit (console CRUD, the agent's ``remember`` tool, the lesson
loop) — never a silent per-turn extraction.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime

from agent_core.domain.memory import Memory, MemoryScope, MemoryType
from agent_core.memory.embedding import EmbeddingClient
from agent_core.memory.repository import MemoryRepository
from agent_core.memory.retriever import (
    DEFAULT_LIMIT,
    DEFAULT_SEMANTIC_THRESHOLD,
    DEFAULT_TOKEN_BUDGET,
    retrieve,
)

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\s，。、；：！？,.;:!?\"'`()（）\[\]【】]+")


def normalize(content: str) -> str:
    """Canonical form used to detect duplicate memories."""
    return _PUNCT_RE.sub("", _WS_RE.sub("", content.strip().lower()))


class MemoryService:
    """Read/write façade over a :class:`MemoryRepository`.

    Writes keep the embedding sidecar in step: a stored memory is embedded
    (best-effort, in the background) so semantic retrieval can find it. When no
    embedding endpoint is configured everything degrades to keyword retrieval.
    """

    def __init__(
        self,
        repository: MemoryRepository,
        *,
        embedding: EmbeddingClient | None = None,
        semantic_weight: float = 0.7,
        semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
    ) -> None:
        self._repository = repository
        self._embedding = embedding
        self._semantic_weight = semantic_weight
        self._semantic_threshold = semantic_threshold

    async def _embed_into_index(self, memory: Memory) -> None:
        """Best-effort: embed ``memory`` and store its vector (never raises)."""
        if self._embedding is None or not self._embedding.enabled:
            return
        vector = await self._embedding.embed(memory.content)
        if vector is not None:
            self._repository.store_vector(memory.id, vector)

    def list(self, *, live_only: bool = False) -> list[Memory]:
        items = self._repository.list()
        if live_only:
            items = [m for m in items if m.is_live()]
        return sorted(items, key=lambda m: m.updated_at, reverse=True)

    def get(self, memory_id: str) -> Memory:
        return self._repository.get(memory_id)

    def find_duplicate(self, content: str) -> Memory | None:
        """An existing live memory with the same normalized content, if any."""
        target = normalize(content)
        if not target:
            return None
        for memory in self._repository.list():
            if memory.is_live() and normalize(memory.content) == target:
                return memory
        return None

    def add(
        self,
        content: str,
        *,
        scope: MemoryScope = MemoryScope.USER,
        type: MemoryType = MemoryType.FACT,
        source: str = "manual",
        task_id: str | None = None,
        importance: int = 0,
        confidence: float = 1.0,
    ) -> Memory:
        """Store a memory, deduplicating by normalized content.

        A duplicate refreshes the existing entry (bumping its timestamp and
        taking the stronger importance/confidence) and returns *it*, so callers
        cannot accidentally create twins of the same fact.
        """
        existing = self.find_duplicate(content)
        if existing is not None:
            existing.importance = max(existing.importance, importance)
            existing.confidence = max(existing.confidence, confidence)
            existing.updated_at = datetime.now(UTC)
            self._repository.replace(existing)
            return existing
        memory = Memory(
            scope=scope,
            type=type,
            content=content.strip(),
            source=source,
            task_id=task_id,
            importance=importance,
            confidence=confidence,
        )
        self._repository.register(memory)
        self._schedule_embed(memory)
        return memory

    def upsert(self, memory: Memory) -> Memory:
        """Persist an edited entry (console edit path)."""
        memory.updated_at = datetime.now(UTC)
        self._repository.replace(memory)
        self._schedule_embed(memory)  # text may have changed → refresh vector
        return memory

    def _schedule_embed(self, memory: Memory) -> None:
        """Fire-and-forget embedding so writes stay synchronous.

        Runs on the current event loop when there is one (the API/tool paths
        always have one); with no loop — e.g. pure sync tests — the memory is
        simply keyword-retrievable until the next embed pass.
        """
        if self._embedding is None or not self._embedding.enabled:
            return
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._embed_into_index(memory))

    def supersede(
        self,
        old_id: str,
        new_content: str,
        *,
        scope: MemoryScope | None = None,
        type: MemoryType | None = None,
        importance: int = 0,
        confidence: float = 1.0,
        source: str = "manual",
    ) -> Memory:
        """Replace ``old_id`` with a new entry, marking the old one superseded."""
        old = self._repository.get(old_id)
        replacement = Memory(
            scope=scope or old.scope,
            type=type or old.type,
            content=new_content.strip(),
            source=source,
            importance=max(importance, old.importance),
            confidence=confidence,
        )
        self._repository.register(replacement)
        old.superseded_by = replacement.id
        old.active = False
        old.updated_at = datetime.now(UTC)
        self._repository.replace(old)
        return replacement

    def forget(self, memory_id: str) -> Memory:
        """Delete a memory outright (the user asked to forget it)."""
        return self._repository.remove(memory_id)

    def deactivate(self, memory_id: str) -> Memory:
        """Soft-forget: keep the row for audit but stop retrieving it."""
        memory = self._repository.get(memory_id)
        memory.active = False
        memory.updated_at = datetime.now(UTC)
        self._repository.replace(memory)
        return memory

    def retrieve(
        self,
        query: str,
        *,
        scopes: Sequence[MemoryScope] | None = None,
        limit: int = DEFAULT_LIMIT,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> Sequence[Memory]:
        """Keyword-only retrieval (sync). Use :meth:`aretrieve` for semantics.

        Kept for synchronous callers/tests; it ignores embeddings, so it never
        blocks on the network.
        """
        return retrieve(
            self._repository.list(),
            query,
            scopes=scopes,
            limit=limit,
            token_budget=token_budget,
        )

    async def aretrieve(
        self,
        query: str,
        *,
        scopes: Sequence[MemoryScope] | None = None,
        limit: int = DEFAULT_LIMIT,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
    ) -> Sequence[Memory]:
        """Hybrid retrieval: semantic (when available) blended with keyword.

        Embeds the query, then ranks with cosine similarity plus keyword
        overlap. If the embedding endpoint is off/unreachable the query vector
        is ``None`` and this degrades to exactly the keyword path — retrieval
        never fails because of embeddings.
        """
        query_vector = None
        if self._embedding is not None and self._embedding.enabled:
            query_vector = await self._embedding.embed(query)
        return retrieve(
            self._repository.list(),
            query,
            scopes=scopes,
            limit=limit,
            token_budget=token_budget,
            query_vector=query_vector,
            vectors=dict(self._repository.vectors()) if query_vector is not None else None,
            semantic_weight=self._semantic_weight,
            semantic_threshold=self._semantic_threshold,
        )

    async def embed_missing(self) -> int:
        """Backfill vectors for memories that lack one; returns how many added.

        Used on startup so existing memories (written before embeddings were
        enabled) become semantically searchable without a manual migration.
        """
        if self._embedding is None or not self._embedding.enabled:
            return 0
        added = 0
        for memory in self._repository.list():
            if not memory.is_live() or self._repository.vector(memory.id) is not None:
                continue
            vector = await self._embedding.embed(memory.content)
            if vector is not None:
                self._repository.store_vector(memory.id, vector)
                added += 1
        return added

    def hydrate(self) -> None:
        self._repository.hydrate()
        self._repository.hydrate_vectors()


def memory_prompt(memories: Sequence[Memory]) -> str:
    """Render retrieved memories as a system-prompt block (empty when none)."""
    if not memories:
        return ""
    lines = "\n".join(f"- {m.content}" for m in memories)
    return (
        "\n\n# 长期记忆（与本轮请求相关）\n"
        "以下是与当前请求相关的长期事实，作为背景参考；仅当用户明确表示情况"
        "变化时才推翻它们。\n"
        f"{lines}\n"
    )


__all__ = ["MemoryService", "memory_prompt", "normalize"]
