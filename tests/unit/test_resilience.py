"""Resilience policy validation and native-middleware mapping tests."""

import pytest
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    SummarizationMiddleware,
    ToolRetryMiddleware,
)
from pydantic import ValidationError

from agent_core.domain.agent import AgentSpec
from agent_core.domain.resilience import ResiliencePolicy, SummarizationPolicy
from agent_core.runtime.middleware import build_middleware


def spec_with(policy: ResiliencePolicy | None) -> AgentSpec:
    return AgentSpec(id="a", name="A", model="openai:gpt-4o-mini", resilience=policy)


def stub_model_factory(model_spec: str | None):
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model="gpt-4o-mini", api_key="test-key")


class TestPolicyValidation:
    def test_summarization_requires_exactly_one_trigger(self) -> None:
        with pytest.raises(ValidationError):
            SummarizationPolicy()
        with pytest.raises(ValidationError):
            SummarizationPolicy(trigger_tokens=100, trigger_messages=5)
        policy = SummarizationPolicy(trigger_fraction=0.7)
        assert policy.trigger_fraction == 0.7

    def test_empty_policy_reports_disabled(self) -> None:
        assert ResiliencePolicy().enabled is False

    def test_any_knob_enables_policy(self) -> None:
        assert ResiliencePolicy(tool_retries=1).enabled is True
        assert ResiliencePolicy(model_fallbacks=["openai:gpt-4o-mini"]).enabled is True

    def test_retries_bounded(self) -> None:
        with pytest.raises(ValidationError):
            ResiliencePolicy(tool_retries=9)


class TestBuildMiddleware:
    def test_no_policy_builds_nothing(self) -> None:
        assert build_middleware(spec_with(None), stub_model_factory) == []

    def test_summarization_mapping(self) -> None:
        policy = ResiliencePolicy(
            summarization=SummarizationPolicy(trigger_tokens=2000, keep_messages=4)
        )
        middlewares = build_middleware(spec_with(policy), stub_model_factory)

        assert len(middlewares) == 1
        summarizer = middlewares[0]
        assert isinstance(summarizer, SummarizationMiddleware)
        assert summarizer.trigger == ("tokens", 2000)
        assert summarizer.keep == ("messages", 4)

    def test_call_limit_mapping(self) -> None:
        policy = ResiliencePolicy(model_call_limit=3, call_limit_exit="error")
        (limit,) = build_middleware(spec_with(policy), stub_model_factory)

        assert isinstance(limit, ModelCallLimitMiddleware)
        assert limit.thread_limit == 3
        assert limit.exit_behavior == "error"

    def test_retry_mapping(self) -> None:
        policy = ResiliencePolicy(model_retries=2, tool_retries=1)
        middlewares = build_middleware(spec_with(policy), stub_model_factory)

        kinds = {type(m).__name__ for m in middlewares}
        assert kinds == {"ModelRetryMiddleware", "ToolRetryMiddleware"}
        retry = next(m for m in middlewares if isinstance(m, ModelRetryMiddleware))
        assert retry.max_retries == 2
        tool_retry = next(m for m in middlewares if isinstance(m, ToolRetryMiddleware))
        assert tool_retry.max_retries == 1

    def test_fallback_models_built_via_factory(self) -> None:
        policy = ResiliencePolicy(model_fallbacks=["openai:gpt-4o-mini", "openai:gpt-4o"])
        (fallback,) = build_middleware(spec_with(policy), stub_model_factory)

        assert isinstance(fallback, ModelFallbackMiddleware)
        assert len(fallback.models) == 2

    def test_full_stack_order(self) -> None:
        policy = ResiliencePolicy(
            summarization=SummarizationPolicy(trigger_messages=10),
            model_call_limit=5,
            model_retries=1,
            tool_retries=1,
            model_fallbacks=["openai:gpt-4o-mini"],
        )
        middlewares = build_middleware(spec_with(policy), stub_model_factory)

        assert [type(m).__name__ for m in middlewares] == [
            "SummarizationMiddleware",
            "ModelCallLimitMiddleware",
            "ModelRetryMiddleware",
            "ToolRetryMiddleware",
            "ModelFallbackMiddleware",
        ]
