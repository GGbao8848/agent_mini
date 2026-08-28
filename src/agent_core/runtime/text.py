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


def last_message_text(state: Any) -> str | None:
    """Text of the last message in a ``{'messages': [...]}`` state, if any."""
    messages = state.get("messages") if isinstance(state, dict) else None
    if not messages:
        return None
    last = messages[-1]
    if isinstance(last, BaseMessage):
        return extract_text(last.content)
    return None
