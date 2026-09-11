"""Capture non-standard reasoning deltas from OpenAI-compatible streams.

Reasoning models served behind the Chat Completions API stream their
chain-of-thought in a field that is not part of the OpenAI schema: vLLM emits
``delta.reasoning``, DeepSeek (and vLLM with the matching flag) emits
``delta.reasoning_content``. ``langchain-openai``'s chunk parser only reads
``content``/``tool_calls``, so those deltas are dropped before any callback
sees them — the console's 思考 stream then shows only the final answer and the
model looks like it never thought.

:class:`ReasoningChatOpenAI` keeps the deltas as they arrive, attached to each
streamed generation chunk's ``generation_info`` (a transport-only field, so it
is *not* persisted into message history and never sent back to the provider on
the next turn). :func:`generation_chunk_reasoning` reads them back in
:class:`~agent_core.runtime.thinking.ThinkingStreamHandler`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from langchain_core.outputs import ChatGenerationChunk
from langchain_openai import ChatOpenAI

_REASONING_KEYS = ("reasoning_content", "reasoning")
"""Delta keys seen in the wild, most specific first."""

_REASONING_INFO_KEY = "reasoning_content"
"""Key this module stashes the delta under on ``generation_info``."""


def reasoning_delta(raw_chunk: Mapping[str, Any]) -> str:
    """Return the reasoning text carried by one raw SSE chunk, if any."""
    choices = raw_chunk.get("choices") or []
    if not choices:
        return ""
    delta = (choices[0] or {}).get("delta") or {}
    for key in _REASONING_KEYS:
        value = delta.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def generation_chunk_reasoning(chunk: Any) -> str:
    """Return the reasoning text on a streamed ``ChatGenerationChunk``."""
    info = getattr(chunk, "generation_info", None) or {}
    value = info.get(_REASONING_INFO_KEY)
    return value if isinstance(value, str) else ""


class ReasoningChatOpenAI(ChatOpenAI):
    """ChatOpenAI that preserves non-standard reasoning deltas while streaming.

    Both the sync and async Chat Completions loops funnel every parsed chunk
    through ``_convert_chunk_to_generation_chunk``, so overriding that one
    method covers ``invoke``/``stream``/``ainvoke``/``astream`` alike.
    """

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict[str, Any],
        default_chunk_class: type,
        base_generation_info: dict[str, Any] | None,
    ) -> ChatGenerationChunk | None:
        generation_chunk = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if generation_chunk is None:
            return None
        text = reasoning_delta(chunk)
        if text:
            generation_chunk.generation_info = {
                **(generation_chunk.generation_info or {}),
                _REASONING_INFO_KEY: text,
            }
        return generation_chunk
