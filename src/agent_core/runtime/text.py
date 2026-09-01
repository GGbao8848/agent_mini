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
    tail = max_chars - keep_head
    return (
        f"{value[:keep_head]}\n…[middle {len(value) - keep_head - tail} chars "
        f"truncated, total {len(value)} chars]…\n{value[-tail:]}"
    )


def last_message_text(state: Any) -> str | None:
    """Text of the last message in a ``{'messages': [...]}`` state, if any."""
    messages = state.get("messages") if isinstance(state, dict) else None
    if not messages:
        return None
    last = messages[-1]
    if isinstance(last, BaseMessage):
        return extract_text(last.content)
    return None
