"""Run budget enforcement as a LangChain agent middleware.

Mirrors the native ``ModelCallLimitMiddleware`` pattern: before each model
call the live usage (via a run-scoped :class:`~agent_core.runtime.usage.UsageCollector`)
is checked against the budget. Past the hard limit the graph jumps to end
with an explanatory message (graceful finish, run completes — never a
crash); past ``warn_fraction`` the system prompt gets a one-line reminder so
the model wraps up before hitting the wall.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage

from agent_core.domain.autonomy import RunBudget
from agent_core.domain.metrics import RunUsage

UsageGetter = Callable[[], RunUsage | None]
Verdict = Literal["ok", "warn", "stop"]


def budget_verdict(usage: RunUsage | None, budget: RunBudget) -> Verdict:
    """Pure decision: ``ok`` / ``warn`` (>= warn_fraction) / ``stop`` (>= limit)."""
    if usage is None:
        return "ok"
    checks: list[tuple[int | None, int | None]] = [
        (usage.total_tokens, budget.max_total_tokens),
        (usage.model_calls, budget.max_model_calls),
        (usage.tool_calls, budget.max_tool_calls),
    ]
    warn = False
    for value, limit in checks:
        if value is None or limit is None:
            continue
        if value >= limit:
            return "stop"
        if value >= limit * budget.warn_fraction:
            warn = True
    return "warn" if warn else "ok"


def budget_stop_message(usage: RunUsage, budget: RunBudget) -> str:
    return (
        "[budget] Run budget exhausted "
        f"(tokens {usage.total_tokens}/{budget.max_total_tokens or '∞'}, "
        f"model calls {usage.model_calls}/{budget.max_model_calls or '∞'}, "
        f"tool calls {usage.tool_calls}/{budget.max_tool_calls or '∞'}). "
        "The run is ending now; report what was completed and what remains."
    )


def budget_warn_message(budget: RunBudget) -> str:
    return (
        f"[budget] You have used >= {int(budget.warn_fraction * 100)}% of this run's "
        "budget. Finish up now: consolidate what you have and produce the final "
        "answer instead of starting new work."
    )


class BudgetMiddleware(AgentMiddleware):
    """Graceful spend cap for one run; hard-stops by jumping to ``end``."""

    def __init__(self, budget: RunBudget, usage_getter: UsageGetter) -> None:
        super().__init__()
        self._budget = budget
        self._usage_getter = usage_getter
        self._warned = False

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        usage = self._usage_getter()
        if budget_verdict(usage, self._budget) == "stop":
            return self._stop_command()
        return None

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        # The runtime is async end-to-end; without this hook LangChain refuses
        # to use the middleware at all (no automatic sync->async fallback).
        usage = self._usage_getter()
        if budget_verdict(usage, self._budget) == "stop":
            return self._stop_command()
        return None

    def _stop_command(self) -> dict[str, Any]:
        usage = self._usage_getter()
        message = budget_stop_message(usage, self._budget) if usage else "[budget] exhausted"
        return {"jump_to": "end", "messages": [AIMessage(content=message)]}

    def wrap_model_call(self, request: Any, handler: Any) -> Any:
        return handler(self._with_reminder(request))

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        # In the async chain handler(request) is a coroutine — it must be
        # awaited, not returned (LangChain composes handlers per contract).
        return await handler(self._with_reminder(request))

    def _with_reminder(self, request: Any) -> Any:
        usage = self._usage_getter()
        if budget_verdict(usage, self._budget) == "warn" and not self._warned:
            self._warned = True
            reminder = budget_warn_message(self._budget)
            request = request.override(
                system_prompt=(request.system_prompt or "") + "\n\n" + reminder
            )
        return request
