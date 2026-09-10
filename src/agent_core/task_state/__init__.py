"""Task State (R21): the explicit progress record of a conversation.

Conversation history answers "what was said"; this package answers "where is
the task now". See :mod:`agent_core.task_state.domain` for the model,
:mod:`agent_core.task_state.reducer` for the event projection, and
:mod:`agent_core.task_state.service` for the read/write path.
"""

from agent_core.task_state.domain import ActivityRef, ArtifactRef, StepStatus, TaskState, TaskStep
from agent_core.task_state.reducer import TaskStateReducer
from agent_core.task_state.repository import TaskStateRepository
from agent_core.task_state.service import TaskStateService, render_prompt

__all__ = [
    "ActivityRef",
    "ArtifactRef",
    "StepStatus",
    "TaskState",
    "TaskStateReducer",
    "TaskStateRepository",
    "TaskStateService",
    "TaskStep",
    "render_prompt",
]
