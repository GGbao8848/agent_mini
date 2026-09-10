"""Built-in memory tools: the agent's explicit long-term-memory operations.

Deliberately *explicit*: the agent calls these when the user says to remember
something, states a lasting preference, corrects a fact, or asks to forget —
there is no silent per-turn extraction (that design was rolled back as noisy).

Three tools cover the full maintenance cycle so memory stays clean *in
conversation* rather than only via the console:

- ``remember``   — add a fact, or replace stale ones (``supersedes``)
- ``recall_memories`` — list/search what is stored (to find ids to act on)
- ``forget_memories`` — delete entries the user asked to drop

All are LOW risk: they touch only the memory store, never the host/workspace.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent_core.domain.action import RiskLevel
from agent_core.domain.memory import Memory, MemoryScope, MemoryType
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import ToolError

if TYPE_CHECKING:
    from agent_core.memory.service import MemoryService


@dataclass(frozen=True)
class MemoryWriteContext:
    """Who is writing and into what, resolved at call time (R23 governance)."""

    scope_id: str | None = None
    agent_id: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None


WriteContextProvider = Callable[[], MemoryWriteContext]
"""Resolve the current run's memory write context (from context vars)."""


def current_write_context() -> MemoryWriteContext:
    """Default provider: reads the in-flight run/task context vars."""
    from agent_core.runtime.context import get_current_run

    run = get_current_run()
    if run is None:
        return MemoryWriteContext()
    return MemoryWriteContext(
        agent_id=run.agent_id,
        task_id=run.task_id,
        run_id=run.id,
    )

REMEMBER_TOOL = "remember"
RECALL_MEMORIES_TOOL = "recall_memories"
FORGET_MEMORIES_TOOL = "forget_memories"

_SCOPE_VALUES = [s.value for s in MemoryScope]
_TYPE_VALUES = [t.value for t in MemoryType]

_REMEMBER_DESCRIPTION = (
    "Save a durable fact, preference, decision or lesson to long-term memory so "
    "it is available in future conversations. Use it when the user says to "
    "remember something, states a lasting preference, or you learn a project "
    "constraint worth keeping. If the user is CORRECTING or UPDATING a fact you "
    "can already see in the injected 长期记忆 block, pass that entry's #id in "
    "`supersedes` so the old one retires instead of both lingering. Do NOT use "
    "it for one-off task details or transient instructions ('do X for now')."
)

_RECALL_DESCRIPTION = (
    "List or search long-term memory. Call it to check what is already stored — "
    "e.g. before updating or deleting a fact, or when the user asks what you "
    "remember. With a query it does semantic+keyword search; without one it "
    "returns the most recent entries. Each result carries the #id used by "
    "`remember`(supersedes) and `forget_memories`."
)

_FORGET_DESCRIPTION = (
    "Delete entries from long-term memory — use it when the user asks you to "
    "forget something, or when a stored fact is no longer true and has no "
    "replacement. Pass the #id values (full or the short prefix) of the entries "
    "to drop; find them with recall_memories or from the injected 长期记忆 block."
)


def _scope_of(value: str | None) -> MemoryScope | None:
    return next((s for s in MemoryScope if s.value == value), None) if value else None


def _type_of(value: str | None) -> MemoryType | None:
    return next((t for t in MemoryType if t.value == value), None) if value else None


def _format(memory: Memory) -> str:
    return f"[#{memory.id[:8]}] ({memory.scope.value}/{memory.type.value}) {memory.content}"


def make_remember(
    service: MemoryService,
    *,
    context_provider: WriteContextProvider | None = None,
) -> tuple[ToolDefinition, Any]:
    provide: WriteContextProvider = context_provider or current_write_context

    async def remember(
        content: str,
        scope: str | None = None,
        type: str | None = None,
        supersedes: list[str] | None = None,
    ) -> str:
        if not content.strip():
            raise ToolError("remember requires non-empty content", details={"tool": REMEMBER_TOOL})
        from agent_core.memory.policy import MemoryOrigin

        context = provide()
        target_scope = _scope_of(scope) or MemoryScope.USER
        # A PROJECT memory belongs to the bound project; an AGENT memory to the
        # writing agent. USER/ORG need no id (R23).
        scope_id = None
        if target_scope is MemoryScope.PROJECT:
            scope_id = context.project_id
        elif target_scope is MemoryScope.AGENT:
            scope_id = context.agent_id
        old_ids: list[str] = []
        unresolved: list[str] = []
        for token in supersedes or []:
            memory_id = service.resolve_id(token)
            if memory_id is None:
                unresolved.append(token)
            else:
                old_ids.append(memory_id)
        if old_ids:
            self_decision = service.policy.can_write(
                scope=target_scope,
                origin=MemoryOrigin.AGENT,
                agent_id=context.agent_id,
                project_id=context.project_id,
            )
            if self_decision.value == "deny":
                raise ToolError(
                    service.policy.deny_reason(target_scope),
                    details={"tool": REMEMBER_TOOL, "scope": target_scope.value},
                )
            memory = service.supersede_many(
                old_ids,
                content,
                scope=target_scope,
                scope_id=scope_id,
                type=_type_of(type),
                source="agent",
                source_run_id=context.run_id,
                created_by=context.agent_id or "agent",
            )
            note = f"（已退役 {len(old_ids)} 条旧记忆）"
        else:
            try:
                memory = service.add_governed(
                    content,
                    scope=target_scope,
                    scope_id=scope_id,
                    type=_type_of(type) or MemoryType.FACT,
                    origin=MemoryOrigin.AGENT,
                    agent_id=context.agent_id,
                    project_id=context.project_id,
                    task_id=context.task_id,
                    source_run_id=context.run_id,
                    created_by=context.agent_id or "agent",
                )
            except Exception as exc:
                # Surface the policy refusal as a tool-level error the model
                # can act on (switch scope) rather than failing the run.
                raise ToolError(
                    service.policy.deny_reason(target_scope),
                    details={"tool": REMEMBER_TOOL, "scope": target_scope.value},
                ) from exc
            note = ""
        if unresolved:
            note += f"（未找到：{', '.join(unresolved)}）"
        return f"已记住 [#{memory.id[:8]}] {memory.content}{note}"

    definition = ToolDefinition(
        name=REMEMBER_TOOL,
        description=_REMEMBER_DESCRIPTION,
        risk_level=RiskLevel.LOW,
        source=ToolSource.INTERNAL,
        input_schema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The fact/preference/lesson to remember, one sentence",
                },
                "scope": {
                    "type": "string",
                    "enum": _SCOPE_VALUES,
                    "description": "Who it is about (default: retired entry's scope, else user)",
                },
                "type": {
                    "type": "string",
                    "enum": _TYPE_VALUES,
                    "description": "Kind of memory (default: the retired entry's type, else fact)",
                },
                "supersedes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Ids of existing memories this statement replaces "
                        "(from the #id shown with each entry). Pass these when "
                        "correcting/updating a fact so the old one retires."
                    ),
                },
            },
            "required": ["content"],
        },
        metadata={"builtin": True, "available": True},
    )
    return definition, remember


def make_recall_memories(service: MemoryService) -> tuple[ToolDefinition, Any]:
    async def recall_memories(query: str | None = None, limit: int = 10) -> str:
        count = max(1, min(int(limit or 10), 50))
        if query and query.strip():
            hits = await service.aretrieve(query, limit=count, token_budget=1_000_000)
        else:
            hits = service.list(live_only=True)[:count]
        if not hits:
            return "没有匹配的长期记忆。"
        lines = "\n".join(_format(m) for m in hits)
        return f"共 {len(hits)} 条：\n{lines}"

    definition = ToolDefinition(
        name=RECALL_MEMORIES_TOOL,
        description=_RECALL_DESCRIPTION,
        risk_level=RiskLevel.LOW,
        source=ToolSource.INTERNAL,
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search text; omit to list the most recent entries",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max entries to return (default 10, max 50)",
                },
            },
        },
        metadata={"builtin": True, "available": True},
    )
    return definition, recall_memories


def make_forget_memories(service: MemoryService) -> tuple[ToolDefinition, Any]:
    async def forget_memories(ids: list[str]) -> str:
        removed: list[str] = []
        missing: list[str] = []
        for token in ids or []:
            memory_id = service.resolve_id(token)
            if memory_id is None:
                missing.append(token)
                continue
            removed.append(service.forget(memory_id).content)
        parts = []
        if removed:
            parts.append(f"已删除 {len(removed)} 条记忆：\n" + "\n".join(f"- {c}" for c in removed))
        if missing:
            parts.append(f"未找到这些 #id：{', '.join(missing)}")
        return "\n".join(parts) if parts else "没有提供要删除的记忆。"

    definition = ToolDefinition(
        name=FORGET_MEMORIES_TOOL,
        description=_FORGET_DESCRIPTION,
        risk_level=RiskLevel.LOW,
        source=ToolSource.INTERNAL,
        input_schema={
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Memory #id values (full or short prefix) to delete",
                },
            },
            "required": ["ids"],
        },
        metadata={"builtin": True, "available": True},
    )
    return definition, forget_memories
