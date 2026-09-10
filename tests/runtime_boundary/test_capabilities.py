"""Capability resolver tests (R22, invariant I-23).

The point of the resolver is that ONE object answers "can this agent call tool
X" — the builder, the action gate and the console all read it. These tests pin
that the three agree, and that each input to the intersection is honoured.
"""

from __future__ import annotations

from agent_core.capabilities import CapabilityResolver, CapabilityState
from agent_core.domain.action import RiskLevel
from agent_core.domain.agent import AgentSpec
from agent_core.domain.permission import PermissionDecision, PermissionRule, PermissionSpec
from agent_core.domain.tool import ToolDefinition


def make_resolver(
    tools: list[ToolDefinition],
    *,
    skills: dict[str, list[str]] | None = None,
    has_handler: bool = True,
) -> CapabilityResolver:
    return CapabilityResolver(
        lambda: tools,
        has_handler=lambda _name: has_handler,
        skill_allowed_tools=(lambda sid: (skills or {}).get(sid)),
    )


def tool(name: str, risk: RiskLevel = RiskLevel.LOW) -> ToolDefinition:
    return ToolDefinition(name=name, description=name, risk_level=risk)


def test_empty_binding_exposes_all_registered_tools() -> None:
    resolver = make_resolver([tool("a"), tool("b")])
    assert resolver.exposed_names(AgentSpec(id="x", name="X")) == ["a", "b"]


def test_explicit_binding_is_a_hard_whitelist() -> None:
    resolver = make_resolver([tool("a"), tool("b")])
    spec = AgentSpec(id="x", name="X", tools=["a"])
    assert resolver.exposed_names(spec) == ["a"]
    assert resolver.decide(spec, "b") is PermissionDecision.DENY


def test_skill_allowed_tools_narrow_capabilities() -> None:
    resolver = make_resolver(
        [tool("read_file"), tool("write_file")], skills={"ro": ["read_file"]}
    )
    spec = AgentSpec(id="x", name="X", skills=["ro"])
    # The narrow set is enforced at build time (buildable) and call time.
    assert resolver.buildable_names(spec) == ["read_file"]
    assert resolver.decide(spec, "write_file") is PermissionDecision.DENY


def test_skill_with_empty_allowlist_does_not_lock_out() -> None:
    resolver = make_resolver([tool("run_code")], skills={"free": []})
    spec = AgentSpec(id="x", name="X", skills=["free"])
    assert resolver.buildable_names(spec) == ["run_code"]


def test_unknown_skill_is_ignored_not_locking() -> None:
    resolver = make_resolver([tool("run_code")], skills={})
    spec = AgentSpec(id="x", name="X", skills=["ghost"])
    assert resolver.decide(spec, "run_code") is PermissionDecision.ALLOW


def test_risk_floor_upgrades_allow_to_approval() -> None:
    resolver = make_resolver([tool("danger", RiskLevel.HIGH)])
    entry = resolver.effective(AgentSpec(id="x", name="X")).get("danger")
    assert entry is not None
    assert entry.decision is PermissionDecision.REQUIRE_APPROVAL
    assert entry.state is CapabilityState.RESTRICTED
    # Restricted still means "exposed and callable (with review)".
    assert resolver.decide(AgentSpec(id="x", name="X"), "danger") is (
        PermissionDecision.REQUIRE_APPROVAL
    )


def test_permission_deny_wins() -> None:
    resolver = make_resolver([tool("a")])
    spec = AgentSpec(
        id="x",
        name="X",
        permissions=PermissionSpec(
            rules=[PermissionRule(tool="a", decision=PermissionDecision.DENY)]
        ),
    )
    assert resolver.decide(spec, "a") is PermissionDecision.DENY


def test_unavailable_tool_is_excluded_from_exposed_and_reported() -> None:
    resolver = CapabilityResolver(
        lambda: [tool("a"), tool("b")],
        has_handler=lambda name: name == "a",
    )
    spec = AgentSpec(id="x", name="X")
    assert resolver.exposed_names(spec) == ["a"]
    entry = resolver.effective(spec).get("b")
    assert entry is not None
    assert entry.state is CapabilityState.UNAVAILABLE
    assert entry.exposed is False


def test_flagged_unavailable_tool_is_excluded_from_implicit_set() -> None:
    flagged = ToolDefinition(name="b", metadata={"available": False})
    resolver = make_resolver([tool("a"), flagged])
    assert resolver.exposed_names(AgentSpec(id="x", name="X")) == ["a"]


def test_explicit_binding_returns_names_verbatim() -> None:
    """An explicit binding is not filtered — the registry fails fast instead."""
    resolver = make_resolver([tool("a")])
    assert resolver.buildable_names(AgentSpec(id="x", name="X", tools=["ghost"])) == ["ghost"]


def test_resolver_and_policy_agree() -> None:
    """I-23: the gate's decision (ActionPolicy) is the resolver's decision."""
    from agent_core.permissions.policy import ActionPolicy

    skills = {"ro": ["read_file"]}
    resolver = make_resolver([tool("read_file"), tool("write_file")], skills=skills)
    policy = ActionPolicy(resolver=resolver)
    spec = AgentSpec(id="x", name="X", skills=["ro"])

    for definition in [tool("read_file"), tool("write_file")]:
        assert policy.evaluate(spec, definition) == resolver.decide(spec, definition.name)


def test_explain_reports_the_reason() -> None:
    resolver = make_resolver([tool("read_file"), tool("write_file")], skills={"ro": ["read_file"]})
    spec = AgentSpec(id="x", name="X", skills=["ro"])
    assert "allowed_tools" in resolver.explain(spec, "write_file")
