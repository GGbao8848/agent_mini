"""Map ResiliencePolicy onto LangChain's native agent middleware.

One line per knob, no re-implementation: summarization, call limits, retries
and model fallbacks are all LangChain ``AgentMiddleware`` that DeepAgents
accepts via ``create_deep_agent(middleware=...)``. Model instances are built
through the same ModelFactory as the primary model, so provider keys and the
proxy environment apply to fallback/summarization models too.
"""

from __future__ import annotations

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
from agent_core.domain.resilience import SummarizationPolicy
from agent_core.runtime.model import ModelFactory


def build_middleware(spec: AgentSpec, model_factory: ModelFactory) -> list[AgentMiddleware]:
    """Build the middleware list for ``spec.resilience`` (empty when unset)."""
    policy = spec.resilience
    if policy is None or not policy.enabled:
        return []

    # The concrete middleware classes are generic with mutually incompatible
    # default parameterizations; native-wise they are all AgentMiddleware.
    middlewares: list[Any] = []
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
    return middlewares


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
