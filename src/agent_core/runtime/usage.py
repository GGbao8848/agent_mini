"""Usage extraction from LangChain callbacks.

LangChain's callback system is the one official seam that sees every model
and tool call in a delegation tree: deepagents propagates the parent's
callbacks into subagents, so a single collector attached to the root run
counts the whole tree — including subagent calls that never appear in the
parent's final state (context quarantine hides their messages, not their
cost).
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from agent_core.domain.metrics import RunUsage
from agent_core.runtime.context_breakdown import estimate_tokens
from agent_core.runtime.text import extract_text


class UsageCollector(BaseCallbackHandler):
    """Accumulates token and call counts for one run invocation."""

    def __init__(self) -> None:
        self._usage = RunUsage()

    @property
    def usage(self) -> RunUsage:
        """Snapshot of everything collected so far."""
        return self._usage.model_copy()

    def merge(self, extra: RunUsage) -> None:
        """Charge externally produced usage (e.g. a verification sub-run)."""
        self._usage.add(extra)

    def on_chat_model_start(
        self, serialized: Any = None, messages: Any = None, **kwargs: Any
    ) -> None:
        self._usage.model_calls += 1
        # Split the actual prompt into system vs conversation history so the
        # context gauge can show a per-part breakdown (heuristic estimates,
        # overwritten on every call — the latest prompt is the live context).
        system = 0
        conversation = 0
        flat = messages[0] if messages and isinstance(messages[0], list) else (messages or [])
        for message in flat:
            if not isinstance(message, BaseMessage):
                continue
            cost = estimate_tokens(extract_text(message.content))
            if getattr(message, "type", None) == "system":
                system += cost
            else:
                conversation += cost
        if system:
            self._usage.estimated_system_tokens = system
        if conversation:
            self._usage.estimated_messages_tokens = conversation

    def on_tool_end(self, *args: Any, **kwargs: Any) -> None:
        self._usage.tool_calls += 1

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        tokens = _tokens_from_result(response)
        self._usage.input_tokens += tokens["input"]
        self._usage.output_tokens += tokens["output"]
        self._usage.total_tokens += tokens["total"]
        # Overwrite, not accumulate: the newest call's prompt is the current
        # conversation replay (the context gauge reads this).
        if tokens["input"]:
            self._usage.last_input_tokens = tokens["input"]


def _tokens_from_result(response: LLMResult) -> dict[str, int]:
    """Prefer per-message usage_metadata; fall back to llm_output totals."""
    result = {"input": 0, "output": 0, "total": 0}
    for generation in response.generations:
        message = getattr(generation[0], "message", None) if generation else None
        usage = getattr(message, "usage_metadata", None) or {}
        result["input"] += int(usage.get("input_tokens") or 0)
        result["output"] += int(usage.get("output_tokens") or 0)
        result["total"] += int(usage.get("total_tokens") or 0)
    if result["total"] == 0:
        fallback = (response.llm_output or {}).get("token_usage") or {}
        result["input"] = int(fallback.get("prompt_tokens") or 0)
        result["output"] = int(fallback.get("completion_tokens") or 0)
        result["total"] = int(fallback.get("total_tokens") or 0)
    return result
