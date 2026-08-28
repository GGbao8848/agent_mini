"""Resilience policies: declarative agent-level reliability and cost guards.

Pure data — the runtime layer maps these onto LangChain's native agent
middleware (SummarizationMiddleware, ModelCallLimitMiddleware,
ToolRetryMiddleware, ModelRetryMiddleware, ModelFallbackMiddleware). Nothing
here re-implements what the framework already provides; the policies only
expose the knobs in the domain model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SummarizationPolicy(BaseModel):
    """Context-window policy: when to summarize the conversation history.

    Exactly one trigger clause must be set. ``keep_messages`` controls how
    many recent messages survive a summarization.
    """

    trigger_tokens: int | None = Field(default=None, gt=0)
    trigger_messages: int | None = Field(default=None, gt=0)
    trigger_fraction: float | None = Field(default=None, gt=0, le=1.0)
    keep_messages: int = Field(default=20, ge=1)

    @model_validator(mode="after")
    def _exactly_one_trigger(self) -> SummarizationPolicy:
        set_triggers = [
            name
            for name in ("trigger_tokens", "trigger_messages", "trigger_fraction")
            if getattr(self, name) is not None
        ]
        if len(set_triggers) != 1:
            raise ValueError(
                "exactly one of trigger_tokens/trigger_messages/trigger_fraction is required"
            )
        return self


class ResiliencePolicy(BaseModel):
    """Agent-level resilience knobs, backed by native middleware at build time."""

    summarization: SummarizationPolicy | None = None
    model_call_limit: int | None = Field(default=None, ge=1)
    call_limit_exit: Literal["end", "error"] = "end"
    tool_retries: int = Field(default=0, ge=0, le=5)
    model_retries: int = Field(default=0, ge=0, le=5)
    model_fallbacks: list[str] = Field(
        default_factory=list, description="Fallback model specs, tried in order"
    )

    @property
    def enabled(self) -> bool:
        """True when any knob is configured (avoid empty middleware wrappers)."""
        return bool(
            self.summarization is not None
            or self.model_call_limit is not None
            or self.tool_retries
            or self.model_retries
            or self.model_fallbacks
        )
