"""Real-task evaluation: five end-to-end tasks with objective verifiers.

Unlike the bench suite (strategy comparison on synthetic workloads), this
package evaluates the framework on realistic tasks — live public APIs, real
business text, buggy code — and grades each answer with deterministic
checkers (JSON schema, code execution, numeric plausibility, tool usage).
On top of the hard checks it offers an optional LLM-as-judge quality score
and baseline snapshots with regression comparison across runs.
"""

from agent_core.eval.baseline import (
    Baseline,
    BaselineEntry,
    Comparison,
    compare,
    load_baseline,
    render_comparison,
    save_baseline,
    snapshot,
)
from agent_core.eval.judge import (
    JUDGE_SYSTEM_PROMPT,
    JudgeResult,
    build_judge_input,
    parse_judge_output,
)
from agent_core.eval.model import Check, EvalResult
from agent_core.eval.runner import EvalRunner
from agent_core.eval.tasks import ALL_TASKS, RealTask

__all__ = [
    "ALL_TASKS",
    "Baseline",
    "BaselineEntry",
    "Check",
    "Comparison",
    "EvalResult",
    "EvalRunner",
    "JUDGE_SYSTEM_PROMPT",
    "JudgeResult",
    "RealTask",
    "build_judge_input",
    "compare",
    "load_baseline",
    "parse_judge_output",
    "render_comparison",
    "save_baseline",
    "snapshot",
]
