"""Task-state reducer and service tests (R21, invariants I-20…).

The task state must be an *evidence-based projection* of the run's event
stream, not something the model asserts about itself. These tests pin that:
status/failures/activity come from events, the plan comes from ``update_plan``
(a declared intent), and a restart repairs stale state.
"""

from __future__ import annotations

from agent_core.domain.task import Run, RunStatus, Task
from agent_core.domain.trace import EventType, TraceEvent
from agent_core.task_state import StepStatus, TaskStateService


def _event(event_type: EventType, **fields: object) -> TraceEvent:
    base: dict[str, object] = {"run_id": "r1", "task_id": "t1"}
    base.update(fields)
    return TraceEvent(event_type=event_type, **base)  # type: ignore[arg-type]


def test_status_follows_lifecycle_events() -> None:
    """I-20: status mirrors the root run's lifecycle, not an LLM claim."""
    service = TaskStateService()
    service.apply(_event(EventType.RUN_STARTED, input="做一份报表"))
    assert service.peek("t1").status == "running"  # type: ignore[union-attr]

    service.apply(_event(EventType.RUN_FINISHED))
    assert service.peek("t1").status == "completed"  # type: ignore[union-attr]


def test_goal_captured_from_first_run_input() -> None:
    service = TaskStateService()
    service.apply(_event(EventType.RUN_STARTED, input="把 A 转成 B"))
    assert service.peek("t1").goal == "把 A 转成 B"  # type: ignore[union-attr]


def test_plan_declaration_installs_steps_and_marks_current() -> None:
    service = TaskStateService()
    service.apply(_event(EventType.RUN_STARTED, input="任务"))
    service.apply(
        _event(
            EventType.PLAN_UPDATED,
            tool="update_plan",
            metadata={
                "steps": [
                    {"description": "读取"},
                    {"description": "转换"},
                    {"description": "验证"},
                ],
                "current_index": 1,
                "next_action": "运行转换",
            },
        )
    )
    state = service.peek("t1")
    assert state is not None
    assert [s.status for s in state.steps] == [
        StepStatus.DONE,
        StepStatus.ACTIVE,
        StepStatus.PENDING,
    ]
    assert state.current_step is not None
    assert state.current_step.description == "转换"
    assert state.next_action == "运行转换"


def test_replanning_preserves_step_identity() -> None:
    """A re-plan of the same step text keeps its id (stable references)."""
    service = TaskStateService()
    plan = {
        "steps": [{"description": "读取"}, {"description": "转换"}],
        "current_index": 0,
    }
    service.apply(_event(EventType.PLAN_UPDATED, metadata=plan))
    first = service.peek("t1")
    assert first is not None
    ids = [s.id for s in first.steps]

    plan = {
        "steps": [{"description": "读取"}, {"description": "转换"}, {"description": "验证"}],
        "current_index": 1,
    }
    service.apply(_event(EventType.PLAN_UPDATED, metadata=plan))
    state = service.peek("t1")
    assert state is not None
    assert [s.id for s in state.steps[:2]] == ids
    assert state.current_step is not None and state.current_step.description == "转换"


def test_tool_failure_marks_active_step_failed_and_records_failure() -> None:
    service = TaskStateService()
    service.apply(
        _event(
            EventType.PLAN_UPDATED,
            metadata={
                "steps": [{"description": "转换"}],
                "current_index": 0,
            },
        )
    )
    service.apply(_event(EventType.TOOL_FAILED, tool="run_code", error="KeyError"))
    state = service.peek("t1")
    assert state is not None
    assert state.steps[0].status is StepStatus.FAILED
    assert state.steps[0].detail == "run_code: KeyError"
    assert any("KeyError" in f for f in state.failures)


def test_investigation_tools_do_not_clutter_activity() -> None:
    """Read-only tools must not be counted as task progress."""
    service = TaskStateService()
    service.apply(_event(EventType.TOOL_EXECUTED, tool="read_file"))
    service.apply(_event(EventType.TOOL_EXECUTED, tool="ls"))
    service.apply(_event(EventType.TOOL_EXECUTED, tool="run_code"))
    state = service.peek("t1")
    assert state is not None
    assert [a.tool for a in state.activity] == ["run_code"]


def test_nested_run_events_are_ignored() -> None:
    """A verifier/sub-agent failure is not the task's progress (I-21)."""
    service = TaskStateService()
    service.apply(
        _event(
            EventType.TOOL_FAILED,
            tool="judge",
            error="nested",
            parent_run_id="verifier1",
        )
    )
    assert service.peek("t1") is None


def test_approval_pauses_status_explicitly() -> None:
    service = TaskStateService()
    service.apply(_event(EventType.RUN_STARTED, input="任务"))
    service.apply(_event(EventType.ACTION_PENDING, tool="run_code"))
    assert service.peek("t1").status == "waiting_approval"  # type: ignore[union-attr]
    service.apply(
        _event(EventType.ACTION_PENDING, metadata={"kind": "task_help"})
    )
    assert service.peek("t1").status == "needs_input"  # type: ignore[union-attr]


def test_artifacts_mirrored_into_state() -> None:
    service = TaskStateService()
    service.apply(_event(EventType.RUN_STARTED, input="任务"))
    service.sync_artifacts(
        "t1", [{"path": "outputs/a.xlsx", "name": "a.xlsx", "run_id": "r1"}]
    )
    state = service.peek("t1")
    assert state is not None
    assert [a.name for a in state.artifacts] == ["a.xlsx"]


def test_reconcile_repairs_stale_status_after_restart() -> None:
    """I-22: a state left 'running' by a crash is corrected to the run's truth."""
    service = TaskStateService()
    service.apply(_event(EventType.RUN_STARTED, input="任务"))
    assert service.peek("t1").status == "running"  # type: ignore[union-attr]

    task = Task(id="t1", agent_id="a", title="t")
    run = Run(id="r1", task_id="t1", agent_id="a", status=RunStatus.FAILED)
    changed = service.reconcile([task], [run])
    assert changed == 1
    assert service.peek("t1").status == "failed"  # type: ignore[union-attr]


def test_prompt_block_empty_for_trivial_state() -> None:
    service = TaskStateService()
    service.apply(_event(EventType.RUN_STARTED, input="嗨"))
    # Single run, no plan, no artifacts: nothing worth injecting.
    assert service.prompt_block("t1") == ""


def test_prompt_block_renders_plan_and_failures() -> None:
    service = TaskStateService()
    service.apply(_event(EventType.RUN_STARTED, input="把 A 转 B"))
    service.apply(
        _event(
            EventType.PLAN_UPDATED,
            metadata={"steps": [{"description": "读取 A"}], "current_index": 0},
        )
    )
    block = service.prompt_block("t1")
    assert "任务状态" in block
    assert "读取 A" in block
    assert "把 A 转 B" in block


class TestUpdatePlanStepNormalization:
    """The update_plan tool must tolerate the shapes a real model sends.

    A production trace showed the model call update_plan with a list of plain
    strings, then {step}, then {text}, before finally using {description} — the
    parser must accept all of these rather than failing the call.
    """

    def test_plain_strings(self) -> None:
        from agent_core.builtins.plan import _normalize_steps

        assert _normalize_steps(["读文件", "写文件"]) == [
            {"description": "读文件", "tool": None},
            {"description": "写文件", "tool": None},
        ]

    def test_alternate_dict_keys(self) -> None:
        from agent_core.builtins.plan import _normalize_steps

        for key in ("description", "step", "text", "title", "name", "content"):
            assert _normalize_steps([{key: "做某事"}]) == [
                {"description": "做某事", "tool": None}
            ]

    def test_tool_is_preserved(self) -> None:
        from agent_core.builtins.plan import _normalize_steps

        assert _normalize_steps([{"description": "跑脚本", "tool": "run_code"}]) == [
            {"description": "跑脚本", "tool": "run_code"}
        ]

    def test_empty_and_junk_items_are_dropped(self) -> None:
        from agent_core.builtins.plan import _normalize_steps

        assert _normalize_steps(["  ", {}, {"description": ""}, 42, None]) == []

    def test_non_list_returns_empty(self) -> None:
        from agent_core.builtins.plan import _normalize_steps

        assert _normalize_steps("不是列表") == []
        assert _normalize_steps(None) == []
