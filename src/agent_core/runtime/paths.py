"""Task working-root resolution: project directory vs per-task folder.

Lives in its own module because both :mod:`agent_core.artifacts` (which owns
``task_workspace``) and the runtime context feed into it — keeping it here
avoids import cycles between the artifacts and runtime packages.
"""

from __future__ import annotations

from pathlib import Path

from agent_core.artifacts import task_workspace
from agent_core.runtime.context import current_task_root, get_current_task_id


def current_task_dir(workspace: Path) -> Path:
    """The working root of the in-flight task, created on demand.

    Tasks bound to a project work directly inside the project's directory
    (the runtime publishes it via ``current_task_root``); everything else
    uses the anonymous ``workspace/tasks/<task_id>/`` folder, or the shared
    workspace root outside any task.
    """
    root = current_task_root.get()
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        return root
    task_id = get_current_task_id()
    return task_workspace(workspace, task_id) if task_id is not None else workspace
