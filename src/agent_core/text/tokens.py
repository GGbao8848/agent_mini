"""Token estimation shared by context accounting and memory retrieval.

Lives in the domain-neutral ``text`` package (no runtime imports) so both the
runtime's context breakdown and the memory retriever can use it without an
import cycle.
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """CJK-aware token heuristic: ~1 token per CJK char, ~1 per 4 ASCII chars.

    Good enough for proportional display and budget checks; never used for
    billing or gating.
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f")
    return max(1, cjk + (len(text) - cjk) // 4)
