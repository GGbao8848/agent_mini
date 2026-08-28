from agent_core.domain.action import (
    Action,
    ActionStatus,
    ApprovalRequest,
    ApprovalStatus,
    RiskLevel,
)


def test_action_defaults_to_pending_low_risk() -> None:
    action = Action(run_id="r", agent_id="a", tool_name="search_customer")
    assert action.status is ActionStatus.PENDING
    assert action.risk_level is RiskLevel.LOW


def test_approval_request_starts_pending() -> None:
    req = ApprovalRequest(
        run_id="r",
        agent_id="a",
        action_id="act",
        tool_name="delete_customer",
        risk_level=RiskLevel.CRITICAL,
    )
    assert req.status is ApprovalStatus.PENDING
    assert req.resolved_at is None


def test_risk_levels_exist() -> None:
    assert {r.value for r in RiskLevel} == {"low", "medium", "high", "critical"}
