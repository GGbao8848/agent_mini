"""Message-content helpers shared by executor and trace callbacks."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage


def extract_text(content: str | list[Any]) -> str:
    """Flatten LLM message content (string or content blocks) into plain text."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


def cap_text(value: str, *, max_chars: int = 4000, keep_head: int = 2000) -> str:
    """Shorten a long tool result for the model context.

    Keeps the head (usually the informative prefix) and the tail (the end of
    an error/log trace), dropping the middle. Long tool outputs are the main
    driver of context bloat: every step re-prefills the whole history, so a
    few multi-KB results make each subsequent model call seconds slower.
    """
    if len(value) <= max_chars:
        return value
    if keep_head >= max_chars:
        # Degenerate budget: head-only. ``value[-0:]`` would be the WHOLE
        # string (and then some), so the tail slice must not run at all.
        return f"{value[:keep_head]}\n…[truncated, total {len(value)} chars]…"
    tail = max_chars - keep_head
    return (
        f"{value[:keep_head]}\n…[middle {len(value) - keep_head - tail} chars "
        f"truncated, total {len(value)} chars]…\n{value[-tail:]}"
    )


def cap_result(value: Any, *, max_chars: int = 4000) -> Any:
    """Cap any tool result before it enters the model context.

    Strings go through :func:`cap_text`. Structured results (dicts, lists —
    e.g. a directory listing or a JSON payload) are serialized and checked:
    they used to bypass the cap entirely, so one verbose tool could push
    hundreds of KB into every subsequent prefill. Within budget the original
    object is returned untouched (callers may rely on the structure); over
    budget the capped JSON string replaces it. Scalars pass through as-is.
    """
    if isinstance(value, str):
        return cap_text(value, max_chars=max_chars)
    if isinstance(value, (dict, list)):
        import json

        try:
            rendered = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            rendered = str(value)
        if len(rendered) <= max_chars:
            return value
        return cap_text(rendered, max_chars=max_chars)
    return value


def last_message_text(state: Any) -> str | None:
    """Text of the last message in a ``{'messages': [...]}`` state, if any."""
    messages = state.get("messages") if isinstance(state, dict) else None
    if not messages:
        return None
    last = messages[-1]
    if isinstance(last, BaseMessage):
        return extract_text(last.content)
    return None
