"""Streamed-model-token capture: forward LLM output as ``agent_thinking`` events.

Requires the chat model to run with ``streaming=True`` (see
``Settings.model_streaming``): LangChain then invokes ``on_llm_new_token`` per
token on the run's callback chain, and this handler forwards the text as
``agent_thinking`` trace deltas so the console can show the avatar composing
its reply in real time. Tokens are small-buffered (chars + time) so a long
answer does not become one SSE event per token.

Reasoning models (vLLM/DeepSeek behind the Chat Completions API) stream their
chain-of-thought in a non-standard delta field that ``on_llm_new_token`` never
sees. :class:`ReasoningChatOpenAI` stashes it on the chunk's ``generation_info``
and this handler emits it too, so the console's 思考 stream carries the actual
thinking rather than only the final answer. The two streams never overlap on
one chunk (a chunk is either a reasoning delta or a content delta).
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from agent_core.domain.task import Run
from agent_core.domain.trace import EventType
from agent_core.observability.emitter import EventFanout
from agent_core.runtime.reasoning import generation_chunk_reasoning

_FLUSH_CHARS = 32
_FLUSH_SECONDS = 0.6


class ThinkingStreamHandler(BaseCallbackHandler):
    """Buffer streamed tokens (and reasoning deltas) as agent_thinking events."""

    def __init__(self, fanout: EventFanout, run: Run) -> None:
        self._fanout = fanout
        self._run = run
        self._buffer: list[str] = []
        self._since = 0.0

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        text = generation_chunk_reasoning(kwargs.get("chunk")) or token
        if not text:
            return
        now = time.monotonic()
        buffered = sum(len(chunk) for chunk in self._buffer)
        if self._buffer and (
            now - self._since >= _FLUSH_SECONDS or buffered >= _FLUSH_CHARS
        ):
            self._flush()
        if not self._buffer:
            self._since = now
        self._buffer.append(text)

    def on_llm_end(self, *args: Any, **kwargs: Any) -> None:
        self._flush()

    def on_llm_error(self, *args: Any, **kwargs: Any) -> None:
        self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        chunk = "".join(self._buffer)
        self._buffer.clear()
        self._fanout.emit(
            EventType.AGENT_THINKING,
            run=self._run,
            agent_id=self._run.agent_id,
            output=chunk,
        )
