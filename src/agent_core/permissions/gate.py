"""Action Gate: the only path from an agent decision to tool execution.

Execution chain (never bypassed)::

    Agent -> Tool -> Permission -> Risk -> ActionGate -> Approval? -> Execute

The gate records an :class:`Action` for every invocation (allowed or not),
pauses the run in ``WAITING_APPROVAL`` while a human decides, and aborts the
run on rejection (fail closed: a refused action cannot be retried silently).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from agent_core.domain.action import Action, ActionStatus, ApprovalStatus
from agent_core.domain.permission import PermissionDecision
from agent_core.domain.task import Run, RunStatus
from agent_core.domain.trace import EventType
from agent_core.errors.exceptions import (
    AgentError,
    ApprovalRejectedError,
    PermissionDeniedError,
)
from agent_core.observability.emitter import EventFanout
from agent_core.permissions.approval import ApprovalManager
from agent_core.permissions.policy import ActionPolicy
from agent_core.registries import AgentRegistry, ToolHandler, ToolRegistry

if TYPE_CHECKING:
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
    ) -> None:
        self._agents = agents
        self._tools = tools
        self._policy = policy
        self._approvals = approvals
        self._executor = executor
        self._fanout = fanout

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
        handler = self._tools.handler_for(tool_name)
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

        if decision is PermissionDecision.REQUIRE_APPROVAL:
            arguments = await self._request_approval(run, action, arguments)

        return await self._execute(run, action, handler, arguments)

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
        self, run: Run, action: Action, handler: ToolHandler, arguments: dict[str, Any]
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
            result = await self._executor.execute(action.tool_name, handler, arguments)
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
