"""Real-task evaluation: five end-to-end tasks with objective verifiers.

Unlike the bench suite (strategy comparison on synthetic workloads), this
package evaluates the framework on realistic tasks — live public APIs, real
business text, buggy code — and grades each answer with deterministic
checkers (JSON schema, code execution, numeric plausibility, tool usage).
"""

from agent_core.eval.model import Check, EvalResult
from agent_core.eval.runner import EvalRunner
from agent_core.eval.tasks import ALL_TASKS, RealTask

__all__ = ["ALL_TASKS", "Check", "EvalResult", "EvalRunner", "RealTask"]
