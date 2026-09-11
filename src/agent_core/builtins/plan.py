"""The ``update_plan`` built-in tool (R21): the agent's explicit step plan.

The runtime derives *facts* (status, failures, artifacts) from events, but the
*intent* — what the task's steps are and which one is in flight — can only come
from the agent. This tool is that channel: the agent declares the plan, the
resulting ``plan_updated`` event is folded into the persisted :class:`TaskState`
by the reducer, and the state is rendered back into the system prompt next turn.

It is LOW risk and side-effect free (it never touches the host/workspace), so it
needs no approval — its only effect lands in the task state.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.action import RiskLevel
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.domain.trace import EventType
from agent_core.errors.exceptions import ToolError

UPDATE_PLAN_TOOL = "update_plan"

_DESCRIPTION = (
    "记录/更新本任务的执行计划与进度（长任务、多步骤任务建议使用）。传入完整的 "
    "steps 列表：已经完成的步骤放在前面、当前正在做的步骤用 current_index 指定、"
    "尚未开始的排在后面。每次进度变化（完成一步、改变下一步）都调用一次，"
    "系统会把这份计划作为权威进度记录注入后续上下文，减少重复劳动。"
    "步骤要具体、可验证（例如“读取 report.pdf 提取数据”“生成 summary.xlsx”）。"
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "description": (
                "按执行顺序排列的完整步骤列表（包含已完成和未完成的）。"
                "每项写成字符串，或带 description 字段的对象。"
            ),
            "items": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "一句话描述这一步要做什么，尽量可验证",
                    },
                    "tool": {
                        "type": "string",
                        "description": "预计使用的工具名（可选）",
                    },
                },
                "required": ["description"],
            },
        },
        "current_index": {
            "type": "integer",
            "description": (
                "当前正在执行的步骤序号（0 开始）。它之前的步骤视为已完成，"
                "之后的视为未开始。全部完成时省略。"
            ),
        },
        "goal": {
            "type": "string",
            "description": "任务目标（可选；仅在你判断目标有变化或首次记录时传）",
        },
        "next_action": {
            "type": "string",
            "description": "下一步具体动作（可选）",
        },
        "decisions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "本次要追加记录的关键决定/取舍（可选）",
        },
    },
    "required": ["steps"],
}

# Keys a model has been observed to use for a step's text (the tool must be
# tolerant: real models do not follow the schema precisely — production traces
# showed "str", {step}, {text} and {description} across four attempts).
_DESCRIPTION_KEYS = ("description", "step", "text", "title", "name", "content")


def _normalize_steps(steps: Any) -> list[dict[str, Any]]:
    """Coerce whatever ``steps`` the model sent into ``{description, tool}`` dicts.

    Accepts a list of strings, or of dicts using any of the common key names for
    a step's text. Items that carry no usable text are dropped rather than
    failing the whole call — a partial plan is more useful than a tool error.
    """
    if not isinstance(steps, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in steps:
        if isinstance(item, str):
            text = item.strip()
            tool = None
        elif isinstance(item, dict):
            text = ""
            for key in _DESCRIPTION_KEYS:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    text = value.strip()
                    break
            tool = item.get("tool")
        else:
            continue
        if text:
            normalized.append({"description": text, "tool": tool})
    return normalized


def make_update_plan(fanout: Any) -> tuple[ToolDefinition, Any]:
    """Build the ``update_plan`` definition and handler.

    The handler emits ``plan_updated`` on ``fanout`` (the reducer and the
    console both consume that event) and returns a short confirmation.
    """

    async def update_plan(
        steps: list[dict[str, Any]],
        current_index: int | None = None,
        goal: str | None = None,
        next_action: str | None = None,
        decisions: list[str] | None = None,
    ) -> str:
        from agent_core.runtime.context import get_current_run

        run = get_current_run()
        if run is None:
            raise ToolError(
                "update_plan must run inside a task", details={"tool": UPDATE_PLAN_TOOL}
            )
        cleaned = _normalize_steps(steps)
        if not cleaned:
            raise ToolError(
                "update_plan requires at least one non-empty step",
                details={"tool": UPDATE_PLAN_TOOL},
            )
        index: int | None = (
            current_index
            if isinstance(current_index, int) and 0 <= current_index < len(cleaned)
            else None
        )
        fanout.emit(
            EventType.PLAN_UPDATED,
            run=run,
            agent_id=run.agent_id,
            tool=UPDATE_PLAN_TOOL,
            metadata={
                "steps": cleaned,
                "current_index": index,
                "goal": goal,
                "next_action": next_action,
                "decisions": [str(d) for d in (decisions or []) if str(d).strip()],
            },
        )
        total = len(cleaned)
        if index is None:
            return f"已记录计划：共 {total} 步。"
        return f"已记录计划：共 {total} 步，当前第 {index + 1} 步（前 {index} 步标记为已完成）。"

    definition = ToolDefinition(
        name=UPDATE_PLAN_TOOL,
        description=_DESCRIPTION,
        risk_level=RiskLevel.LOW,
        source=ToolSource.INTERNAL,
        input_schema=_SCHEMA,
        metadata={"builtin": True, "available": True},
    )
    return definition, update_plan
