"""Baseline snapshots and regression comparison for eval results.

Persists one run's metrics as pure data, then scores later runs against it so
time/token/quality drift becomes a visible verdict instead of an anecdote.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agent_core.eval.model import EvalResult

TOLERANCE = 0.25
"""A passing task counts as regressed when wall time or tokens exceed baseline by this."""


class BaselineEntry(BaseModel):
    """Metrics of one task from the snapshotted run."""

    task_id: str
    name: str
    passed: bool
    wall_ms: float
    total_tokens: int
    checks_passed: int
    checks_total: int


class Baseline(BaseModel):
    """A full eval run worth of entries, saved for later comparisons."""

    created_at: str
    entries: list[BaselineEntry] = Field(default_factory=list)


class Comparison(BaseModel):
    """Verdict for one task: current run vs its baseline entry."""

    task_id: str
    label: str = ""
    verdict: Literal["improved", "regressed", "unchanged", "new", "missing"]
    detail: str = ""


def snapshot(results: list[EvalResult]) -> Baseline:
    """Reduce eval results to baseline entries."""
    return Baseline(
        created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        entries=[
            BaselineEntry(
                task_id=result.task_id,
                name=result.name,
                passed=result.passed,
                wall_ms=result.wall_ms,
                total_tokens=result.total_tokens,
                checks_passed=sum(1 for check in result.checks if check.passed),
                checks_total=len(result.checks),
            )
            for result in results
        ],
    )


def save_baseline(path: Path | str, results: list[EvalResult]) -> Baseline:
    """Write a baseline JSON file and return what was written."""
    baseline = snapshot(results)
    Path(path).write_text(baseline.model_dump_json(indent=2), encoding="utf-8")
    return baseline


def load_baseline(path: Path | str) -> Baseline:
    return Baseline.model_validate_json(Path(path).read_text(encoding="utf-8"))


def compare(
    results: list[EvalResult], baseline: Baseline, *, tolerance: float = TOLERANCE
) -> list[Comparison]:
    """Compare current results against a baseline, in current-run order."""
    base_by_id = {entry.task_id: entry for entry in baseline.entries}
    comparisons: list[Comparison] = []
    seen: set[str] = set()
    for result in results:
        seen.add(result.task_id)
        base = base_by_id.get(result.task_id)
        if base is None:
            comparisons.append(
                Comparison(
                    task_id=result.task_id,
                    label=_label(result),
                    verdict="new",
                    detail="no baseline entry",
                )
            )
            continue
        comparisons.append(
            Comparison(
                task_id=result.task_id,
                label=_label(result),
                verdict=_verdict(result, base, tolerance),
                detail=_detail(result, base),
            )
        )
    for task_id, base in base_by_id.items():
        if task_id not in seen:
            comparisons.append(
                Comparison(
                    task_id=task_id,
                    verdict="missing",
                    detail=f"baseline checks {base.checks_passed}/{base.checks_total}",
                )
            )
    return comparisons


def _label(result: EvalResult) -> str:
    """Disambiguate rows when one task runs under several modes (single/team)."""
    if result.aspects:
        return f"{result.task_id} [{'/'.join(result.aspects)}]"
    return result.task_id


def _verdict(result: EvalResult, base: BaselineEntry, tolerance: float) -> str:
    if base.passed and not result.passed:
        return "regressed"
    if not base.passed and result.passed:
        return "improved"
    if not base.passed and not result.passed:
        return "unchanged"
    regressed = result.wall_ms > base.wall_ms * (1 + tolerance) or result.total_tokens > (
        base.total_tokens * (1 + tolerance)
    )
    improved = result.wall_ms < base.wall_ms * (1 - tolerance) and result.total_tokens < (
        base.total_tokens * (1 - tolerance)
    )
    if regressed:
        return "regressed"
    if improved:
        return "improved"
    return "unchanged"


def _detail(result: EvalResult, base: BaselineEntry) -> str:
    checks = f"checks {sum(1 for check in result.checks if check.passed)}/{len(result.checks)}"
    return (
        f"wall {_delta(result.wall_ms, base.wall_ms)}, "
        f"tokens {_delta(result.total_tokens, base.total_tokens)}, "
        f"{checks} vs {base.checks_passed}/{base.checks_total}"
    )


def _delta(current: float, base: float) -> str:
    if base <= 0:
        return "n/a"
    return f"{(current - base) / base * 100:+.0f}%"


def render_comparison(comparisons: list[Comparison]) -> str:
    icon = {
        "improved": "📈",
        "regressed": "📉",
        "unchanged": "➖",
        "new": "🆕",
        "missing": "❓",
    }
    lines = ["# 基线对比", "", "| 任务 | 结论 | 明细 |", "|---|---|---|"]
    for comparison in comparisons:
        lines.append(
            f"| {comparison.label or comparison.task_id} | {icon[comparison.verdict]} "
            f"{comparison.verdict} | {comparison.detail} |"
        )
    return "\n".join(lines) + "\n"
