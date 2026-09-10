"""Runtime context model (R20).

Today the system prompt is assembled by string concatenation scattered across
the builder: spec prompt, autonomy addendum, environment note, memory block,
task-state block, and (implicitly, in the harness) skill manifests and tool
schemas. That works, but it cannot answer the question this stage is about:

    **why is each piece of text in the prompt right now, and how big is it?**

:class:`RuntimeContext` is the explicit answer. A context is an *ordered list
of named sections*, each carrying its own token estimate, priority and source,
plus the rendered prompt they compose. Anything the model sees can then be
traced back to a section — and a section that is too expensive under the
budget can be dropped by name instead of silently bloating every request.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from agent_core.text.tokens import estimate_tokens


class SectionKind(StrEnum):
    """Where a prompt section comes from (stable labels for the console)."""

    SYSTEM = "system"
    AUTONOMY = "autonomy"
    ENVIRONMENT = "environment"
    TASK_STATE = "task_state"
    MEMORY = "memory"
    LESSON = "lesson"
    BUDGET = "budget"


class ContextSection(BaseModel):
    """One named block of the system prompt."""

    kind: SectionKind
    text: str
    priority: int = Field(
        default=50,
        description="Higher survives a tight budget; the base prompt is 1000.",
    )
    required: bool = Field(
        default=False,
        description="Never dropped by the budget (the agent's own instructions).",
    )
    source: str = Field(default="", description="Free-form provenance for display")
    tokens: int = 0

    def model_post_init(self, _context: Any) -> None:
        if not self.tokens:
            self.tokens = estimate_tokens(self.text)


class RuntimeContext(BaseModel):
    """The assembled system-prompt context for one run."""

    sections: list[ContextSection] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)
    """Section kinds removed to fit the injected-text budget."""

    injected_budget: int | None = None
    """Token ceiling for non-required sections, when one was applied."""

    @property
    def prompt(self) -> str:
        """The rendered system prompt (sections in order, no separators added)."""
        return "".join(section.text for section in self.sections)

    @property
    def injected_tokens(self) -> int:
        """Tokens of the non-required (droppable) sections only."""
        return sum(s.tokens for s in self.sections if not s.required)

    @property
    def total_tokens(self) -> int:
        return sum(section.tokens for section in self.sections)

    def breakdown(self) -> dict[str, int]:
        """Per-kind token counts, for ``run.metadata["context_sections"]``."""
        out: dict[str, int] = {}
        for section in self.sections:
            out[section.kind.value] = out.get(section.kind.value, 0) + section.tokens
        return out

    def explain(self) -> list[dict[str, Any]]:
        """Human-readable account of what is in the prompt and why."""
        return [
            {
                "kind": s.kind.value,
                "tokens": s.tokens,
                "priority": s.priority,
                "required": s.required,
                "source": s.source,
            }
            for s in self.sections
        ]
