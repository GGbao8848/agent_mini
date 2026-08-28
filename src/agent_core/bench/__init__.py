"""Benchmark suite: run common task types end-to-end and compare strategies.

Each case is executed under one or more execution modes — a single agent,
a model-driven team (coordinator delegating via native parallel subagents),
or code-driven fan-out — and every execution records wall time and the
per-run usage metrics from Phase 9. Reports answer the framework's core
question: which strategy is faster, cheaper, and still correct?
"""

from agent_core.bench.cases import ALL_CASES, BENCH_MODES, BenchCase
from agent_core.bench.harness import (
    BenchResult,
    BenchRunner,
    CaseWiring,
)
from agent_core.bench.report import render_json, render_markdown

__all__ = [
    "ALL_CASES",
    "BENCH_MODES",
    "BenchCase",
    "BenchResult",
    "BenchRunner",
    "CaseWiring",
    "render_json",
    "render_markdown",
]
