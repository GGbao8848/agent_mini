"""Eval data models (shared by tasks, runner, and reports)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_core.eval.judge import JudgeResult


class Check(BaseModel):
    """One objective assertion about a task's answer."""

    name: str
    passed: bool
    detail: str = ""


class EvalResult(BaseModel):
    """Outcome of one real task: metrics plus verifier verdicts."""

    task_id: str
    name: str
    aspects: list[str] = Field(default_factory=list)
    status: str
    passed: bool = False
    wall_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    error: str | None = None
    checks: list[Check] = Field(default_factory=list)
    output: str = ""
    judge: JudgeResult | None = None

    @property
    def failed_checks(self) -> list[Check]:
        return [check for check in self.checks if not check.passed]
