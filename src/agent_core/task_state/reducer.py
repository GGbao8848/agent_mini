"""Task State reducer (R21): project trace events onto a :class:`TaskState`.

This is the deterministic half of the task-state model. It never calls a model:
lifecycle status, tool activity, failures and plan declarations are folded in
from the event stream exactly as the runtime emitted them, so the state is
evidence-based rather than something the model asserts about itself.

Only **root-run** events count (``parent_run_id is None``): a verifier or
sub-agent's tool failures are the verifier's business, not the task's progress.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.task import new_id
from agent_core.domain.trace import TraceEvent
from agent_core.task_state.domain import (
    ActivityRef,
    StepStatus,
    TaskState,
    TaskStep,
    _now,
)

# Tools that only *look* at things do not represent task progress; recording
# them would drown the plan in read_file/ls noise. Everything else counts as
# evidence that a step moved forward.
_INVESTIGATION_TOOLS = frozenset(
    {"read_file", "ls", "glob", "grep", "recall_memories", "update_plan", "request_help"}
)

_MAX_ACTIVITY = 40
_MAX_FAILURES = 20
_MAX_GOAL_CHARS = 500


class TaskStateReducer:
    """Folds one trace event into a task state (pure; no I/O)."""

    def apply(self, state: TaskState, event: TraceEvent) -> TaskState | None:
        """Return ``state`` after ``event``, or None when it does not apply."""
        if event.parent_run_id is not None:
            return None
        handler = getattr(self, f"_on_{event.event_type.value}", None)
        if handler is None:
            return None
        updated: TaskState = handler(state, event)
        updated.updated_at = _now()
        return updated

    # ------------------------------------------------------------- lifecycle

    def _on_run_started(self, state: TaskState, event: TraceEvent) -> TaskState:
        if not state.goal and isinstance(event.input, str):
            state.goal = event.input.strip()[:_MAX_GOAL_CHARS]
        state.status = "running"
        state.run_count += 1
        state.next_action = None
        return state

    def _on_run_status_changed(self, state: TaskState, event: TraceEvent) -> TaskState:
        to = str((event.metadata or {}).get("to") or "")
        if to:
            state.status = to
        return state

    def _on_action_pending(self, state: TaskState, event: TraceEvent) -> TaskState:
        # A run parked on a human decision is not "stuck": say so explicitly so
        # the model (and the console) understand why nothing is progressing.
        kind = (event.metadata or {}).get("kind")
        state.status = "needs_input" if kind == "task_help" else "waiting_approval"
        state.next_action = "等待人工处理"
        return state

    def _on_run_finished(self, state: TaskState, event: TraceEvent) -> TaskState:
        # ``next_action`` is deliberately kept: a completed run whose plan still
        # has outstanding steps should tell the next turn what is left.
        state.status = "completed"
        return state

    def _on_run_failed(self, state: TaskState, event: TraceEvent) -> TaskState:
        state.status = str(event.status or "failed")
        message = event.error or "run failed"
        self._add_failure(state, message)
        return state

    def _on_run_cancelled(self, state: TaskState, event: TraceEvent) -> TaskState:
        state.status = "cancelled"
        return state

    # ------------------------------------------------------------------ plan

    def _on_plan_updated(self, state: TaskState, event: TraceEvent) -> TaskState:
        """Install the agent's declared plan (from the ``update_plan`` tool)."""
        meta: dict[str, Any] = event.metadata or {}
        specs = meta.get("steps") or []
        current_index = meta.get("current_index")
        goal = meta.get("goal")
        if isinstance(goal, str) and goal.strip():
            state.goal = goal.strip()[:_MAX_GOAL_CHARS]

        previous = {s.description: s for s in state.steps}
        steps: list[TaskStep] = []
        for position, spec in enumerate(specs):
            description = str(spec.get("description") or "").strip()
            if not description:
                continue
            prior = previous.get(description)
            status = _status_for_position(position, current_index, prior)
            steps.append(
                TaskStep(
                    id=prior.id if prior is not None else new_id(),
                    description=description,
                    status=status,
                    tool=spec.get("tool") or (prior.tool if prior else None),
                    detail=prior.detail if prior is not None else "",
                )
            )
        state.steps = steps
        state.plan_revision += 1
        # Point the marker at the declared current step (if any) so failures and
        # the prompt block can attribute themselves to the step in flight.
        if isinstance(current_index, int) and 0 <= current_index < len(steps):
            state.current_step_id = steps[current_index].id
        else:
            state.current_step_id = None
        next_action = meta.get("next_action")
        state.next_action = str(next_action) if next_action else None
        for decision in meta.get("decisions") or []:
            text = str(decision).strip()
            if text and text not in state.decisions:
                state.decisions.append(text)
        return state

    # -------------------------------------------------------------- activity

    def _on_tool_executed(self, state: TaskState, event: TraceEvent) -> TaskState:
        tool = event.tool or ""
        if not tool:
            return state
        if tool in _INVESTIGATION_TOOLS:
            return state
        self._record_activity(state, tool, failed=False)
        return state

    def _on_tool_failed(self, state: TaskState, event: TraceEvent) -> TaskState:
        tool = event.tool or ""
        if tool:
            # A failed *investigation* tool is still not task progress — record
            # the failure but do not claim an activity step (mirrors the success
            # path). Without this a retried update_plan looked like real work.
            if tool not in _INVESTIGATION_TOOLS:
                self._record_activity(state, tool, failed=True)
            self._add_failure(state, f"{tool}: {event.error or 'failed'}")
        return state

    # --------------------------------------------------------------- helpers

    def _record_activity(self, state: TaskState, tool: str, *, failed: bool) -> None:
        for entry in state.activity:
            if entry.tool == tool:
                entry.count += 1
                entry.failed = entry.failed and failed
                entry.last_at = _now()
                return
        state.activity.append(ActivityRef(tool=tool, count=1, failed=failed))
        if len(state.activity) > _MAX_ACTIVITY:
            del state.activity[: len(state.activity) - _MAX_ACTIVITY]

    def _add_failure(self, state: TaskState, message: str) -> None:
        text = message.strip()[:300]
        if not text or text in state.failures:
            return
        state.failures.append(text)
        if len(state.failures) > _MAX_FAILURES:
            del state.failures[: len(state.failures) - _MAX_FAILURES]
        # A failure on the step the agent is actively working is the step's
        # problem: mark it FAILED. A later re-plan resets it.
        active = state.current_step
        if active is not None and active.status is StepStatus.ACTIVE:
            active.status = StepStatus.FAILED
            active.detail = text
            active.updated_at = _now()


def _status_for_position(
    position: int, current_index: Any, prior: TaskStep | None
) -> StepStatus:
    """Derive a fresh step's status from its position in the declared plan.

    Steps before ``current_index`` are the agent's assertion that they are
    already done; the step at ``current_index`` is active. A step the agent has
    explicitly failed stays failed until it re-plans it as current.
    """
    if prior is not None and prior.status is StepStatus.FAILED and position != current_index:
        return StepStatus.FAILED
    if not isinstance(current_index, int):
        return prior.status if prior is not None else StepStatus.PENDING
    if position < current_index:
        return StepStatus.DONE
    if position == current_index:
        return StepStatus.ACTIVE
    return StepStatus.PENDING
