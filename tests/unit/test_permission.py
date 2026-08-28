from agent_core.domain.permission import PermissionDecision, PermissionRule, PermissionSpec


def test_exact_match_rule_wins() -> None:
    spec = PermissionSpec(
        rules=[PermissionRule(tool="delete_customer", decision=PermissionDecision.DENY)]
    )
    assert spec.evaluate("delete_customer") is PermissionDecision.DENY


def test_first_match_wins() -> None:
    spec = PermissionSpec(
        rules=[
            PermissionRule(tool="delete_*", decision=PermissionDecision.REQUIRE_APPROVAL),
            PermissionRule(tool="delete_customer", decision=PermissionDecision.DENY),
        ]
    )
    assert spec.evaluate("delete_customer") is PermissionDecision.REQUIRE_APPROVAL
    assert spec.evaluate("delete_all") is PermissionDecision.REQUIRE_APPROVAL


def test_default_applies_when_no_rule_matches() -> None:
    spec = PermissionSpec(default=PermissionDecision.DENY)
    assert spec.evaluate("anything") is PermissionDecision.DENY


def test_default_allow_allows_unlisted_tools() -> None:
    spec = PermissionSpec(
        rules=[PermissionRule(tool="delete_*", decision=PermissionDecision.DENY)]
    )
    assert spec.evaluate("read_customer") is PermissionDecision.ALLOW


def test_require_approval_decision() -> None:
    spec = PermissionSpec(
        rules=[PermissionRule(tool="update_customer", decision=PermissionDecision.REQUIRE_APPROVAL)]
    )
    assert spec.evaluate("update_customer") is PermissionDecision.REQUIRE_APPROVAL
