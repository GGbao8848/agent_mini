"""Context variables identifying the Run / Agent for the current async task.

DeepAgents (and LangGraph) invoke tools deep inside their own execution;
context vars are the only reliable way for a tool wrapper to know which run it
serves — including nested sub-agent invocations, which inherit the context.
"""

from __future__ import annotations

from contextvars import ContextVar

current_run_id: ContextVar[str | None] = ContextVar("current_run_id", default=None)
current_agent_id: ContextVar[str | None] = ContextVar("current_agent_id", default=None)
