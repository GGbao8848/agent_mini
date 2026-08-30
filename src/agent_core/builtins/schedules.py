"""Built-in ``create_schedule`` tool: the agent turns a request into a schedule.

The agent understands the user's intent in conversation and calls this tool
to create a recurring or one-time automation. The schedule runs the same
conversation path as a manual task (creates a Task and starts it), so the
result shows up in the console and can be continued by hand. Because the
"empty tools = all tools" policy exposes every registered tool to agents with
no explicit binding, this is available to the avatar out of the box.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_core.domain.schedule import Schedule
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import RegistryError, ScheduleError, ToolError

if TYPE_CHECKING:
    from agent_core.application.service import AgentCoreService
    from agent_core.runtime.runtime import AgentRuntime
    from agent_core.runtime.context import ContextVar

CREATE_SCHEDULE_TOOL = "create_schedule"

_DESCRIPTION = (
    "Create a schedule that runs an agent task automatically. "
    "Use one of: schedule_type='one_time' with run_at (ISO datetime), "
    "'cron' with cron_expr (5-field: minute hour day-of-month month day-of-week), "
    "or 'interval' with interval_minutes. The task runs as a new conversation "
    "for the given agent (default: the current agent)."
)


def make_create_schedule(service: "AgentCoreService") -> tuple[ToolDefinition, Any]:
    """Handler bound to the service's schedule manager."""

    async def create_schedule(
        name: str,
        task_input: str,
        schedule_type: str,
        run_at: str | None = None,
        cron_expr: str | None = None,
        interval_minutes: int | None = None,
        agent_id: str | None = None,
        enabled: bool = True,
    ) -> str:
        runtime: AgentRuntime = service.runtime
        active_agent = agent_id or _current_agent(runtime)
        schedule = Schedule(
            name=name,
            agent_id=active_agent,
            task_input=task_input,
            schedule_type=schedule_type,  # type: ignore[arg-type]
            run_at=_parse_datetime(run_at),
            cron_expr=cron_expr,
            interval_minutes=interval_minutes,
            enabled=enabled,
        )
        try:
            service.create_schedule(schedule)
        except ScheduleError as exc:
            raise ToolError(f"Could not create schedule: {exc.message}") from exc
        return (
            f"Schedule '{schedule.name}' created ({schedule.describe_trigger()}, "
            f"agent '{active_agent}'). It runs task: {task_input}"
        )

    definition = ToolDefinition(
        name=CREATE_SCHEDULE_TOOL,
        description=_DESCRIPTION,
        source=ToolSource.INTERNAL,
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable schedule name"},
                "task_input": {"type": "string", "description": "The task text to run"},
                "schedule_type": {
                    "type": "string",
                    "enum": ["one_time", "cron", "interval"],
                },
                "run_at": {
                    "type": "string",
                    "description": "ISO datetime for one_time, e.g. 2026-09-01T09:00:00",
                },
                "cron_expr": {
                    "type": "string",
                    "description": "5-field cron for cron type",
                },
                "interval_minutes": {
                    "type": "integer",
                    "description": "Minutes between runs for interval type",
                },
                "agent_id": {
                    "type": "string",
                    "description": "Agent to run (defaults to the calling agent)",
                },
                "enabled": {"type": "boolean", "description": "Start enabled (default true)"},
            },
            "required": ["name", "task_input", "schedule_type"],
        },
        metadata={"builtin": True, "available": True},
    )
    return definition, create_schedule


def _current_agent(runtime: "AgentRuntime") -> str:
    """Agent id of the run currently executing (default for the tool)."""
    try:
        from agent_core.runtime.context import current_run

        run = current_run.get()
        if run is not None:
            return run.agent_id
    except Exception:
        pass
    return "avatar"


def _parse_datetime(value: str | None) -> Any:
    """Parse an ISO datetime string into a tz-aware datetime, or None."""
    if not value:
        return None
    from datetime import datetime

    from tzlocal import get_localzone

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ToolError(f"Invalid run_at '{value}': expected ISO datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=get_localzone())
    return parsed
