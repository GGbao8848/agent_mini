"""Evaluation runner: execute real tasks and grade answers with verifiers."""

from __future__ import annotations

import time
from collections.abc import Mapping

from agent_core.domain.metrics import RunUsage
from agent_core.domain.task import Run
from agent_core.eval.judge import JudgeResult, build_judge_input, parse_judge_output
from agent_core.eval.model import Check, EvalResult
from agent_core.eval.tasks import RealTask
from agent_core.orchestration import Job, run_parallel
from agent_core.runtime.runtime import AgentRuntime


class EvalRunner:
    """Runs RealTask cases against one runtime and applies their verifiers."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def run_task(
        self, task: RealTask, agent_id: str, context: Mapping[str, object]
    ) -> EvalResult:
        started = time.monotonic()
        run = self._runtime.create_run(agent_id, task.prompt)
        await self._runtime.execute_run(run)
        wall_ms = (time.monotonic() - started) * 1000
        output = self._finished_output(run.id)
        return self._grade(task, run, output, wall_ms, context)

    async def run_task_fanout(
        self,
        task: RealTask,
        worker_ids: list[str],
        merge_agent_id: str,
        context: Mapping[str, object],
    ) -> EvalResult:
        """Code-driven mode: subtasks run as parallel child runs, then a merge run."""
        if not task.subtasks:
            raise ValueError(f"task '{task.id}' has no subtasks for fan-out")
        started = time.monotonic()
        children = await run_parallel(
            self._runtime,
            [
                Job(agent_id=worker_ids[i % len(worker_ids)], input=subtask)
                for i, subtask in enumerate(task.subtasks)
            ],
        )
        child_outputs = [self._finished_output(run.id) for run in children]
        merge_input = (
            "以下是各子任务的结果：\n"
            + "\n\n".join(f"[子任务{i}] {text}" for i, text in enumerate(child_outputs, start=1))
            + f"\n\n原始任务：\n{task.prompt}\n\n请基于以上结果完成任务，直接输出最终答案。"
        )
        merge_run = self._runtime.create_run(merge_agent_id, merge_input)
        await self._runtime.execute_run(merge_run)
        wall_ms = (time.monotonic() - started) * 1000
        output = self._finished_output(merge_run.id)
        usage = RunUsage()
        for run in [*children, merge_run]:
            if run.usage is not None:
                usage.add(run.usage)

        failed_children = sum(1 for run in children if run.status.value == "failed")
        checks = task.verifier(output, dict(context))
        error = merge_run.error or (
            f"{failed_children} subtask(s) failed" if failed_children else None
        )
        status = merge_run.status.value
        return EvalResult(
            task_id=task.id,
            name=task.name,
            aspects=[*task.aspects, "fanout"],
            status=status,
            passed=status == "completed" and all(c.passed for c in checks),
            wall_ms=wall_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            model_calls=usage.model_calls,
            tool_calls=usage.tool_calls,
            error=error,
            checks=checks,
            output=output,
        )

    def _grade(
        self,
        task: RealTask,
        run: Run,
        output: str,
        wall_ms: float,
        context: Mapping[str, object],
    ) -> EvalResult:
        usage = run.usage or RunUsage()
        status = run.status.value
        checks = (
            task.verifier(output, dict(context))
            if status == "completed"
            else [Check(name="run completed", passed=False, detail=run.error or status)]
        )
        return EvalResult(
            task_id=task.id,
            name=task.name,
            aspects=list(task.aspects),
            status=status,
            passed=status == "completed" and bool(checks) and all(c.passed for c in checks),
            wall_ms=wall_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            model_calls=usage.model_calls,
            tool_calls=usage.tool_calls,
            error=run.error,
            checks=checks,
            output=output,
        )

    def _finished_output(self, run_id: str) -> str:
        for event in reversed(self._runtime.tracer.get_events(run_id)):
            if event.event_type.value == "run_finished" and event.output is not None:
                return str(event.output)
        return ""

    async def run_judge(
        self, judge_agent_id: str, task: RealTask, result: EvalResult
    ) -> JudgeResult:
        """Grade a completed result's output with an LLM judge agent."""
        verdict = await self._judge_once(judge_agent_id, task, result)
        if verdict.parsed:
            return verdict
        # Small/free models occasionally return an empty message; one retry is cheap.
        return await self._judge_once(judge_agent_id, task, result)

    async def _judge_once(
        self, judge_agent_id: str, task: RealTask, result: EvalResult
    ) -> JudgeResult:
        run = self._runtime.create_run(
            judge_agent_id, build_judge_input(task.name, task.prompt, result.output)
        )
        await self._runtime.execute_run(run)
        return parse_judge_output(self._finished_output(run.id))


def collect_usage(runs: list[Run]) -> RunUsage:
    """Sum usage across several runs (fan-out children + merge)."""
    usage = RunUsage()
    for run in runs:
        if run.usage is not None:
            usage.add(run.usage)
    return usage
