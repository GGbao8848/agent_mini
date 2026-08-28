"""Benchmark harness: execute cases under different strategies, record metrics.

Modes:
- ``single``: one agent runs the whole case input.
- ``team``: a composed coordinator runs the same input and may delegate to
  workers via DeepAgents' native parallel ``task`` calls (model-driven).
- ``fanout``: code-driven — the case's independent subtasks run as concurrent
  child runs (orchestration.run_parallel), then one merge run synthesizes.

Every mode records wall time plus the Phase 9 usage metrics, so reports can
compare strategies on time, tokens, and call counts.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel

from agent_core.bench.cases import BENCH_MODES, BenchCase
from agent_core.domain.metrics import RunUsage
from agent_core.domain.task import Run
from agent_core.errors.exceptions import ConfigurationError
from agent_core.orchestration import Job, run_parallel
from agent_core.runtime.runtime import AgentRuntime


class BenchResult(BaseModel):
    """One measured execution of one case under one mode."""

    case_id: str
    mode: str
    status: str
    wall_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    error: str | None = None
    output: str = ""


@dataclass(frozen=True)
class CaseWiring:
    """Registry ids a case needs for each mode."""

    single_agent_id: str
    coordinator_id: str | None = None
    fanout_worker_ids: tuple[str, ...] = ()
    fanout_merge_agent_id: str | None = None


class BenchRunner:
    """Executes benchmark cases against one runtime."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    async def run_suite(
        self,
        cases: Sequence[BenchCase],
        wirings: Mapping[str, CaseWiring],
        *,
        modes: Sequence[str] = BENCH_MODES,
    ) -> list[BenchResult]:
        """Run every case in every mode the case allows and the caller selected."""
        results: list[BenchResult] = []
        for case in cases:
            wiring = wirings.get(case.id)
            if wiring is None:
                raise ConfigurationError(
                    f"no wiring registered for bench case '{case.id}'",
                    details={"case_id": case.id},
                )
            for mode in case.modes:
                if mode in modes:
                    results.append(await self.run_case(case, mode, wiring))
        return results

    async def run_case(self, case: BenchCase, mode: str, wiring: CaseWiring) -> BenchResult:
        if mode not in BENCH_MODES:
            raise ConfigurationError(
                f"unknown bench mode '{mode}'", details={"known": list(BENCH_MODES)}
            )
        if mode == "single":
            return await self.run_single(case, wiring.single_agent_id)
        if mode == "team":
            if wiring.coordinator_id is None:
                raise ConfigurationError(
                    f"case '{case.id}': team mode requires coordinator_id",
                    details={"case_id": case.id},
                )
            return await self.run_team(case, wiring.coordinator_id)
        return await self.run_fanout(case, wiring)

    async def run_single(self, case: BenchCase, agent_id: str) -> BenchResult:
        return await self._run_one(case, "single", agent_id, case.input)

    async def run_team(self, case: BenchCase, coordinator_id: str) -> BenchResult:
        return await self._run_one(case, "team", coordinator_id, case.input)

    async def run_fanout(self, case: BenchCase, wiring: CaseWiring) -> BenchResult:
        if not wiring.fanout_worker_ids:
            raise ConfigurationError(
                f"case '{case.id}': fanout mode requires fanout_worker_ids",
                details={"case_id": case.id},
            )
        merge_agent_id = wiring.fanout_merge_agent_id or wiring.single_agent_id
        started = time.monotonic()

        workers = wiring.fanout_worker_ids
        children = await run_parallel(
            self._runtime,
            [
                Job(agent_id=workers[i % len(workers)], input=subtask)
                for i, subtask in enumerate(case.subtasks)
            ],
        )
        child_outputs = [self._finished_output(run.id) for run in children]

        merge_input = (
            "以下是各子任务的结果：\n"
            + "\n\n".join(f"[子任务{i}] {text}" for i, text in enumerate(child_outputs, start=1))
            + f"\n\n原始任务：\n{case.input}\n\n"
            "请基于以上结果完成原始任务中要求的汇总/融合，直接输出最终答案。"
        )
        merge_run, output = await self._execute(merge_agent_id, merge_input)
        wall_ms = (time.monotonic() - started) * 1000

        usage = RunUsage()
        for run in [*children, merge_run]:
            if run.usage is not None:
                usage.add(run.usage)

        failed = sum(1 for run in children if run.status.value == "failed")
        return BenchResult(
            case_id=case.id,
            mode="fanout",
            status=merge_run.status.value,
            wall_ms=wall_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            model_calls=usage.model_calls,
            tool_calls=usage.tool_calls,
            error=f"{failed} subtask(s) failed" if failed else merge_run.error,
            output=output,
        )

    async def _run_one(
        self, case: BenchCase, mode: str, agent_id: str, task_input: str
    ) -> BenchResult:
        started = time.monotonic()
        run, output = await self._execute(agent_id, task_input)
        wall_ms = (time.monotonic() - started) * 1000
        usage = run.usage or RunUsage()
        return BenchResult(
            case_id=case.id,
            mode=mode,
            status=run.status.value,
            wall_ms=wall_ms,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
            model_calls=usage.model_calls,
            tool_calls=usage.tool_calls,
            error=run.error,
            output=output,
        )

    async def _execute(self, agent_id: str, task_input: str) -> tuple[Run, str]:
        run = self._runtime.create_run(agent_id, task_input)
        await self._runtime.execute_run(run)
        return run, self._finished_output(run.id)

    def _finished_output(self, run_id: str) -> str:
        for event in reversed(self._runtime.tracer.get_events(run_id)):
            if event.event_type.value == "run_finished" and event.output is not None:
                return str(event.output)
        return ""
