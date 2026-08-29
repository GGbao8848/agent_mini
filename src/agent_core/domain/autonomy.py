"""Autonomy policies: declarative agent-level self-governance knobs.

Pure data, like :class:`~agent_core.domain.resilience.ResiliencePolicy`. The
runtime maps these onto concrete guards: budgets become a budget middleware,
the loop guard hooks into the Action Gate, verification wraps the run's
output in a verify → self-fix → escalate loop. Everything is opt-in per
agent — ``autonomy=None`` keeps the plain, ungoverned behaviour.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RunBudget(BaseModel):
    """Hard spend limits for one run; exhausting any of them ends the run gracefully.

    ``warn_fraction`` is where the runtime starts reminding the model to wrap
    up, so the hard stop is rarely hit with work still unfinished.
    """

    max_total_tokens: int | None = Field(default=None, gt=0)
    max_model_calls: int | None = Field(default=None, gt=0)
    max_tool_calls: int | None = Field(default=None, gt=0)
    warn_fraction: float = Field(default=0.8, gt=0, le=1.0)

    def has_any_limit(self) -> bool:
        return any(
            v is not None
            for v in (self.max_total_tokens, self.max_model_calls, self.max_tool_calls)
        )


class LoopGuardPolicy(BaseModel):
    """When to consider an agent stuck: repeated identical tool calls or a
    streak of tool failures.

    ``max_identical_calls`` counts calls with the same tool+arguments
    fingerprint: the Nth identical call is nudged (the model sees a "you are
    looping, change approach" message instead of a result), the (N+1)th
    escalates to a human. ``max_consecutive_failures`` counts tool errors in
    a row; with a loop guard configured, tool failures are surfaced to the
    model as messages (soft) instead of aborting the run.
    """

    max_identical_calls: int = Field(default=3, ge=2)
    max_consecutive_failures: int = Field(default=3, ge=1)


class VerificationPolicy(BaseModel):
    """Post-execution quality gate: judge the output, self-fix, then escalate.

    The judge is a registered agent (``judge_agent_id``); verification runs
    are nested runs charged to the parent's usage. After ``max_rounds`` fix
    rounds, ``on_fail`` decides between escalating to a human (default) and
    completing with the result marked unverified in ``run.metadata``.
    """

    enabled: bool = False
    judge_agent_id: str = "verifier"
    min_overall: float = Field(default=7.0, ge=0, le=10)
    max_rounds: int = Field(default=1, ge=0)
    on_fail: Literal["escalate", "accept"] = "escalate"


class AutonomyPolicy(BaseModel):
    """Agent-level autonomy configuration; None on AgentSpec means ungoverned."""

    budget: RunBudget | None = None
    loop_guard: LoopGuardPolicy | None = None
    verification: VerificationPolicy | None = None

    @property
    def enabled(self) -> bool:
        """True when any guard is active (agents get the help tool + prompt note)."""
        return (
            self.budget is not None
            or self.loop_guard is not None
            or (self.verification is not None and self.verification.enabled)
        )
