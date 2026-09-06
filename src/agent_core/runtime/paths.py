"""Task working-root resolution: project directory vs per-task folder.

Lives in its own module because both :mod:`agent_core.artifacts` (which owns
``task_workspace``) and the runtime context feed into it — keeping it here
avoids import cycles between the artifacts and runtime packages.
"""

from __future__ import annotations

from pathlib import Path

from agent_core.artifacts import task_workspace
from agent_core.config.settings import Settings
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


def environment_note(root: Path, settings: Settings) -> str:
    """System-prompt addendum describing where the agent actually works.

    Regenerated on every build so the note always matches the real execution
    backend — podman's /work mapping, or the host root (project dir when the
    conversation is bound to one) — instead of a stale hard-coded path.
    Agents chased ``/work`` and resorted to ``find /`` when the prompt lied
    about the backend; this note is the fix.
    """
    if settings.sandbox == "podman":
        detail = (
            "你在 rootless 容器沙箱里工作：任务目录挂载在 /work，"
            "文件工具与 run_code 的工作目录都是 /work。"
        )
    else:
        detail = (
            f"你的工作目录是 {root}：文件工具和 run_code 的 bash 都在这个目录里执行，"
            "所有文件一律用相对路径读写。"
        )
    return (
        "\n\n## 运行环境\n"
        f"- {detail}\n"
        "- 你写的文件不会丢：它们都在工作目录里，不要用 find / 全盘搜索找文件。\n"
        "- 需要第三方库时优先调用 ensure_packages 声明，不要直接 pip install。\n"
        "- 交付前用相对路径验证文件确实存在。"
    )
