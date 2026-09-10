"""Semantic memory retrieval invariants (ported from aimemory).

Covers the hybrid ranking, the graceful keyword fallback when embeddings are
unavailable, the half-open circuit breaker, and vector persistence.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_core.domain.memory import Memory
from agent_core.memory import MemoryRepository, MemoryService
from agent_core.memory.embedding import EmbeddingClient
from agent_core.memory.retriever import cosine, retrieve


def _memory(content: str, memory_id: str = "m1") -> Memory:
    return Memory(id=memory_id, content=content)


# ------------------------------------------------------------------ ranking


def test_cosine_basic() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0  # dim mismatch
    assert cosine([], []) == 0.0


def test_semantic_channel_catches_a_paraphrase_keyword_misses() -> None:
    """The whole point: '回复简短' should find '偏好简洁' via vectors."""
    memories = [
        _memory("用户偏好简洁直接的回答。", "pref"),
        _memory("生产库使用 PostgreSQL 15。", "db"),
    ]
    # A query vector aligned with the preference entry but sharing no tokens.
    vectors = {"pref": [1.0, 0.0], "db": [0.0, 1.0]}

    hits = retrieve(
        memories,
        "回复能不能短一点",
        query_vector=[1.0, 0.0],
        vectors=vectors,
        semantic_weight=0.7,
    )

    assert [m.id for m in hits] == ["pref"]  # keyword alone would return []


def test_keyword_fallback_when_no_vectors() -> None:
    """With no embeddings, retrieval is exactly the keyword path."""
    memories = [_memory("项目代号 ALPHA-001", "p"), _memory("无关内容", "x")]

    hits = retrieve(memories, "ALPHA-001 是什么")

    assert [m.id for m in hits] == ["p"]


def test_unrelated_query_returns_nothing_even_with_vectors() -> None:
    """Semantic must not manufacture relevance: orthogonal vector, no overlap."""
    memories = [_memory("用户偏好简洁。", "pref")]
    vectors = {"pref": [0.0, 1.0]}

    hits = retrieve(
        memories, "计算 17 乘 23", query_vector=[1.0, 0.0], vectors=vectors
    )

    assert hits == []


def test_low_similarity_semantic_hit_is_gated_out() -> None:
    """A weak cosine (below threshold) with no keyword overlap is dropped.

    Cosine has a high baseline — unrelated text still scores ~0.5 — so without
    a threshold every prompt would carry irrelevant memories.
    """
    memories = [_memory("生产库使用 PostgreSQL 15。", "db")]
    vectors = {"db": [0.5, 0.866]}  # ~0.5 similarity, below the 0.55 default

    hits = retrieve(
        memories, "今天天气怎么样", query_vector=[1.0, 0.0], vectors=vectors
    )

    assert hits == []


def test_keyword_hit_survives_the_semantic_threshold() -> None:
    """An exact keyword match is always eligible, whatever the cosine."""
    memories = [_memory("项目代号 ALPHA-001", "p")]
    vectors = {"p": [0.0, 1.0]}  # orthogonal → semantic would gate it out

    hits = retrieve(memories, "ALPHA-001", query_vector=[1.0, 0.0], vectors=vectors)

    assert [m.id for m in hits] == ["p"]


def test_importance_does_not_override_relevance() -> None:
    relevant = Memory(id="r", content="部署在 10.10.10.146 的 vLLM 服务", importance=0)
    irrelevant = Memory(id="i", content="另一条无关记忆", importance=10)

    hits = retrieve([relevant, irrelevant], "10.10.10.146 上跑的是什么")

    assert [m.id for m in hits] == ["r"]


# ------------------------------------------------------ circuit breaker


class _CountingEmbedder(EmbeddingClient):
    """EmbeddingClient that fails a fixed number of times then succeeds."""

    def __init__(self, fail_times: int) -> None:
        super().__init__(base_url="http://x", model="m", enabled=True)
        self.calls = 0
        self.fail_times = fail_times

    async def embed(self, text: str) -> list[float] | None:  # type: ignore[override]
        self.calls += 1
        if self.calls <= self.fail_times:
            return None
        return [1.0, 0.0]


async def test_embedding_failure_returns_none_never_raises() -> None:
    client = EmbeddingClient(base_url="", model="", enabled=True)
    assert not client.enabled  # no base_url/model → disabled
    assert await client.embed("hi") is None


async def test_circuit_breaker_stops_hitting_a_dead_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the threshold, the breaker short-circuits calls (no network)."""
    client = EmbeddingClient(base_url="http://x", model="m", enabled=True)
    hits = {"n": 0}

    async def _fail(*_a: object, **_k: object) -> object:
        hits["n"] += 1
        raise RuntimeError("down")

    monkeypatch.setattr(httpx.AsyncClient, "post", _fail)

    for _ in range(3):  # threshold failures → breaker opens
        assert await client.embed("x") is None
    opened_at = hits["n"]

    assert await client.embed("x") is None
    assert hits["n"] == opened_at  # no further network calls while open


# ----------------------------------------------------------- persistence


async def test_vectors_persist_and_reload(tmp_path: Path) -> None:
    from agent_core.persistence.store import SqliteStore

    store = SqliteStore(f"sqlite:///{tmp_path / 'mem.db'}")
    repo = MemoryRepository(store)
    service = MemoryService(repo)
    memory = service.add("用户叫宋奎。")
    repo.store_vector(memory.id, [0.1, 0.2, 0.3])

    # A fresh process rehydrates the vectors from the DB.
    repo2 = MemoryRepository(store)
    repo2.hydrate()
    assert repo2.hydrate_vectors() == 1
    assert repo2.vector(memory.id) == pytest.approx([0.1, 0.2, 0.3])
    store.close()


async def test_arembed_on_write_when_endpoint_present() -> None:
    """Writing a memory embeds it (best-effort) so it is semantically findable."""
    captured: list[str] = []

    class _Stub(EmbeddingClient):
        def __init__(self) -> None:
            super().__init__(base_url="http://x", model="m", enabled=True)

        async def embed(self, text: str) -> list[float] | None:  # type: ignore[override]
            captured.append(text)
            return [1.0, 0.0]

    repo = MemoryRepository()
    service = MemoryService(repo, embedding=_Stub())
    memory = service.add("用户偏好简洁回答。")

    # _schedule_embed runs on the event loop; let it complete.
    import asyncio

    await asyncio.sleep(0)
    assert repo.vector(memory.id) == [1.0, 0.0]
    assert captured == ["用户偏好简洁回答。"]
