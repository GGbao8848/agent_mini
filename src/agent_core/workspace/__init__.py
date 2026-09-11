"""Workspace boundaries: the controlled working environment for a task.

The workspace directory is a **container of working folders**: each bound
project works in its own directory, and every unbound conversation shares a
folder called ``default`` (see :func:`default_root`). The agent gets a
*logical* filesystem rooted at its working folder:

    /inputs   read-only   user-provided material (attachments)
    /workspace read-write agent scratch space
    /outputs  read-write  deliverables the user will collect
    /scratch  read-write  ephemeral scratch (deliberately not "tmp": the
                          backend renders relative paths as virtual absolutes,
                          and a "/tmp" receipt was indistinguishable from the
                          host temp dir)
    /skills   read-write  the shared skills directory — a skill is a directory
                          the agent adds, edits, and deletes like any other

``skills/`` and the staging ``uploads/`` live at the workspace root, as
siblings of the working folders, never inside one. The rules that make some
paths read-only are applied to the DeepAgents filesystem middleware via
:mod:`agent_core.workspace.permissions`. See the runtime engineering guide,
Phase R2/R3.
"""

from agent_core.workspace.backend import BoundaryBackend
from agent_core.workspace.layout import (
    DEFAULT_GROUP_NAME,
    READ_ONLY_DIRS,
    WorkspaceLayout,
    default_root,
    skills_root,
)
from agent_core.workspace.permissions import filesystem_permissions

__all__ = [
    "DEFAULT_GROUP_NAME",
    "READ_ONLY_DIRS",
    "BoundaryBackend",
    "WorkspaceLayout",
    "default_root",
    "filesystem_permissions",
    "skills_root",
]
