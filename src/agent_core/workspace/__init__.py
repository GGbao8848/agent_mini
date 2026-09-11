"""Where conversations work, and where skills live.

The workspace directory is a **container of working folders**: each bound
project works in its own directory, and every unbound conversation shares a
folder called ``default`` (see :func:`default_root`). A working folder holds
whatever the conversation puts in it — no structure is pre-created.

``skills/`` and the staging ``uploads/`` live at the workspace root, as siblings
of the working folders, never inside one.
"""

from agent_core.workspace.layout import (
    DEFAULT_GROUP_NAME,
    default_root,
    skills_root,
)

__all__ = [
    "DEFAULT_GROUP_NAME",
    "default_root",
    "skills_root",
]
