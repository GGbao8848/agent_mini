"""Built-in ``remember`` tool: the agent's explicit long-term memory write.

Deliberately *explicit*: the agent calls this when the user says "remember
this" or states a durable preference/fact — there is no silent per-turn
extraction (that design was rolled back as noisy). Duplicate content refreshes
the existing entry instead of creating a twin, and the write is LOW risk
because it only touches the memory store, never the host or the workspace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_core.domain.action import RiskLevel
from agent_core.domain.memory import MemoryScope, MemoryType
from agent_core.domain.tool import ToolDefinition, ToolSource

if TYPE_CHECKING:
    from agent_core.memory.service import MemoryService

REMEMBER_TOOL = "remember"

_DESCRIPTION = (
    "Save a durable fact, preference, decision or lesson to long-term memory so "
    "it is available in future conversations. Use it when the user says to "
    "remember something, states a lasting preference, or you learn a project "
    "constraint worth keeping. Do NOT use it for one-off task details or "
    "transient instructions ('do X for now')."
)

_SCOPE_VALUES = [s.value for s in MemoryScope]
_TYPE_VALUES = [t.value for t in MemoryType]


def make_remember(service: MemoryService) -> tuple[ToolDefinition, Any]:
    async def remember(
        content: str,
        scope: str = MemoryScope.USER.value,
        type: str = MemoryType.FACT.value,
    ) -> str:
        selected_scope = next(
            (s for s in MemoryScope if s.value == scope), MemoryScope.USER
        )
        selected_type = next((t for t in MemoryType if t.value == type), MemoryType.FACT)
        memory = service.add(
            content,
            scope=selected_scope,
            type=selected_type,
            source="agent",
        )
        return (
            f"Saved to long-term memory ({selected_scope.value}/{selected_type.value}): "
            f"{memory.content}"
        )

    definition = ToolDefinition(
        name=REMEMBER_TOOL,
        description=_DESCRIPTION,
        risk_level=RiskLevel.LOW,
        source=ToolSource.INTERNAL,
        input_schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The fact/preference/lesson to remember, one sentence",
                },
                "scope": {
                    "type": "string",
                    "enum": _SCOPE_VALUES,
                    "description": "Who it is about (default user)",
                },
                "type": {
                    "type": "string",
                    "enum": _TYPE_VALUES,
                    "description": "Kind of memory (default fact)",
                },
            },
            "required": ["content"],
        },
        metadata={"builtin": True, "available": True},
    )
    return definition, remember
