"""Action Gate: the only path from an agent decision to tool execution.

Execution chain (never bypassed)::

    Agent -> Tool -> Permission -> Risk -> ActionGate -> LoopGuard? -> Approval? -> Execute

The gate records an :class:`Action` for every invocation (allowed or not),
pauses the run in ``WAITING_APPROVAL`` while a human decides, and aborts the
run on rejection (fail closed: a refused action cannot be retried silently).

Autonomy exceptions: agents with ``autonomy.loop_guard`` get their repeated
calls / tool failures surfaced to the model as messages instead of aborting
(soft), and both the guard and the agent itself (via the ``request_help``
tool) can raise a task-level help request that parks the run in
``NEEDS_INPUT`` until a human answers; the answer is fed back as guidance.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from agent_core.domain.action import Action, ActionStatus, ApprovalKind, ApprovalStatus
from agent_core.domain.autonomy import LoopGuardPolicy
from agent_core.domain.permission import PermissionDecision
from agent_core.domain.task import Run, RunStatus
from agent_core.domain.tool import ToolDefinition, adapt_handler_arguments
from agent_core.domain.trace import EventType
from agent_core.errors.exceptions import (
    AgentError,
    ApprovalRejectedError,
    PermissionDeniedError,
)
from agent_core.observability.emitter import EventFanout
from agent_core.permissions.approval import ApprovalManager
from agent_core.permissions.loop_guard import LoopGuard, LoopVerdict
from agent_core.permissions.policy import ActionPolicy
from agent_core.registries import AgentRegistry, ToolHandler, ToolRegistry

if TYPE_CHECKING:
    # Runtime import would be circular (runtime/__init__ pulls the builder,
    # which pulls this module via help_tool); the executor is injected.
    from agent_core.runtime.tool_executor import ToolExecutor


class ActionGate:
    """Evaluates policy, collects approvals, then executes tools."""

    def __init__(
        self,
        agents: AgentRegistry,
        tools: ToolRegistry,
        policy: ActionPolicy,
        approvals: ApprovalManager,
        executor: ToolExecutor,
        fanout: EventFanout,
        loop_guard: LoopGuard | None = None,
    ) -> None:
        self._agents = agents
        self._tools = tools
        self._policy = policy
        self._approvals = approvals
        self._executor = executor
        self._fanout = fanout
        self._loop_guard = loop_guard

    async def execute(self, *, run: Run, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Gate and execute one tool invocation; returns the tool result."""
        self._fanout.emit(
            EventType.TOOL_REQUESTED,
            run=run,
            agent_id=run.agent_id,
            tool=tool_name,
            input=arguments,
        )
        definition = self._tools.get(tool_name)
        handler = adapt_handler_arguments(definition, self._tools.handler_for(tool_name))
        action = Action(
            run_id=run.id,
            agent_id=run.agent_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            risk_level=definition.risk_level,
        )

        spec = self._agents.get(run.agent_id)
        decision = self._policy.evaluate(spec, definition)
        if decision is PermissionDecision.DENY:
            action.status = ActionStatus.REJECTED
            action.reason = f"Permission denied for agent '{run.agent_id}'"
            self._fanout.emit(
                EventType.ACTION_REJECTED,
                run=run,
                agent_id=run.agent_id,
                tool=tool_name,
                error=action.reason,
            )
            raise PermissionDeniedError(run.agent_id, tool_name)

        guard_policy = spec.autonomy.loop_guard if spec.autonomy else None
        if guard_policy is not None and self._loop_guard is not None:
            verdict = self._loop_guard.check(run.id, tool_name, arguments, guard_policy)
            if verdict.action != "allow":
                return await self._on_loop_verdict(run, action, verdict, guard_policy)

        if decision is PermissionDecision.REQUIRE_APPROVAL:
            arguments = await self._request_approval(run, action, arguments)

        if guard_policy is None or self._loop_guard is None:
            return await self._execute(run, action, definition, handler, arguments)
        # Soft-failure mode: tool errors become messages the model can react
        # to, with the failure streak nudging/escalating before it wastes more
        # calls. Without a loop guard the historical fail-closed applies.
        self._loop_guard.record_called(run.id, tool_name, arguments)
        try:
            result = await self._execute(run, action, definition, handler, arguments)
        except AgentError as exc:
            failures = self._loop_guard.record_result(run.id, ok=False)
            if failures >= guard_policy.max_consecutive_failures:
                return await self.request_help(
                    run=run,
                    question=(
                        f"Tool '{tool_name}' failed {failures} times in a row; last error: "
                        f"{exc.message}. How should I proceed?"
                    ),
                    reason=f"consecutive tool failures ({failures})",
                )
            return (
                f"[tool error] '{tool_name}' failed: {exc.message} "
                f"(consecutive failures: {failures}/{guard_policy.max_consecutive_failures}). "
                "Fix the cause, adjust the arguments, or call request_help."
            )
        self._loop_guard.record_result(run.id, ok=True)
        return result

    async def _on_loop_verdict(
        self, run: Run, action: Action, verdict: LoopVerdict, policy: LoopGuardPolicy
    ) -> Any:
        """Handle a non-allow verdict: nudge (message back) or escalate (human)."""
        self._fanout.emit(
            EventType.LOOP_DETECTED,
            run=run,
            agent_id=run.agent_id,
            tool=action.tool_name,
            metadata={"verdict": verdict.action, "detail": verdict.message},
        )
        if verdict.action == "nudge":
            action.status = ActionStatus.REJECTED
            action.reason = verdict.message
            return verdict.message
        action.status = ActionStatus.REJECTED
        action.reason = verdict.message
        return await self.request_help(
            run=run,
            question=(
                f"{verdict.message} I appear to be stuck in a loop "
                f"(limit: {policy.max_identical_calls} identical calls). "
                "What should I do differently?"
            ),
            reason="loop guard escalation",
        )

    async def request_help(self, *, run: Run, question: str, reason: str = "") -> str:
        """Park the run in NEEDS_INPUT until a human answers; returns the guidance.

        The human's ``resolved_note`` becomes the tool result the agent sees;
        rejection keeps the fail-closed contract and aborts the run.
        """
        request = self._approvals.create_help(
            run_id=run.id, agent_id=run.agent_id, question=question, reason=reason
        )
        self._transition(run, RunStatus.NEEDS_INPUT)
        self._fanout.emit(
            EventType.ACTION_PENDING,
            run=run,
            agent_id=run.agent_id,
            input=question,
            metadata={
                "approval_id": request.id,
                "kind": ApprovalKind.TASK_HELP.value,
                "reason": reason,
            },
        )
        resolved = await self._approvals.wait(request.id)
        # Back to RUNNING so the run can legally reach any terminal state.
        self._transition(run, RunStatus.RUNNING)

        if resolved.status in (ApprovalStatus.REJECTED, ApprovalStatus.CANCELLED):
            self._fanout.emit(
                EventType.ACTION_REJECTED,
                run=run,
                agent_id=run.agent_id,
                metadata={"approval_id": request.id, "kind": ApprovalKind.TASK_HELP.value},
            )
            raise ApprovalRejectedError(request.id, resolved.resolved_by or "user")
        self._fanout.emit(
            EventType.ACTION_APPROVED,
            run=run,
            agent_id=run.agent_id,
            metadata={
                "approval_id": request.id,
                "kind": ApprovalKind.TASK_HELP.value,
                "status": resolved.status.value,
            },
        )
        return resolved.resolved_note or ""

    async def _request_approval(
        self, run: Run, action: Action, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        request = self._approvals.create(action)
        self._transition(run, RunStatus.WAITING_APPROVAL)
        self._fanout.emit(
            EventType.ACTION_PENDING,
            run=run,
            agent_id=run.agent_id,
            tool=action.tool_name,
            input=arguments,
            metadata={"approval_id": request.id, "risk": action.risk_level.value},
        )
        resolved = await self._approvals.wait(request.id)
        # Back to RUNNING so the run can legally reach any terminal state.
        self._transition(run, RunStatus.RUNNING)

        if resolved.status in (ApprovalStatus.REJECTED, ApprovalStatus.CANCELLED):
            action.status = ActionStatus.REJECTED
            action.reason = (
                f"Approval '{request.id}' {resolved.status.value} by {resolved.resolved_by}"
            )
            self._fanout.emit(
                EventType.ACTION_REJECTED,
                run=run,
                agent_id=run.agent_id,
                tool=action.tool_name,
                error=action.reason,
                metadata={"approval_id": request.id},
            )
            raise ApprovalRejectedError(request.id, resolved.resolved_by or "user")

        if resolved.status is ApprovalStatus.EDITED and resolved.edited_arguments is not None:
            action.status = ActionStatus.EDITED
            action.arguments = dict(resolved.edited_arguments)
            arguments = dict(resolved.edited_arguments)
        else:
            action.status = ActionStatus.APPROVED
        self._fanout.emit(
            EventType.ACTION_APPROVED,
            run=run,
            agent_id=run.agent_id,
            tool=action.tool_name,
            metadata={"approval_id": request.id, "status": resolved.status.value},
        )
        return arguments

    async def _execute(
        self,
        run: Run,
        action: Action,
        definition: ToolDefinition,
        handler: ToolHandler,
        arguments: dict[str, Any],
    ) -> Any:
        action.status = ActionStatus.EXECUTING
        self._fanout.emit(
            EventType.TOOL_STARTED,
            run=run,
            agent_id=run.agent_id,
            tool=action.tool_name,
            input=arguments,
        )
        started = time.monotonic()
        try:
            # A tool can declare its own execution budget via metadata
            # ("timeout_seconds") — image generation and code runs legitimately
            # exceed the executor's 60s default.
            timeout = definition.metadata.get("timeout_seconds")
            result = await self._executor.execute(
                action.tool_name, handler, arguments, timeout_seconds=timeout
            )
        except AgentError as exc:
            action.status = ActionStatus.FAILED
            action.error = exc.message
            self._fanout.emit(
                EventType.TOOL_FAILED,
                run=run,
                agent_id=run.agent_id,
                tool=action.tool_name,
                error=exc.message,
                duration_ms=(time.monotonic() - started) * 1000,
            )
            raise
        action.status = ActionStatus.COMPLETED
        action.result = result
        self._fanout.emit(
            EventType.TOOL_EXECUTED,
            run=run,
            agent_id=run.agent_id,
            tool=action.tool_name,
            output=result,
            duration_ms=(time.monotonic() - started) * 1000,
        )
        return result

    def _transition(self, run: Run, status: RunStatus) -> None:
        previous = run.status
        run.transition_to(status)
        self._fanout.emit(
            EventType.RUN_STATUS_CHANGED,
            run=run,
            agent_id=run.agent_id,
            metadata={"from": previous.value, "to": status.value},
        )
