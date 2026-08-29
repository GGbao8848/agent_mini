"""Autonomy layer tests: budgets, loop guard, task-level help, self-verification.

The verification tests wire the real runtime with stub graphs (the builder
branches on spec.id so the verifier agent gets its own scripted graph) — the
same pattern as test_api.py.
"""

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from agent_core.api.schemas import ApprovalOut
from agent_core.domain.action import ApprovalRequest, ApprovalStatus
from agent_core.domain.agent import AgentSpec
from agent_core.domain.autonomy import (
    AutonomyPolicy,
    LoopGuardPolicy,
    RunBudget,
    VerificationPolicy,
)
from agent_core.domain.metrics import RunUsage
from agent_core.domain.task import Run, RunStatus
from agent_core.domain.tool import ToolDefinition
from agent_core.errors.exceptions import ApprovalRejectedError, StateError, ToolError
from agent_core.permissions.approval import ApprovalManager
from agent_core.permissions.loop_guard import LoopGuard
from agent_core.persistence.store import SqliteStore
from agent_core.registries import AgentRegistry, SkillRegistry, ToolRegistry
from agent_core.runtime.budget import BudgetMiddleware, budget_verdict
from agent_core.runtime.context import current_run
from agent_core.runtime.help_tool import make_help_tool
from agent_core.runtime.runtime import AgentRuntime

# ------------------------------------------------------------------- status


class TestNeedsInputTransitions:
    def test_running_to_needs_input_and_back(self) -> None:
        run = Run(task_id="t1", agent_id="helper")
        run.transition_to(RunStatus.RUNNING)
        run.transition_to(RunStatus.NEEDS_INPUT)
        assert run.status is RunStatus.NEEDS_INPUT
        assert not run.status.is_terminal
        run.transition_to(RunStatus.RUNNING)
        assert run.status is RunStatus.RUNNING

    def test_needs_input_can_be_cancelled_but_not_completed(self) -> None:
        run = Run(task_id="t1", agent_id="helper")
        run.transition_to(RunStatus.RUNNING)
        run.transition_to(RunStatus.NEEDS_INPUT)
        run.transition_to(RunStatus.CANCELLED)
        assert run.status.is_terminal

        run2 = Run(task_id="t2", agent_id="helper")
        run2.transition_to(RunStatus.RUNNING)
        run2.transition_to(RunStatus.NEEDS_INPUT)
        with pytest.raises(StateError):
            run2.transition_to(RunStatus.COMPLETED)


# ------------------------------------------------------------------ budgets


class TestBudgetVerdict:
    def test_no_usage_is_ok(self) -> None:
        assert budget_verdict(None, RunBudget(max_total_tokens=100)) == "ok"

    def test_stop_on_hard_limit(self) -> None:
        budget = RunBudget(max_total_tokens=100, max_model_calls=10)
        assert budget_verdict(RunUsage(total_tokens=100, model_calls=2), budget) == "stop"

    def test_warn_past_fraction(self) -> None:
        budget = RunBudget(max_total_tokens=100, warn_fraction=0.8)
        assert budget_verdict(RunUsage(total_tokens=79), budget) == "ok"
        assert budget_verdict(RunUsage(total_tokens=80), budget) == "warn"

    def test_tool_calls_counted(self) -> None:
        budget = RunBudget(max_tool_calls=5)
        assert budget_verdict(RunUsage(tool_calls=3), budget) == "ok"
        assert budget_verdict(RunUsage(tool_calls=4), budget) == "warn"
        assert budget_verdict(RunUsage(tool_calls=5), budget) == "stop"

    def test_unset_limits_never_stop(self) -> None:
        assert budget_verdict(RunUsage(total_tokens=10**9), RunBudget()) == "ok"


class _FakeRequest:
    def __init__(self) -> None:
        self.system_prompt = "base prompt"

    def override(self, **kwargs: Any) -> Any:
        return SimpleNamespace(system_prompt=kwargs["system_prompt"])


class TestBudgetMiddleware:
    def test_stop_returns_jump_to_end(self) -> None:
        mw = BudgetMiddleware(RunBudget(max_total_tokens=100), lambda: RunUsage(total_tokens=150))
        result = mw.before_model({}, None)
        assert result is not None
        assert result["jump_to"] == "end"
        assert "budget" in result["messages"][0].content.lower()

    def test_ok_returns_none(self) -> None:
        mw = BudgetMiddleware(RunBudget(max_total_tokens=100), lambda: RunUsage(total_tokens=10))
        assert mw.before_model({}, None) is None

    def test_warn_overrides_system_prompt_once(self) -> None:
        mw = BudgetMiddleware(RunBudget(max_total_tokens=100), lambda: RunUsage(total_tokens=90))
        handled: list[Any] = []
        mw.wrap_model_call(_FakeRequest(), handled.append)
        assert len(handled) == 1
        assert "base prompt" in handled[0].system_prompt
        assert "budget" in handled[0].system_prompt.lower()
        # The warning is injected once, not on every subsequent call.
        mw.wrap_model_call(_FakeRequest(), handled.append)
        assert handled[1].system_prompt == "base prompt"

    def test_usage_getter_invoked_every_check(self) -> None:
        usage = RunUsage(total_tokens=10)
        mw = BudgetMiddleware(RunBudget(max_total_tokens=100), lambda: usage)
        assert mw.before_model({}, None) is None
        usage.total_tokens = 500  # same mutable object, new reading
        assert mw.before_model({}, None) is not None


# --------------------------------------------------------------- loop guard


class TestLoopGuard:
    POLICY = LoopGuardPolicy(max_identical_calls=3, max_consecutive_failures=2)

    def test_identical_calls_allow_nudge_escalate(self) -> None:
        guard = LoopGuard()
        assert guard.check("r1", "search", {"q": "x"}, self.POLICY).action == "allow"
        guard.record_called("r1", "search", {"q": "x"})
        assert guard.check("r1", "search", {"q": "x"}, self.POLICY).action == "allow"
        guard.record_called("r1", "search", {"q": "x"})
        third = guard.check("r1", "search", {"q": "x"}, self.POLICY)
        assert third.action == "nudge"
        assert "NOT executed" in third.message
        fourth = guard.check("r1", "search", {"q": "x"}, self.POLICY)
        assert fourth.action == "escalate"

    def test_different_arguments_are_distinct(self) -> None:
        guard = LoopGuard()
        for query in ("a", "b", "c"):
            assert guard.check("r1", "search", {"q": query}, self.POLICY).action == "allow"
            guard.record_called("r1", "search", {"q": query})

    def test_consecutive_failures_reset_on_success(self) -> None:
        guard = LoopGuard()
        assert guard.record_result("r1", ok=False) == 1
        assert guard.record_result("r1", ok=False) == 2
        assert guard.record_result("r1", ok=True) == 0
        assert guard.record_result("r1", ok=False) == 1

    def test_forget_run_clears_state(self) -> None:
        guard = LoopGuard()
        guard.record_called("r1", "search", {"q": "x"})
        guard.record_result("r1", ok=False)
        guard.forget_run("r1")
        assert guard.check("r1", "search", {"q": "x"}, self.POLICY).action == "allow"
        assert guard.record_result("r1", ok=False) == 1


# ----------------------------------------------------- gate: soft deny/help


def gated_runtime(autonomy: AutonomyPolicy, handler: Any) -> AgentRuntime:
    agents = AgentRegistry()
    agents.register(AgentSpec(id="helper", name="Helper", tools=["box"], autonomy=autonomy))
    tools = ToolRegistry()
    tools.register(
        ToolDefinition(name="box", description="Box", input_schema={"type": "object"}),
        handler,
    )
    return AgentRuntime(agents, tools, SkillRegistry())


def running_run() -> Run:
    run = Run(task_id="t1", agent_id="helper")
    run.transition_to(RunStatus.RUNNING)
    return run


class TestGateLoopGuard:
    async def test_repeated_calls_nudge_then_escalate_and_answer_flows_back(self) -> None:
        runtime = gated_runtime(AutonomyPolicy(loop_guard=LoopGuardPolicy()), lambda **_: "ok")
        run = running_run()
        token = current_run.set(run)

        first = await runtime.gate.execute(run=run, tool_name="box", arguments={"q": 1})
        assert first == "ok"
        second = await runtime.gate.execute(run=run, tool_name="box", arguments={"q": 1})
        assert second == "ok"
        third = await runtime.gate.execute(run=run, tool_name="box", arguments={"q": 1})
        assert isinstance(third, str) and "NOT executed" in third
        assert run.status is RunStatus.RUNNING  # a nudge does not pause the run

        escalated = asyncio.create_task(
            runtime.gate.execute(run=run, tool_name="box", arguments={"q": 1})
        )
        await asyncio.sleep(0.01)
        assert run.status is RunStatus.NEEDS_INPUT
        (pending,) = runtime.approvals.list_pending()
        assert pending.kind.value == "task_help"
        assert "loop" in pending.question.lower()
        runtime.approvals.resolve(pending.id, ApprovalStatus.APPROVED, note="try fewer arguments")
        assert await escalated == "try fewer arguments"
        assert run.status is RunStatus.RUNNING
        current_run.reset(token)

    async def test_escalation_rejection_aborts_the_call(self) -> None:
        runtime = gated_runtime(AutonomyPolicy(loop_guard=LoopGuardPolicy()), lambda **_: "ok")
        run = running_run()
        token = current_run.set(run)
        await runtime.gate.execute(run=run, tool_name="box", arguments={"q": 1})
        await runtime.gate.execute(run=run, tool_name="box", arguments={"q": 1})
        await runtime.gate.execute(run=run, tool_name="box", arguments={"q": 1})  # nudged
        escalated = asyncio.create_task(
            runtime.gate.execute(run=run, tool_name="box", arguments={"q": 1})
        )
        await asyncio.sleep(0.01)
        (pending,) = runtime.approvals.list_pending()
        runtime.approvals.resolve(pending.id, ApprovalStatus.REJECTED)
        with pytest.raises(ApprovalRejectedError):
            await escalated
        current_run.reset(token)

    async def test_tool_failures_become_soft_messages_then_escalate(self) -> None:
        def failing(**_: Any) -> Any:
            raise RuntimeError("simulated outage")

        runtime = gated_runtime(
            AutonomyPolicy(loop_guard=LoopGuardPolicy(max_consecutive_failures=2)), failing
        )
        run = running_run()
        token = current_run.set(run)
        first = await runtime.gate.execute(run=run, tool_name="box", arguments={"q": 1})
        assert "simulated outage" in first
        assert "consecutive failures: 1/2" in first
        escalated = asyncio.create_task(
            runtime.gate.execute(run=run, tool_name="box", arguments={"q": 1})
        )
        await asyncio.sleep(0.01)
        (pending,) = runtime.approvals.list_pending()
        assert "failed 2 times" in pending.question
        runtime.approvals.resolve(pending.id, ApprovalStatus.APPROVED, note="restart it first")
        assert await escalated == "restart it first"
        current_run.reset(token)

    async def test_without_loop_guard_failures_stay_fail_closed(self) -> None:
        runtime = gated_runtime(AutonomyPolicy(), lambda **_: 1 / 0)
        run = running_run()
        token = current_run.set(run)
        with pytest.raises(ToolError):
            await runtime.gate.execute(run=run, tool_name="box", arguments={"q": 1})
        current_run.reset(token)


class TestRequestHelpTool:
    async def test_help_tool_returns_human_note(self) -> None:
        runtime = gated_runtime(AutonomyPolicy(), lambda **_: "ok")
        run = running_run()
        token = current_run.set(run)
        help_tool = make_help_tool(runtime.gate)

        pending_answer = asyncio.create_task(
            help_tool.coroutine(  # type: ignore[attr-defined]
                question="Which API key should I use?", context="both look valid"
            )
        )
        await asyncio.sleep(0.01)
        assert run.status is RunStatus.NEEDS_INPUT
        (pending,) = runtime.approvals.list_pending()
        assert pending.kind.value == "task_help"
        assert "API key" in pending.question
        runtime.approvals.resolve(pending.id, ApprovalStatus.APPROVED, note="use the staging key")
        assert await pending_answer == "use the staging key"
        assert run.status is RunStatus.RUNNING
        current_run.reset(token)


# ------------------------------------------------------------ verification


class ScriptedVerifierGraph:
    """Verifier graph returning pre-programmed overall scores in order."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = scores

    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        score = self._scores.pop(0) if self._scores else 10.0
        verdict = {"dimensions": {"accuracy": score, "completeness": score}, "overall": score}
        return {"messages": [AIMessage(content=json.dumps(verdict))]}


class EchoGraph:
    async def ainvoke(self, state: Any, config: Any = None) -> dict[str, Any]:
        content = state["messages"][-1]["content"]
        return {"messages": [AIMessage(content=f"out: {content}")]}


class BranchingBuilder:
    """Main agent gets EchoGraph, the verifier agent a scripted graph."""

    def __init__(self, verifier_scores: list[float]) -> None:
        self._verifier = ScriptedVerifierGraph(verifier_scores)

    def build(self, spec: Any) -> Any:
        return self._verifier if spec.id == "verifier" else EchoGraph()


def verify_runtime(scores: list[float], policy: VerificationPolicy) -> AgentRuntime:
    agents = AgentRegistry()
    agents.register(
        AgentSpec(id="helper", name="Helper", autonomy=AutonomyPolicy(verification=policy))
    )
    return AgentRuntime(
        agents, ToolRegistry(), SkillRegistry(), builder=BranchingBuilder(scores)
    )


async def resolve_when_pending(runtime: AgentRuntime, **resolve_kwargs: Any) -> None:
    """Background resolver: resolve the first pending help request when it appears."""
    while True:
        await asyncio.sleep(0)
        pending = runtime.approvals.list_pending()
        if pending:
            runtime.approvals.resolve(pending[0].id, ApprovalStatus.APPROVED, **resolve_kwargs)
            return


class TestSelfVerification:
    async def _run_verified(self, runtime: AgentRuntime, task_input: str) -> Run:
        run = runtime.create_run("helper", task_input)
        return await runtime.execute_run(run)

    async def test_failed_then_fixed_output_passes(self) -> None:
        runtime = verify_runtime(
            [4.0, 8.0], VerificationPolicy(enabled=True, min_overall=7.0, max_rounds=1)
        )
        run = await self._run_verified(runtime, "write a haiku")
        verification = run.metadata["verification"]
        assert verification["passed"] is True
        assert verification["rounds"] == 1
        assert [a["overall"] for a in verification["attempts"]] == [4.0, 8.0]
        assert run.status is RunStatus.COMPLETED

    async def test_escalation_feeds_human_note_into_final_round(self) -> None:
        runtime = verify_runtime(
            [3.0, 3.0, 3.0], VerificationPolicy(enabled=True, min_overall=7.0, max_rounds=1)
        )
        resolver = asyncio.create_task(resolve_when_pending(runtime, note="mention the season"))
        run = await self._run_verified(runtime, "write a haiku")
        await resolver
        verification = run.metadata["verification"]
        assert verification["escalation"] == "resolved"
        assert verification["passed"] is False
        assert run.status is RunStatus.COMPLETED

    async def test_accept_mode_completes_unverified_without_help(self) -> None:
        runtime = verify_runtime(
            [2.0],
            VerificationPolicy(enabled=True, min_overall=7.0, max_rounds=0, on_fail="accept"),
        )
        run = await self._run_verified(runtime, "write a haiku")
        assert run.metadata["verification"]["passed"] is False
        assert runtime.approvals.list_pending() == []
        assert run.status is RunStatus.COMPLETED

    async def test_escalation_rejection_completes_without_guidance(self) -> None:
        runtime = verify_runtime(
            [2.0], VerificationPolicy(enabled=True, min_overall=7.0, max_rounds=0)
        )

        async def rejecter() -> None:
            while True:
                await asyncio.sleep(0)
                pending = runtime.approvals.list_pending()
                if pending:
                    runtime.approvals.resolve(pending[0].id, ApprovalStatus.REJECTED)
                    return

        reject_task = asyncio.create_task(rejecter())
        run = await self._run_verified(runtime, "write a haiku")
        await reject_task
        assert run.metadata["verification"]["escalation"] == "rejected"
        assert run.status is RunStatus.COMPLETED

    async def test_verification_disabled_leaves_output_untouched(self) -> None:
        runtime = verify_runtime([1.0], VerificationPolicy(enabled=False))
        run = await self._run_verified(runtime, "write a haiku")
        assert "verification" not in run.metadata
        assert runtime.list_runs() and len(runtime.list_runs()) == 1  # no nested judge run


# ---------------------------------------------------------- approval plumbing


class TestTaskHelpPersistenceAndSchema:
    def test_create_help_and_resolve_note(self, tmp_path: Any) -> None:
        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        manager = ApprovalManager(store)
        request = manager.create_help(run_id="r1", agent_id="helper", question="What next?")
        assert request.kind.value == "task_help"
        assert request.tool_name is None
        resolved = manager.resolve(request.id, ApprovalStatus.APPROVED, note="do X")
        assert resolved.resolved_note == "do X"

    def test_pending_help_rejected_on_restart(self, tmp_path: Any) -> None:
        store = SqliteStore(f"sqlite:///{tmp_path}/agent.db")
        manager = ApprovalManager(store)
        request = manager.create_help(run_id="r1", agent_id="helper", question="What next?")

        restored = ApprovalManager(store)
        restored.hydrate()

        assert restored.list_pending() == []
        rejected = restored.get(request.id)
        assert rejected.status is ApprovalStatus.REJECTED
        assert rejected.resolved_by == "restart"


class TestApprovalOutSchema:
    def test_new_fields_are_serialized(self) -> None:
        request = ApprovalRequest(run_id="r1", agent_id="helper", question="What next?")
        out = ApprovalOut.of(request)
        assert out.kind == "tool_action"
        assert out.question == "What next?"
        assert out.resolved_note is None
        assert out.tool_name is None
