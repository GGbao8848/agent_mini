"""Context variable identifying the Run for the current async task.

DeepAgents (and LangGraph) invoke tools deep inside their own execution;
the context var is the only reliable way for the Action Gate wrapper to know
which run it serves — sub-agent invocations inherit the context automatically.
"""

from __future__ import annotations

from contextvars import ContextVar

from agent_core.domain.task import Run

current_run: ContextVar[Run | None] = ContextVar("current_run", default=None)
