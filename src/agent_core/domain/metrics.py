"""Resource-consumption metrics for one run.

Pure data: extraction from framework objects (LangChain messages, LLM
results) lives in the runtime layer. A run's usage covers everything the run
itself and its delegated subagents consumed — the numbers used to judge
whether an orchestration strategy is actually cheaper or faster.
"""

from __future__ import annotations

from pydantic import BaseModel


class RunUsage(BaseModel):
    """Aggregated token/call counts for a run (including subagents)."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    duration_ms: float | None = None

    def add(self, other: RunUsage) -> None:
        """Accumulate ``other`` into this instance (in place)."""
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens
        self.model_calls += other.model_calls
        self.tool_calls += other.tool_calls
