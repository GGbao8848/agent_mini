"""Context builder (R20): assemble the prompt as ordered, budgeted sections.

The builder replaces the string concatenation that used to live in
:class:`~agent_core.runtime.builder.AgentBuilder`. Its job:

1. **Order** the sections deterministically (base instructions first, then
   environment, then the explicit task state, then retrieved memory, then the
   correction nudge) so the prompt is the same shape every turn.
2. **Budget** the droppable sections: retrieved memory and hints are useful but
   not load-bearing, so when they exceed the injected-text ceiling the
   lowest-priority sections are dropped *whole* (never mid-sentence) and the
   drop is recorded by name. The agent's own instructions are ``required`` and
   are never trimmed.
3. **Account** each section's size so the console can say where the context
   went — the proposal behind "why is this in the prompt?".

Deliberately pure and synchronous: the runtime resolves the async pieces
(memory retrieval) and hands the text in, so build() stays a cheap, testable
pure function over already-resolved strings.
"""

from __future__ import annotations

from agent_core.context.model import ContextSection, RuntimeContext, SectionKind
from agent_core.text.tokens import estimate_tokens

# Priorities: higher numbers survive a tight budget. The base prompt is never
# dropped (required); everything else competes for the injected-text budget.
_PRIORITY = {
    SectionKind.ENVIRONMENT: 80,
    SectionKind.TASK_STATE: 70,
    SectionKind.MEMORY: 40,
    SectionKind.LESSON: 30,
    SectionKind.AUTONOMY: 90,
    SectionKind.BUDGET: 20,
}


class ContextBuilder:
    """Composes the runtime system prompt from named sections."""

    def __init__(self, *, injected_budget: int | None = None) -> None:
        """``injected_budget`` caps the total tokens of droppable sections.

        ``None`` disables trimming (the default: today's behaviour, everything
        included). A number turns the builder into a guard against runaway
        memory/hint injection.
        """
        self._injected_budget = injected_budget

    def build(
        self,
        *,
        system_prompt: str = "",
        autonomy: str = "",
        environment: str = "",
        task_state: str = "",
        memory: str = "",
        lesson: str = "",
    ) -> RuntimeContext:
        """Assemble the ordered, budgeted runtime context."""
        candidates = [
            ContextSection(
                kind=SectionKind.SYSTEM,
                text=system_prompt,
                priority=1000,
                required=True,
                source="agent.system_prompt",
            ),
            ContextSection(
                kind=SectionKind.AUTONOMY,
                text=autonomy,
                priority=_PRIORITY[SectionKind.AUTONOMY],
                source="autonomy addendum + request_help rules",
            ),
            ContextSection(
                kind=SectionKind.ENVIRONMENT,
                text=environment,
                priority=_PRIORITY[SectionKind.ENVIRONMENT],
                source="runtime.paths.environment_note",
            ),
            ContextSection(
                kind=SectionKind.TASK_STATE,
                text=task_state,
                priority=_PRIORITY[SectionKind.TASK_STATE],
                source="task_state.prompt_block",
            ),
            ContextSection(
                kind=SectionKind.MEMORY,
                text=memory,
                priority=_PRIORITY[SectionKind.MEMORY],
                source="memory.aretrieve (top-k)",
            ),
            ContextSection(
                kind=SectionKind.LESSON,
                text=lesson,
                priority=_PRIORITY[SectionKind.LESSON],
                source="memory.lesson.lesson_hint",
            ),
        ]
        present = [section for section in candidates if section.text]
        kept, dropped = self._apply_budget(present)
        return RuntimeContext(
            sections=kept,
            dropped=dropped,
            injected_budget=self._injected_budget,
        )

    # ----------------------------------------------------------------- budget

    def _apply_budget(
        self, sections: list[ContextSection]
    ) -> tuple[list[ContextSection], list[str]]:
        """Drop the lowest-priority optional sections until the budget fits.

        Sections are dropped whole in ascending priority order (a truncated
        sentence is worse than an absent one), and the result is re-sorted back
        into the canonical order the sections were supplied in.
        """
        if self._injected_budget is None:
            return sections, []
        total = sum(s.tokens for s in sections if not s.required)
        if total <= self._injected_budget:
            return sections, []

        droppable = sorted(
            (s for s in sections if not s.required),
            key=lambda s: s.priority,
        )
        dropped: list[str] = []
        for section in droppable:
            if total <= self._injected_budget:
                break
            total -= section.tokens
            dropped.append(section.kind.value)
            sections = [s for s in sections if s is not section]
        return sections, dropped


def estimate_sections(sections: list[ContextSection]) -> int:
    """Total estimated tokens across ``sections`` (helper for callers)."""
    return sum(section.tokens for section in sections)


def section_from_text(
    kind: SectionKind, text: str, *, source: str = ""
) -> ContextSection:
    """Build one section with an estimated token count (convenience)."""
    tokens = estimate_tokens(text)
    return ContextSection(kind=kind, text=text, source=source, tokens=tokens)
