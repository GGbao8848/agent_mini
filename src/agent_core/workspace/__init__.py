"""Workspace boundaries: the controlled working environment for a task.

The runtime hands the agent a *logical* filesystem, not the real one:

    /inputs   read-only   user-provided material (attachments)
    /workspace read-write agent scratch space
    /outputs  read-write  deliverables the user will collect
    /scratch  read-write  ephemeral scratch (deliberately not "tmp": the
                          backend renders relative paths as virtual absolutes,
                          and a "/tmp" receipt was indistinguishable from the
                          host temp dir)
    /skills   read-write  the shared skills directory — a skill is a directory
                          the agent adds, edits, and deletes like any other

The physical directories live under the task root; the rules that make some of
them read-only are applied to the DeepAgents filesystem middleware via
:mod:`agent_core.workspace.permissions`. See the runtime engineering guide,
Phase R2/R3.
"""

from agent_core.workspace.backend import BoundaryBackend
from agent_core.workspace.layout import READ_ONLY_DIRS, WorkspaceLayout, skills_root
from agent_core.workspace.permissions import filesystem_permissions

__all__ = [
    "READ_ONLY_DIRS",
    "BoundaryBackend",
    "WorkspaceLayout",
    "filesystem_permissions",
    "skills_root",
]
