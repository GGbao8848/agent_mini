"""LoopGuard: per-run detection of repeated tool calls and failure streaks.

The guard is consulted by the Action Gate before every tool execution (only
for agents with ``autonomy.loop_guard`` configured). It fingerprints each
call (tool name + canonical JSON of the arguments) and answers with one of
three verdicts:

- ``allow``: proceed as normal.
- ``nudge``: do not execute; the returned message is fed to the model as the
  tool result so it can change approach.
- ``escalate``: do not execute; the gate raises a task-level help request
  and waits for a human.

Tool failures are recorded too — with a loop guard configured the gate
surfaces failures to the model as messages (soft) instead of aborting, so a
failure streak nudges/escalates instead of killing the run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from agent_core.domain.autonomy import LoopGuardPolicy


@dataclass(frozen=True)
class LoopVerdict:
    action: Literal["allow", "nudge", "escalate"]
    message: str = ""


def fingerprint(tool_name: str, arguments: dict[str, Any]) -> str:
    """Stable hash of a tool call's identity (key order normalized)."""
    payload = json.dumps([tool_name, arguments], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode()).hexdigest()  # noqa: S324  (identity, not security)


class LoopGuard:
    """Bookkeeping for all runs in this process; the gate asks before executing."""

    def __init__(self) -> None:
        # run_id -> [fingerprints in call order]
        self._calls: dict[str, list[str]] = {}
        # run_id -> consecutive tool failures
        self._failures: dict[str, int] = {}

    def check(
        self, run_id: str, tool_name: str, arguments: dict[str, Any], policy: LoopGuardPolicy
    ) -> LoopVerdict:
        """Verdict for the upcoming call; nudged calls count toward the limit."""
        mark = fingerprint(tool_name, arguments)
        history = self._calls.setdefault(run_id, [])
        identical = history.count(mark) + 1  # including the call being decided
        if identical > policy.max_identical_calls:
            return LoopVerdict(
                action="escalate",
                message=(
                    f"Tool '{tool_name}' has already been called {identical - 1} times with "
                    "identical arguments without making progress."
                ),
            )
        if identical == policy.max_identical_calls:
            history.append(mark)
            return LoopVerdict(
                action="nudge",
                message=(
                    f"[loop guard] You have called '{tool_name}' with identical arguments "
                    f"{identical - 1} times already. This call was NOT executed. Change your "
                    "approach, adjust the arguments, or call request_help if you are blocked."
                ),
            )
        return LoopVerdict(action="allow")

    def record_called(self, run_id: str, tool_name: str, arguments: dict[str, Any]) -> None:
        """Record an executed call (fingerprints drive the repetition counters)."""
        self._calls.setdefault(run_id, []).append(fingerprint(tool_name, arguments))

    def record_result(self, run_id: str, *, ok: bool) -> int:
        """Record the outcome; returns the consecutive failure count after it."""
        if ok:
            self._failures[run_id] = 0
            return 0
        self._failures[run_id] = self._failures.get(run_id, 0) + 1
        return self._failures[run_id]

    def forget_run(self, run_id: str) -> None:
        """Drop bookkeeping when the run reaches a terminal state."""
        self._calls.pop(run_id, None)
        self._failures.pop(run_id, None)
