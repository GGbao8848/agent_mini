"""Map declarative policies onto agent middleware.

Resilience knobs map one-to-one onto LangChain's native ``AgentMiddleware``
(summarization, call limits, retries, fallbacks — no re-implementation).
The autonomy budget maps onto the small in-house :class:`BudgetMiddleware`,
which follows the same ``jump_to end`` pattern the native call limiter uses.
Model instances are built through the same ModelFactory as the primary
model, so provider keys and the proxy environment apply everywhere.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    SummarizationMiddleware,
    ToolRetryMiddleware,
)

from agent_core.domain.agent import AgentSpec
from agent_core.domain.autonomy import RunBudget
from agent_core.domain.metrics import RunUsage
from agent_core.domain.resilience import SummarizationPolicy
from agent_core.runtime.budget import BudgetMiddleware
from agent_core.runtime.model import ModelFactory

UsageProvider = Callable[[], RunUsage | None]


def build_middleware(
    spec: AgentSpec,
    model_factory: ModelFactory,
    usage_provider: UsageProvider | None = None,
) -> list[AgentMiddleware]:
    """Build the middleware list for ``spec.resilience`` and ``spec.autonomy``."""
    middlewares: list[Any] = []

    policy = spec.resilience
    if policy is not None and policy.enabled:
        # The concrete middleware classes are generic with mutually incompatible
        # default parameterizations; native-wise they are all AgentMiddleware.
        if policy.summarization is not None:
            middlewares.append(
                SummarizationMiddleware(
                    model=model_factory(spec.model),
                    trigger=_trigger(policy.summarization),
                    keep=("messages", policy.summarization.keep_messages),
                )
            )
        if policy.model_call_limit is not None:
            middlewares.append(
                ModelCallLimitMiddleware(
                    thread_limit=policy.model_call_limit,
                    exit_behavior=policy.call_limit_exit,
                )
            )
        if policy.model_retries:
            middlewares.append(ModelRetryMiddleware(max_retries=policy.model_retries))
        if policy.tool_retries:
            middlewares.append(ToolRetryMiddleware(max_retries=policy.tool_retries))
        if policy.model_fallbacks:
            middlewares.append(
                ModelFallbackMiddleware(
                    *[model_factory(fallback) for fallback in policy.model_fallbacks]
                )
            )

    budget = _effective_budget(spec)
    if budget is not None and usage_provider is not None:
        middlewares.append(BudgetMiddleware(budget, usage_provider))
    return middlewares


def _effective_budget(spec: AgentSpec) -> RunBudget | None:
    """Autonomy budget, with the legacy ``AgentLimits.token_budget`` as fallback."""
    if spec.autonomy is None or spec.autonomy.budget is None:
        if spec.limits.token_budget is None:
            return None
        return RunBudget(max_total_tokens=spec.limits.token_budget)
    budget = spec.autonomy.budget
    if budget.max_total_tokens is None and spec.limits.token_budget is not None:
        return budget.model_copy(update={"max_total_tokens": spec.limits.token_budget})
    return budget


def _trigger(
    policy: SummarizationPolicy,
) -> (
    tuple[Literal["tokens"], int]
    | tuple[Literal["messages"], int]
    | tuple[Literal["fraction"], float]
):
    if policy.trigger_tokens is not None:
        return ("tokens", policy.trigger_tokens)
    if policy.trigger_messages is not None:
        return ("messages", policy.trigger_messages)
    return ("fraction", policy.trigger_fraction or 0.8)
