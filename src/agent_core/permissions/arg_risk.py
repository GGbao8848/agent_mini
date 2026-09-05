"""Argument-level approval rules: risk that depends on *what* is invoked.

Static risk levels cover what a tool can do in principle, but some tools only
cross a boundary for specific arguments — e.g. ``run_code`` on the host backend
touching the system when the command drives a system package manager
(``apt-get install ...``). Registered rules upgrade an ALLOW decision to
REQUIRE_APPROVAL for exactly those invocations; every other call keeps the
static decision.

Rules are process-local callables registered by the tool's own module at boot
(the same lifecycle as tool handlers). The match is a guardrail for a trusted
household agent, not a security boundary — an obfuscated command can walk
around a pattern match; only the container backend truly confines execution.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from typing import Any

ArgumentRiskRule = Callable[[Mapping[str, Any]], bool]

_lock = threading.Lock()
_rules: dict[str, ArgumentRiskRule] = {}


def register_argument_risk_rule(tool_name: str, rule: ArgumentRiskRule) -> None:
    with _lock:
        _rules[tool_name] = rule


def clear_argument_risk_rules(tool_name: str | None = None) -> None:
    with _lock:
        if tool_name is None:
            _rules.clear()
        else:
            _rules.pop(tool_name, None)


def needs_argument_approval(tool_name: str, arguments: Mapping[str, Any]) -> bool:
    """True when a registered rule flags this invocation for human approval."""
    with _lock:
        rule = _rules.get(tool_name)
    if rule is None:
        return False
    try:
        return bool(rule(arguments))
    except Exception:
        # A broken rule must never silently *lower* the bar or crash the run —
        # fail loud in logs, and ask for approval on the safe side.
        return True
