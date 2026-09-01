"""Context variables identifying the Run / Task for the current async task.

DeepAgents (and LangGraph) invoke tools deep inside their own execution;
the context vars are the only reliable way for the Action Gate wrapper and
the builtin tool handlers to know which task they serve — sub-agent
invocations inherit the context automatically.
"""

from __future__ import annotations

from contextvars import ContextVar

from agent_core.domain.task import Run

current_run: ContextVar[Run | None] = ContextVar("current_run", default=None)
current_task_id: ContextVar[str | None] = ContextVar("current_task_id", default=None)
"""The conversation id of the run executing right now, or None outside a run.

Distinct from ``current_run`` so tool handlers can scope their output to the
task's private directory without depending on the whole Run object.
"""


def get_current_task_id() -> str | None:
    """The task id of the in-flight run, or None when not inside a run.

    Tools call this at invocation time (handlers are re-entered per call), so
    it reflects whichever task is executing right now — never a stale capture.
    """
    return current_task_id.get()
