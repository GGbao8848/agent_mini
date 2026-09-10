"""Memory retrieval: pick the few entries actually relevant to a request.

The rolled-back design injected the *whole* memory list into every prompt,
which does not scale and buries the signal (MEM-005). Retrieval here scores
live entries against the request text and returns a bounded top-k that also
fits a token budget, so the injected block stays small and focused — the
guide's "记忆的价值在准不在全".
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


def tokenize(text: str) -> set[str]:
    """Cheap mixed-script tokens: ASCII words plus individual CJK characters.

    Character-level CJK matching is deliberate — it needs no segmenter and
    still catches the overlap that matters for short memory strings.
    """
    lowered = text.lower()
    return set(_WORD_RE.findall(lowered)) | set(_CJK_RE.findall(lowered))


def _score(memory: Memory, query_tokens: set[str]) -> float:
    """Relevance of ``memory`` to the query, blended with importance/confidence."""
    content_tokens = tokenize(memory.content)
    if not content_tokens:
        return 0.0
    overlap = len(query_tokens & content_tokens)
    if overlap == 0:
        return 0.0
    # Normalize by content size so a long entry does not win on length alone.
    relevance = overlap / math.sqrt(len(content_tokens))
    return relevance + memory.importance * 0.05 + memory.confidence * 0.1


def retrieve(
    memories: Iterable[Memory],
    query: str,
    *,
    scopes: Sequence[MemoryScope] | None = None,
    limit: int = DEFAULT_LIMIT,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> list[Memory]:
    """Return the top-``limit`` live memories for ``query`` within a token budget.

    Only active, non-superseded entries in ``scopes`` (all scopes when omitted)
    are considered; entries with no token overlap with the query are dropped, so
    an unrelated request injects nothing rather than irrelevant noise.
    """
    query_tokens = tokenize(query)
    candidates = [
        memory
        for memory in memories
        if memory.is_live() and (scopes is None or memory.scope in scopes)
    ]
    scored = [(m, _score(m, query_tokens)) for m in candidates]
    ranked = sorted(
        (pair for pair in scored if pair[1] > 0),
        key=lambda pair: pair[1],
        reverse=True,
    )

    selected: list[Memory] = []
    spent = 0
    for memory, _ in ranked:
        if len(selected) >= limit:
            break
        cost = estimate_tokens(memory.content)
        if selected and spent + cost > token_budget:
            break
        selected.append(memory)
        spent += cost
    return selected
