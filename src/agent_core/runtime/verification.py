"""Runtime self-verification: judge the output, self-fix, escalate.

Reuses the judge protocol from ``eval/judge.py`` (pure prompt/parse
functions, no execution path of its own). The judge is a registered agent —
by default the built-in ``verifier`` spec, registered lazily on first use —
executed as a nested run (``parent_run_id`` points at the verified run) and
charged back to the parent's usage. Failing verification triggers up to
``max_rounds`` self-fix rounds (re-running the same graph with the critique
attached); when rounds are exhausted the run escalates to a human via the
Action Gate's help channel, or completes marked unverified.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_core.domain.autonomy import VerificationPolicy

if TYPE_CHECKING:
    # Import-time cycle: agent_core.eval pulls in orchestration → runtime.
    from agent_core.eval.judge import JudgeResult

VERIFIER_SYSTEM_PROMPT = (
    "You are a strict output verifier. Given an original task and an assistant's "
    "final answer, judge whether the answer actually fulfils the task.\n"
    "Score three dimensions 0-10 (one decimal allowed):\n"
    "- accuracy: internally consistent, no contradictions, no fabricated facts\n"
    "- completeness: covers everything the task asks for\n"
    "- instruction_following: respects the task's format and constraints\n"
    "\n"
    "Do not penalize answers for things the task never required. Do not try to "
    "verify facts you cannot check from the task itself.\n"
    "\n"
    "Respond with ONLY a JSON object, no other text:\n"
    '{"dimensions": {"accuracy": 0, "completeness": 0, "instruction_following": 0}, '
    '"overall": 0, "comment": "one-sentence verdict without double quotes"}'
)


def build_verification_input(task_input: str, output: str) -> str:
    """User input for the judge run."""
    return (
        f"Original task:\n{task_input}\n\n"
        f"Assistant's final answer:\n{output}\n\n"
        "Judge the answer against the task. Respond with the JSON verdict only."
    )


def build_fix_input(original_input: str, previous_output: str, feedback: str) -> str:
    """Task input for a self-fix round: original task plus the critique."""
    return (
        f"{original_input}\n\n"
        "---\n"
        "Your previous answer below was judged insufficient. Produce an improved "
        "final answer to the ORIGINAL task above, fixing the issues pointed out.\n\n"
        f"Previous answer:\n{previous_output}\n\n"
        f"Verifier feedback:\n{feedback}"
    )


def passed(result: JudgeResult | None, policy: VerificationPolicy) -> bool:
    """A missing or unparsable verdict never blocks the run (fail-open verifier)."""
    return result is not None and result.parsed and result.overall >= policy.min_overall


def parse_verifier_output(text: str) -> JudgeResult:
    """Parse the verifier's JSON verdict (same contract as the eval judge).

    Imported lazily: ``agent_core.eval`` pulls in the orchestration package,
    which imports this runtime — a top-level import here would be circular.
    """
    from agent_core.eval.judge import parse_judge_output

    return parse_judge_output(text)


def attempt_record(result: JudgeResult | None) -> dict[str, Any]:
    """Log-friendly record of one verification attempt for ``run.metadata``."""
    if result is None:
        return {"overall": None, "comment": "verifier unavailable"}
    if not result.parsed:
        return {"overall": None, "comment": "verifier output unparsable", "raw": result.raw[:200]}
    return {"overall": result.overall, "comment": result.comment}


def verification_question(
    task_input: str, output: str, attempts: list[dict[str, object]]
) -> str:
    """Question for the escalation help request after failed verification."""
    scores = ", ".join(
        f"round {i + 1}: {attempt.get('overall')}" for i, attempt in enumerate(attempts)
    )
    return (
        "My answer failed automatic quality verification and self-fix rounds are "
        f"exhausted (verdicts: {scores}).\n\n"
        f"Task: {task_input[:2000]}\n\n"
        f"My current answer: {output[:2000]}\n\n"
        "Please tell me how to proceed; your reply will guide my final attempt."
    )
