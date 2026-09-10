"""Workspace boundaries: the controlled working environment for a task.

The runtime hands the agent a *logical* filesystem, not the real one:

    /inputs   read-only   user-provided material (attachments)
    /workspace read-write agent scratch space
    /outputs  read-write  deliverables the user will collect
    /tmp      read-write  ephemeral scratch
    /skills   read-only   capability sources, shared and never copied

The physical directories live under the task root; the rules that make some of
them read-only are applied to the DeepAgents filesystem middleware via
:mod:`agent_core.workspace.permissions`. See the runtime engineering guide,
Phase R2/R3.
"""

from agent_core.workspace.backend import BoundaryBackend
from agent_core.workspace.layout import READ_ONLY_DIRS, WorkspaceLayout
from agent_core.workspace.permissions import filesystem_permissions
from agent_core.workspace.skills_index import SkillsIndexBackend

__all__ = [
    "READ_ONLY_DIRS",
    "BoundaryBackend",
    "SkillsIndexBackend",
    "WorkspaceLayout",
    "filesystem_permissions",
]
