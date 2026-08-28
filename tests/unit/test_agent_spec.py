import pytest
from pydantic import ValidationError

from agent_core.domain.agent import AgentLimits, AgentSpec, SubAgentRef
from agent_core.domain.permission import PermissionDecision, PermissionRule, PermissionSpec


def test_minimal_agent_spec() -> None:
    spec = AgentSpec(id="assistant", name="Assistant")
    assert spec.limits.max_depth == 2
    assert spec.tools == []
    assert spec.permissions is None


def test_blank_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentSpec(id="", name="Assistant")


def test_full_agent_spec() -> None:
    spec = AgentSpec(
        id="researcher",
        name="Researcher",
        model="openai:gpt-4o-mini",
        system_prompt="You research things.",
        skills=["web_research"],
        tools=["web_search"],
        subagents=[SubAgentRef(agent_id="writer")],
        permissions=PermissionSpec(
            rules=[PermissionRule(tool="delete_*", decision=PermissionDecision.DENY)]
        ),
        limits=AgentLimits(max_depth=3, token_budget=100_000),
    )
    assert spec.permissions is not None
    assert spec.permissions.evaluate("delete_customer") is PermissionDecision.DENY
    assert spec.limits.max_depth == 3


def test_limits_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        AgentLimits(max_depth=0)
    with pytest.raises(ValidationError):
        AgentLimits(timeout_seconds=-1)
