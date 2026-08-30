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
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from agent_core.domain.agent import AgentSpec
from agent_core.domain.task import Run
from agent_core.domain.trace import EventType
from agent_core.errors.exceptions import AgentError, AgentExecutionError, RunTimeoutError
from agent_core.observability.emitter import EventFanout
from agent_core.runtime.subagent_trace import SubagentTraceHandler
from agent_core.runtime.text import extract_text
from agent_core.runtime.usage import UsageCollector

CompiledGraph = CompiledStateGraph[Any, Any, Any, Any]
"""Fully parameterized alias; concrete state types are DeepAgents internals."""

__all__ = ["AgentExecutor", "extract_text"]


class AgentExecutor:
    """Executes a compiled graph for a single run."""

    def __init__(self, fanout: EventFanout | None = None) -> None:
        self._fanout = fanout or EventFanout()

    async def execute(
        self,
        graph: CompiledGraph,
        *,
        run: Run,
        input_text: str,
        spec: AgentSpec,
        collector: UsageCollector | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Run the graph to completion and return the agent's final text.

        ``collector`` lets the caller own the usage accounting (the runtime
        registers a run-scoped collector so budget middleware can read live
        usage mid-run); without one a local collector is used.
        """
        usage_collector = collector or UsageCollector()
        self._fanout.emit(
            EventType.AGENT_STARTED, run=run, agent_id=run.agent_id, input=input_text
        )
        started = time.monotonic()
        callbacks: list[Any] = [usage_collector]
        if spec.subagents:
            callbacks.append(
                SubagentTraceHandler(
                    self._fanout, run, {ref.agent_id for ref in spec.subagents}
                )
            )
        try:
            config: RunnableConfig = {"callbacks": callbacks}
            if thread_id is not None:
                # Same thread → LangGraph replays the stored conversation, so
                # follow-up messages continue where the previous run stopped.
                config["configurable"] = {"thread_id": thread_id}
            state = await asyncio.wait_for(
                graph.ainvoke(
                    {"messages": [{"role": "user", "content": input_text}]},
                    config=config,
                ),
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
        finally:
            # Partial usage survives failures; consumers still see the cost.
            run.usage = usage_collector.usage

        output = self._final_output(state, run_id=run.id)
        run.usage.duration_ms = (time.monotonic() - started) * 1000
        self._fanout.emit(
            EventType.AGENT_FINISHED,
            run=run,
            agent_id=run.agent_id,
            output=output,
            duration_ms=run.usage.duration_ms,
            metadata={"usage": run.usage.model_dump()},
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
