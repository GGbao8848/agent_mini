"""Context variables identifying the Run / Task for the current async task.

DeepAgents (and LangGraph) invoke tools deep inside their own execution;
the context vars are the only reliable way for the Action Gate wrapper and
the builtin tool handlers to know which task they serve — sub-agent
invocations inherit the context automatically.
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path

from agent_core.domain.task import Run

current_run: ContextVar[Run | None] = ContextVar("current_run", default=None)
current_task_id: ContextVar[str | None] = ContextVar("current_task_id", default=None)
"""The conversation id of the run executing right now, or None outside a run.

Distinct from ``current_run`` so tool handlers can scope their output to the
task's private directory without depending on the whole Run object.
"""

current_task_root: ContextVar[Path | None] = ContextVar("current_task_root", default=None)
"""The filesystem root the in-flight task works in, or None for the default.

Set by the runtime from the task's bound project: None means the task uses
the anonymous ``workspace/tasks/<task_id>/`` directory; a path means the task
works directly inside that (project) directory.
"""

current_skill_mounts: ContextVar[tuple[tuple[str, str], ...]] = ContextVar(
    "current_skill_mounts", default=()
)
"""``(skill_id, source_dir)`` pairs for the in-flight run's enabled skills.

Set by the runtime before execution so ``run_code`` can mount the same skill
sources read-only into the sandbox at ``/skills/<id>`` — the file tools see
them as ``/skills/<id>`` too, so a skill's documented script path works in
both namespaces. Without this, a skill script the SKILL.md tells the agent to
run is invisible to ``bash`` (the sandbox only mounts the task root at
``/work``).
"""


def get_current_skill_mounts() -> tuple[tuple[str, str], ...]:
    """Enabled ``(skill_id, source_dir)`` pairs for the in-flight run."""
    return current_skill_mounts.get()


current_model_override: ContextVar[str | None] = ContextVar(
    "current_model_override", default=None
)
"""Per-run model spec (``provider:model``) requested by the caller, or None.

Set by the runtime from the run's metadata; the model factory reads it so a
conversation can pin a specific endpoint model without touching the agent
spec. Sub-agent invocations inherit it like the other context vars.
"""


current_query: ContextVar[str | None] = ContextVar("current_query", default=None)
"""The user input of the in-flight run, or None.

Set by the runtime before building the graph so memory retrieval can score the
long-term store against the actual request text and inject only the relevant
entries.
"""


current_memory_block: ContextVar[str] = ContextVar("current_memory_block", default="")
"""Pre-rendered long-term-memory system-prompt block for the in-flight run.

Computed asynchronously by the runtime (hybrid semantic+keyword retrieval)
before the graph is built, then read synchronously by the builder — the
builder cannot await, and retrieval needs to.
"""


def get_current_memory_block() -> str:
    """The retrieved-memory prompt block for the in-flight run (empty if none)."""
    return current_memory_block.get()


def get_current_model_override() -> str | None:
    """The caller-pinned model spec for the in-flight run, if any."""
    return current_model_override.get()


def get_current_query() -> str | None:
    """The user input driving the in-flight run, if any (memory retrieval)."""
    return current_query.get()


def get_current_task_id() -> str | None:
    """The task id of the in-flight run, or None when not inside a run.

    Tools call this at invocation time (handlers are re-entered per call), so
    it reflects whichever task is executing right now — never a stale capture.
    """
    return current_task_id.get()
