"""Built-in ``save_memory`` tool: the agent's write side of long-term memory.

Memories are injected into every run's system prompt (see
:mod:`agent_core.domain.memory`), so one call here makes a fact durable
across conversations. Deletion and editing stay human-only (memory panel) —
the agent proposes, the human curates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.runtime.context import current_run

if TYPE_CHECKING:
    from agent_core.runtime.runtime import AgentRuntime

SAVE_MEMORY_TOOL_NAME = "save_memory"


class SaveMemoryInput(BaseModel):
    """Arguments for the save_memory tool."""

    content: str = Field(
        min_length=1,
        max_length=2000,
        description=(
            "The fact to remember, stated as one self-contained sentence "
            "(e.g. '用户偏好中文回复且要求示例代码可运行')."
        ),
    )


def make_save_memory(runtime: "AgentRuntime") -> tuple[ToolDefinition, Any]:
    """Build the ``(definition, handler)`` pair for the ToolRegistry."""

    async def save_memory(content: str) -> str:
        run = current_run.get()
        memory = runtime.add_memory(content, source="agent", task_id=run.task_id if run else None)
        return f"已记住：{memory.content}"

    # Risk-free: appending to a bounded list the human curates needs no approval.
    definition = ToolDefinition(
        name=SAVE_MEMORY_TOOL_NAME,
        description=(
            "Save a durable fact about the user or their projects to long-term "
            "memory (survives across conversations). Use it when the user states "
            "a preference, a project convention, or corrects a recurring mistake. "
            "Do not save transient task details."
        ),
        input_schema=SaveMemoryInput.model_json_schema(),
        source=ToolSource.INTERNAL,
        metadata={"timeout_seconds": 10},
    )
    return definition, save_memory
