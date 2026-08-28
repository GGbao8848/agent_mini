"""Unit tests for ActionPolicy, ActionGate and the approval flow."""

import asyncio
from typing import Any

import pytest

from agent_core.domain.action import ApprovalStatus, RiskLevel
from agent_core.domain.agent import AgentSpec
from agent_core.domain.permission import PermissionDecision, PermissionRule, PermissionSpec
from agent_core.domain.task import Run, RunStatus
from agent_core.domain.tool import ToolDefinition
from agent_core.domain.trace import EventType
from agent_core.errors.exceptions import (
    ApprovalRejectedError,
    PermissionDeniedError,
    RegistryError,
    ToolError,
    ToolInvalidArgumentsError,
    ToolTimeoutError,
)
from agent_core.observability.emitter import EventFanout
from agent_core.observability.events import EventBus
from agent_core.observability.trace import InMemoryTracer
from agent_core.permissions import ActionGate, ActionPolicy, ApprovalManager
from agent_core.registries import AgentRegistry, ToolRegistry
from agent_core.runtime.context import current_run
from agent_core.runtime.tool_executor import ToolExecutor
from agent_core.runtime.tooling import make_gated_tool

WEATHER_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
}


def weather_definition(risk_level: RiskLevel = RiskLevel.LOW) -> ToolDefinition:
    return ToolDefinition(
        name="get_weather",
        description="Weather lookup",
        risk_level=risk_level,
        input_schema=WEATHER_SCHEMA,
    )


def make_gate(
    *,
    risk_level: RiskLevel = RiskLevel.LOW,
    rules: list[PermissionRule] | None = None,
    handler: Any = None,
    executor: ToolExecutor | None = None,
) -> tuple[ActionGate, ToolRegistry, ApprovalManager, InMemoryTracer]:
    agents = AgentRegistry()
    agents.register(
        AgentSpec(id="helper", name="Helper", permissions=PermissionSpec(rules=rules or []))
    )
    tools = ToolRegistry()
    tools.register(
        weather_definition(risk_level),
        handler if handler is not None else (lambda city: f"{city}: sunny"),
    )
    tracer = InMemoryTracer()
    approvals = ApprovalManager()
    gate = ActionGate(
        agents,
        tools,
        ActionPolicy(),
        approvals,
        executor or ToolExecutor(),
        EventFanout(tracer, EventBus()),
    )
    return gate, tools, approvals, tracer


def make_run() -> Run:
    run = Run(task_id="t1", agent_id="helper")
    run.transition_to(RunStatus.RUNNING)
    return run


def event_types(tracer: InMemoryTracer, run_id: str) -> list[EventType]:
    return [event.event_type for event in tracer.get_events(run_id)]


class TestActionPolicy:
    def test_low_risk_defaults_to_allow(self) -> None:
        policy = ActionPolicy()
        spec = AgentSpec(id="a", name="A")
        assert policy.evaluate(spec, weather_definition(RiskLevel.LOW)) is PermissionDecision.ALLOW
        assert (
            policy.evaluate(spec, weather_definition(RiskLevel.MEDIUM))
            is PermissionDecision.ALLOW
        )

    def test_high_and_critical_rise_above_floor(self) -> None:
        policy = ActionPolicy()
        spec = AgentSpec(id="a", name="A")
        assert (
            policy.evaluate(spec, weather_definition(RiskLevel.HIGH))
            is PermissionDecision.REQUIRE_APPROVAL
        )
        assert (
            policy.evaluate(spec, weather_definition(RiskLevel.CRITICAL))
            is PermissionDecision.REQUIRE_APPROVAL
        )

    def test_explicit_allow_cannot_bypass_floor(self) -> None:
        policy = ActionPolicy()
        spec = AgentSpec(
            id="a", name="A", permissions=PermissionSpec(default=PermissionDecision.ALLOW)
        )
        assert (
            policy.evaluate(spec, weather_definition(RiskLevel.CRITICAL))
            is PermissionDecision.REQUIRE_APPROVAL
        )

    def test_deny_wins_over_risk_floor(self) -> None:
        policy = ActionPolicy()
        spec = AgentSpec(
            id="a",
            name="A",
            permissions=PermissionSpec(
                rules=[PermissionRule(tool="get_weather", decision=PermissionDecision.DENY)]
            ),
        )
        assert policy.evaluate(spec, weather_definition(RiskLevel.LOW)) is PermissionDecision.DENY


class TestActionGate:
    async def test_low_risk_allow_executes_immediately(self) -> None:
        gate, _, approvals, tracer = make_gate()
        run = make_run()

        result = await gate.execute(run=run, tool_name="get_weather", arguments={"city": "Oslo"})

        assert result == "Oslo: sunny"
        assert approvals.list_pending() == []
        assert event_types(tracer, run.id) == [
            EventType.TOOL_REQUESTED,
            EventType.TOOL_STARTED,
            EventType.TOOL_EXECUTED,
        ]

    async def test_deny_blocks_execution(self) -> None:
        gate, _, _, tracer = make_gate(
            rules=[PermissionRule(tool="get_weather", decision=PermissionDecision.DENY)]
        )
        run = make_run()

        with pytest.raises(PermissionDeniedError):
            await gate.execute(run=run, tool_name="get_weather", arguments={"city": "Oslo"})

        assert EventType.TOOL_STARTED not in event_types(tracer, run.id)
        assert EventType.ACTION_REJECTED in event_types(tracer, run.id)

    async def test_high_risk_requires_approval_then_executes(self) -> None:
        gate, _, approvals, tracer = make_gate(risk_level=RiskLevel.HIGH)
        run = make_run()

        task = asyncio.create_task(
            gate.execute(run=run, tool_name="get_weather", arguments={"city": "Oslo"})
        )
        await asyncio.sleep(0.05)
        pending = approvals.list_pending()
        assert len(pending) == 1
        assert run.status is RunStatus.WAITING_APPROVAL
        approvals.resolve(pending[0].id, ApprovalStatus.APPROVED)

        assert await task == "Oslo: sunny"
        assert run.status is RunStatus.RUNNING
        types = event_types(tracer, run.id)
        assert EventType.ACTION_PENDING in types
        assert EventType.ACTION_APPROVED in types

    async def test_edited_arguments_are_used(self) -> None:
        gate, _, approvals, _ = make_gate(risk_level=RiskLevel.HIGH)
        run = make_run()

        task = asyncio.create_task(
            gate.execute(run=run, tool_name="get_weather", arguments={"city": "Oslo"})
        )
        await asyncio.sleep(0.05)
        request = approvals.list_pending()[0]
        approvals.resolve(request.id, ApprovalStatus.EDITED, edited_arguments={"city": "Bergen"})

        assert await task == "Bergen: sunny"

    async def test_rejected_approval_fails_closed_and_restores_run(self) -> None:
        gate, _, approvals, _ = make_gate(risk_level=RiskLevel.HIGH)
        run = make_run()

        task = asyncio.create_task(
            gate.execute(run=run, tool_name="get_weather", arguments={"city": "Oslo"})
        )
        await asyncio.sleep(0.05)
        approvals.resolve(approvals.list_pending()[0].id, ApprovalStatus.REJECTED)

        with pytest.raises(ApprovalRejectedError):
            await task
        # Run is back to RUNNING so it can legally reach a terminal state.
        assert run.status is RunStatus.RUNNING

    async def test_tool_failure_is_normalized(self) -> None:
        def bad_handler(city: str) -> str:
            raise ValueError("boom")

        gate, _, _, tracer = make_gate(handler=bad_handler)
        run = make_run()

        with pytest.raises(ToolError) as excinfo:
            await gate.execute(run=run, tool_name="get_weather", arguments={"city": "Oslo"})
        assert "boom" in str(excinfo.value)
        assert EventType.TOOL_FAILED in event_types(tracer, run.id)

    async def test_invalid_arguments_raise_invalid_arguments_error(self) -> None:
        gate, _, _, _ = make_gate()
        run = make_run()

        with pytest.raises(ToolInvalidArgumentsError):
            await gate.execute(run=run, tool_name="get_weather", arguments={"wrong": 1})

    async def test_tool_timeout(self) -> None:
        async def slow_handler(city: str) -> str:
            await asyncio.sleep(5)

        gate, _, _, _ = make_gate(
            handler=slow_handler, executor=ToolExecutor(default_timeout_seconds=0.05)
        )
        run = make_run()

        with pytest.raises(ToolTimeoutError):
            await gate.execute(run=run, tool_name="get_weather", arguments={"city": "Oslo"})

    async def test_unknown_tool_raises(self) -> None:
        gate, _, _, _ = make_gate()
        run = make_run()

        with pytest.raises(RegistryError):
            await gate.execute(run=run, tool_name="missing", arguments={})


class TestGatedTool:
    async def test_requires_run_context(self) -> None:
        gate, _, _, _ = make_gate()
        tool = make_gated_tool(weather_definition(), None, gate=gate)

        with pytest.raises(Exception, match="outside a run"):
            await tool.ainvoke({"city": "Oslo"})

    async def test_routes_through_gate(self) -> None:
        gate, _, approvals, tracer = make_gate()
        run = make_run()
        tool = make_gated_tool(weather_definition(), None, gate=gate)

        token = current_run.set(run)
        try:
            result = await tool.ainvoke({"city": "Oslo"})
        finally:
            current_run.reset(token)

        assert result == "Oslo: sunny"
        assert approvals.list_pending() == []
        assert EventType.TOOL_EXECUTED in event_types(tracer, run.id)
