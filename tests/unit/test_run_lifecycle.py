import pytest

from agent_core.domain.task import Run, RunStatus, Task
from agent_core.errors.exceptions import StateError


def test_task_has_generated_id() -> None:
    a = Task(agent_id="helper", title="one", input="one")
    b = Task(agent_id="helper", title="two", input="two")
    assert a.id != b.id


def test_happy_path_lifecycle() -> None:
    run = Run(task_id=Task(agent_id="helper", title="hi", input="hi").id, agent_id="assistant")
    run.transition_to(RunStatus.RUNNING)
    run.transition_to(RunStatus.WAITING_APPROVAL)
    run.transition_to(RunStatus.RUNNING)
    run.transition_to(RunStatus.COMPLETED)
    assert run.status is RunStatus.COMPLETED
    assert run.finished_at is not None


def test_planning_step_is_valid() -> None:
    run = Run(task_id="t", agent_id="a")
    run.transition_to(RunStatus.PLANNING)
    run.transition_to(RunStatus.RUNNING)
    assert run.status is RunStatus.RUNNING


def test_terminal_states_are_frozen() -> None:
    run = Run(task_id="t", agent_id="a")
    run.transition_to(RunStatus.RUNNING)
    run.transition_to(RunStatus.FAILED)
    with pytest.raises(StateError):
        run.transition_to(RunStatus.RUNNING)


def test_illegal_transition_raises() -> None:
    run = Run(task_id="t", agent_id="a")
    with pytest.raises(StateError):
        run.transition_to(RunStatus.COMPLETED)


def test_waiting_approval_can_resume_or_cancel() -> None:
    run = Run(task_id="t", agent_id="a")
    run.transition_to(RunStatus.RUNNING)
    run.transition_to(RunStatus.WAITING_APPROVAL)
    run.transition_to(RunStatus.CANCELLED)
    assert run.status.is_terminal


def test_terminal_property() -> None:
    assert not RunStatus.RUNNING.is_terminal
    assert RunStatus.TIMEOUT.is_terminal
