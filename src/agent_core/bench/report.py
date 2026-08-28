"""Benchmark report rendering: markdown comparison table + JSON dump."""

from __future__ import annotations

import json
from collections.abc import Sequence

from agent_core.bench.harness import BenchResult

_HEADERS = ("Case", "Mode", "Status", "Wall (ms)", "Tokens (in/out)", "Model calls", "Tool calls")


def render_markdown(results: Sequence[BenchResult]) -> str:
    """Render results as a markdown table plus per-case strategy winners."""
    lines = [
        "# Agent Core benchmark report",
        "",
        "| " + " | ".join(_HEADERS) + " |",
        "|" + "---|" * len(_HEADERS),
    ]
    for result in results:
        lines.append(
            f"| {result.case_id} | {result.mode} | {result.status} "
            f"| {result.wall_ms:.0f} | {result.input_tokens}/{result.output_tokens} "
            f"| {result.model_calls} | {result.tool_calls} |"
        )
    lines.extend(_winners(results))
    return "\n".join(lines) + "\n"


def _winners(results: Sequence[BenchResult]) -> list[str]:
    lines: list[str] = []
    by_case: dict[str, list[BenchResult]] = {}
    for result in results:
        by_case.setdefault(result.case_id, []).append(result)
    compared = {cid: rows for cid, rows in by_case.items() if len(rows) > 1}
    if not compared:
        return lines
    lines.extend(["", "## Strategy comparison (completed runs only)", ""])
    for case_id, rows in compared.items():
        ok = [row for row in rows if row.status == "completed"]
        if not ok:
            lines.append(f"- **{case_id}**: no completed runs to compare")
            continue
        fastest = min(ok, key=lambda row: row.wall_ms)
        cheapest = min(ok, key=lambda row: row.total_tokens)
        lines.append(
            f"- **{case_id}**: fastest = `{fastest.mode}` ({fastest.wall_ms:.0f} ms), "
            f"cheapest = `{cheapest.mode}` ({cheapest.total_tokens} tokens)"
        )
    return lines


def render_json(results: Sequence[BenchResult]) -> str:
    """Serialize results for machine consumption (CI trend tracking)."""
    return json.dumps([result.model_dump() for result in results], ensure_ascii=False, indent=2)
