"""Memory retrieval: semantic + keyword hybrid, bounded top-k.

The rolled-back design injected the *whole* memory list into every prompt,
which does not scale and buries the signal (MEM-005). This module scores live
entries against the request and returns a bounded top-k that also fits a token
budget — the guide's "记忆的价值在准不在全".

Two recall channels, ported from aimemory's hybrid search:

- **keyword** overlap (cheap, always available, exact substrings)
- **semantic** cosine similarity over embeddings, when an endpoint is
  configured and reachable

Semantic catches paraphrases keyword misses ("回复要简短" ↔ "偏好简洁回复");
keyword is the fallback that keeps retrieval useful when embeddings are off or
down. The two are blended into one score; an entry with neither channel fired
is dropped, so an unrelated request injects nothing.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence

from agent_core.domain.memory import Memory, MemoryScope
from agent_core.text.tokens import estimate_tokens

_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

DEFAULT_LIMIT = 5
DEFAULT_TOKEN_BUDGET = 1500
DEFAULT_SEMANTIC_THRESHOLD = 0.55
"""Minimum cosine to count as a semantic hit.

Qwen3-Embedding scores unrelated Chinese text around 0.4–0.5, so a lower bar
injects noise. Measured on this model: a clear paraphrase lands ≈0.6+ while an
unrelated query stays ≈0.5 and below.
"""


def tokenize(text: str) -> set[str]:
    """Cheap mixed-script tokens: ASCII words plus individual CJK characters.

    Character-level CJK matching is deliberate — it needs no segmenter and
    still catches the overlap that matters for short memory strings.
    """
    lowered = text.lower()
    return set(_WORD_RE.findall(lowered)) | set(_CJK_RE.findall(lowered))


def keyword_score(memory: Memory, query_tokens: set[str]) -> float:
    """Overlap of the query with the memory, normalized by memory length.

    Normalizing by ``sqrt(len)`` keeps a long entry from winning on length
    alone. Returns 0.0 (not a floor) when nothing overlaps, so the caller can
    drop the entry entirely.
    """
    content_tokens = tokenize(memory.content)
    if not content_tokens:
        return 0.0
    overlap = len(query_tokens & content_tokens)
    if overlap == 0:
        return 0.0
    return overlap / math.sqrt(len(content_tokens))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors (0.0 on any mismatch/zero norm)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = norm_a = norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    return 0.0 if denom == 0.0 else dot / denom


def retrieve(
    memories: Iterable[Memory],
    query: str,
    *,
    scopes: Sequence[MemoryScope] | None = None,
    limit: int = DEFAULT_LIMIT,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    query_vector: Sequence[float] | None = None,
    vectors: dict[str, Sequence[float]] | None = None,
    semantic_weight: float = 0.7,
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
) -> list[Memory]:
    """Return the top-``limit`` live memories for ``query`` within a token budget.

    Only active, non-superseded entries in ``scopes`` (all scopes when omitted)
    are considered. When ``query_vector``/``vectors`` are provided the semantic
    channel is blended in with ``semantic_weight``; otherwise retrieval is
    keyword-only (the graceful fallback when embeddings are unavailable).

    ``semantic_threshold`` gates the semantic channel: an entry with no keyword
    overlap whose cosine falls below it is dropped. Without this, cosine's high
    baseline (unrelated text still scores ~0.5) would inject irrelevant memories
    into every prompt. A keyword hit is always eligible regardless of the
    threshold — exact matches must not be filtered out.
    """
    query_tokens = tokenize(query)
    candidates = [
        memory
        for memory in memories
        if memory.is_live() and (scopes is None or memory.scope in scopes)
    ]

    scored: list[tuple[Memory, float]] = []
    for memory in candidates:
        kw = keyword_score(memory, query_tokens)
        sem = 0.0
        if query_vector is not None and vectors is not None:
            vector = vectors.get(memory.id)
            if vector is not None:
                sim = cosine(query_vector, vector)
                if sim >= semantic_threshold:
                    sem = sim
        if kw == 0.0 and sem == 0.0:
            continue
        blend = semantic_weight * sem + (1.0 - semantic_weight) * kw
        # Small importance/confidence nudge — enough to break ties, never
        # enough to override a clear relevance gap.
        blend += memory.importance * 0.02 + memory.confidence * 0.05
        scored.append((memory, blend))

    scored.sort(key=lambda pair: pair[1], reverse=True)

    selected: list[Memory] = []
    spent = 0
    for memory, _ in scored:
        if len(selected) >= limit:
            break
        cost = estimate_tokens(memory.content)
        if selected and spent + cost > token_budget:
            break
        selected.append(memory)
        spent += cost
    return selected
