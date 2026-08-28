from agent_core.errors.exceptions import (
    AgentError,
    ApprovalRejectedError,
    ConfigurationError,
    MCPUnavailableError,
    PermissionDeniedError,
    ToolInvalidArgumentsError,
    ToolTimeoutError,
)


def test_base_error_defaults_to_not_retryable() -> None:
    err = AgentError("boom")
    assert err.retryable is False
    assert err.details == {}


def test_transient_errors_are_retryable() -> None:
    assert ToolTimeoutError("web_search", 30.0).retryable is True
    assert MCPUnavailableError("files", "connection refused").retryable is True


def test_permanent_errors_are_not_retryable() -> None:
    assert PermissionDeniedError("agent_a", "delete_customer").retryable is False
    assert ToolInvalidArgumentsError("search", "missing 'query'").retryable is False
    assert ConfigurationError("bad config").retryable is False
    assert ApprovalRejectedError("apr_1").retryable is False


def test_error_details_are_preserved() -> None:
    err = ToolTimeoutError("web_search", 30.0)
    assert err.details["tool"] == "web_search"
    assert err.details["timeout_seconds"] == 30.0
