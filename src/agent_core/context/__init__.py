"""Runtime Context (R20): explicit, ordered, budgeted prompt assembly.

The system prompt is a list of named sections composed by
:class:`agent_core.context.builder.ContextBuilder`, not an ad-hoc sequence of
string concatenations. Each section is estimated and prioritised, so the
runtime can account for what is in the prompt and drop the optional parts when
the injected-text budget is exceeded.
"""

from agent_core.context.builder import ContextBuilder, estimate_sections, section_from_text
from agent_core.context.model import ContextSection, RuntimeContext, SectionKind

__all__ = [
    "ContextBuilder",
    "ContextSection",
    "RuntimeContext",
    "SectionKind",
    "estimate_sections",
    "section_from_text",
]
