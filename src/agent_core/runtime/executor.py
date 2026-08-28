"""AgentExecutor: invoke one built graph for one Run and trace the outcome.

The executor is deliberately dumb: it wraps a compiled graph with a timeout,
normalizes failures into the unified error model, extracts the final answer
and emits ``agent_*`` trace events. Lifecycle state is owned by AgentRuntime.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from langchain_core.messages import BaseMessage
from langgraph.graph.state import CompiledStateGraph

from agent_core.domain.agent import AgentSpec
from agent_core.domain.task import Run, Task
from agent_core.domain.trace import EventType
from agent_core.errors.exceptions import AgentError, AgentExecutionError, RunTimeoutError
from agent_core.observability.emitter import EventFanout

CompiledGraph = CompiledStateGraph[Any, Any, Any, Any]
"""Fully parameterized alias; concrete state types are DeepAgents internals."""


def extract_text(content: str | list[Any]) -> str:
    """Flatten LLM message content (string or content blocks) into plain text."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "".join(parts)


class AgentExecutor:
    """Executes a compiled graph for a single run."""

    def __init__(self, fanout: EventFanout | None = None) -> None:
        self._fanout = fanout or EventFanout()

    async def execute(
        self, graph: CompiledGraph, *, run: Run, task: Task, spec: AgentSpec
    ) -> str:
        """Run the graph to completion and return the agent's final text."""
        self._fanout.emit(
            EventType.AGENT_STARTED, run=run, agent_id=run.agent_id, input=task.input
        )
        started = time.monotonic()
        try:
            state = await asyncio.wait_for(
                graph.ainvoke({"messages": [{"role": "user", "content": task.input}]}),
                timeout=spec.limits.timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise RunTimeoutError(run.id, spec.limits.timeout_seconds) from exc
        except AgentError:
            raise
        except Exception as exc:
            raise AgentExecutionError(
                f"Agent execution failed: {exc}", details={"run_id": run.id}
            ) from exc

        output = self._final_output(state, run_id=run.id)
        self._fanout.emit(
            EventType.AGENT_FINISHED,
            run=run,
            agent_id=run.agent_id,
            output=output,
            duration_ms=(time.monotonic() - started) * 1000,
        )
        return output

    def _final_output(self, state: Any, *, run_id: str) -> str:
        messages = state.get("messages") if isinstance(state, dict) else None
        if not messages:
            raise AgentExecutionError("Agent returned no messages", details={"run_id": run_id})
        last = messages[-1]
        if not isinstance(last, BaseMessage):
            raise AgentExecutionError(
                "Agent's final message has an unexpected type",
                details={"run_id": run_id, "type": type(last).__name__},
            )
        return extract_text(last.content)
