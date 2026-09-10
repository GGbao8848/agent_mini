"""Task State service: the single read/write path for task states (R21).

Writes happen in exactly one direction — :meth:`apply` folds a runtime trace
event into the persisted state. The agent does not write the state directly: its
``update_plan`` tool emits a ``plan_updated`` event, which lands here like any
other. Reads render a compact prompt block (see :func:`render_prompt`) so the
model gets an explicit progress record instead of re-deriving it from history.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.task import Run, Task
from agent_core.domain.trace import TraceEvent
from agent_core.task_state.domain import (
    ArtifactRef,
    StepStatus,
    TaskState,
)
from agent_core.task_state.reducer import TaskStateReducer
from agent_core.task_state.repository import TaskStateRepository

_STATUS_LABELS = {
    "created": "未开始",
    "running": "进行中",
    "waiting_approval": "等待审批",
    "needs_input": "等待人工回复",
    "completed": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
    "timeout": "超时",
}

_STEP_MARKS = {
    StepStatus.DONE: "[x]",
    StepStatus.ACTIVE: "[>]",
    StepStatus.FAILED: "[!]",
    StepStatus.PENDING: "[ ]",
    StepStatus.SKIPPED: "[-]",
}

_TERMINAL = {"completed", "failed", "cancelled", "timeout"}


class TaskStateService:
    """Projects trace events into per-conversation task states."""

    def __init__(
        self,
        repository: TaskStateRepository | None = None,
        reducer: TaskStateReducer | None = None,
    ) -> None:
        self._repo = repository or TaskStateRepository()
        self._reducer = reducer or TaskStateReducer()

    # ----------------------------------------------------------------- reads

    def peek(self, task_id: str) -> TaskState | None:
        """The stored state, or None when nothing has happened yet."""
        return self._repo.get(task_id)

    def ensure(self, task_id: str) -> TaskState:
        """The state for ``task_id``, creating an empty (unpersisted) one."""
        return self._repo.get(task_id) or TaskState(task_id=task_id)

    # ---------------------------------------------------------------- writes

    def apply(self, event: TraceEvent) -> TaskState | None:
        """Fold one trace event into the task state; returns it when changed."""
        task_id = event.task_id
        if task_id is None:
            return None
        state = self._repo.get(task_id)
        if state is None:
            state = TaskState(task_id=task_id)
        updated = self._reducer.apply(state, event)
        if updated is None:
            return None
        self._repo.save(updated)
        return updated

    def sync_artifacts(
        self, task_id: str, artifacts: list[dict[str, Any]]
    ) -> TaskState | None:
        """Mirror the conversation's artifact manifest into the state.

        Called by the runtime after a root run finishes: artifacts are a fact of
        the filesystem/run record, not an event, so they are pulled rather than
        folded. Replaces the artifact list wholesale (the manifest is complete).
        """
        state = self._repo.get(task_id)
        if state is None or not artifacts:
            return state
        refs: list[ArtifactRef] = []
        for entry in artifacts:
            path = str(entry.get("path") or "")
            if not path:
                continue
            refs.append(
                ArtifactRef(
                    path=path,
                    name=str(entry.get("name") or path.rsplit("/", 1)[-1]),
                    run_id=entry.get("run_id"),
                )
            )
        if refs:
            state.artifacts = refs
            self._repo.save(state)
        return state

    def delete(self, task_id: str) -> None:
        self._repo.delete(task_id)

    def hydrate(self) -> int:
        """Restore states persisted by a previous process."""
        return self._repo.hydrate()

    def reconcile(self, tasks: list[Task], runs: list[Run]) -> int:
        """Repair states left mid-flight by a process restart.

        A restart marks non-terminal runs failed but emits no event, so a state
        could still claim "running". Recomputing status from the latest root run
        keeps the console and the model from reading a stale progress claim.
        """
        latest: dict[str, Run] = {}
        for run in runs:
            if run.parent_run_id is None:
                latest[run.task_id] = run  # runs are ordered by creation
        changed = 0
        for task in tasks:
            state = self._repo.get(task.id)
            if state is None:
                continue
            active = latest.get(task.id)
            if active is None:
                continue
            expected = active.status.value
            if state.status != expected:
                state.status = expected
                if expected in _TERMINAL:
                    state.next_action = None
                self._repo.save(state)
                changed += 1
        return changed

    # ---------------------------------------------------------------- render

    def prompt_block(self, task_id: str) -> str:
        """Compact progress block for the system prompt ('' when trivial)."""
        state = self._repo.get(task_id)
        if state is None or not state.has_content:
            return ""
        return render_prompt(state)


def render_prompt(state: TaskState) -> str:
    """Render the task-state block injected into the system prompt."""
    lines = [
        "\n\n## 任务状态（由系统记录，供你判断进度；不要凭记忆臆测已完成的工作）",
        f"- 目标：{state.goal or '（未记录）'}",
        f"- 状态：{_STATUS_LABELS.get(state.status, state.status)}",
    ]
    if state.steps:
        lines.append("- 计划：")
        for index, step in enumerate(state.steps, start=1):
            mark = _STEP_MARKS.get(step.status, "[ ]")
            suffix = f" — {step.detail}" if step.detail else ""
            lines.append(f"  {mark} {index}. {step.description}{suffix}")
    current = state.current_step
    if current is not None and current.status is not StepStatus.DONE:
        lines.append(f"- 当前步骤：{current.description}")
    if state.next_action:
        lines.append(f"- 下一步：{state.next_action}")
    if state.failures:
        lines.append("- 失败/待解决：")
        lines.extend(f"  - {item}" for item in state.failures[-5:])
    if state.artifacts:
        names = "、".join(a.name or a.path for a in state.artifacts[:10])
        lines.append(f"- 已产出文件：{names}")
    if state.activity:
        names = "、".join(f"{a.tool}×{a.count}" for a in state.activity[-12:])
        lines.append(f"- 最近工具活动：{names}")
    lines.append(
        "- 若实际进度与上述不符，请调用 update_plan 更新计划；"
        "报告完成前请确认产物文件真实存在。"
    )
    return "\n".join(lines)
