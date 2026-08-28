"""Deterministic fan-out: run many child runs concurrently under one parent.

Where team delegation lets the model decide the shape of the work, this
module is the code-controlled counterpart: explicit jobs, a concurrency cap,
and full observability — every child is a real Run (parent_run_id set, its
own events, its own usage), so cancel/trace/stream all work unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from agent_core.domain.task import Run
from agent_core.runtime.runtime import AgentRuntime


@dataclass(frozen=True)
class Job:
    """One unit of work to execute as a child run."""

    agent_id: str
    input: str


async def run_parallel(
    runtime: AgentRuntime,
    jobs: Sequence[Job],
    *,
    parent: Run | None = None,
    max_concurrency: int = 5,
) -> list[Run]:
    """Execute ``jobs`` as concurrent child runs and return them in job order.

    Failing children do not raise: they come back in FAILED status so callers
    can aggregate partial results. Cancelling the awaiting task propagates to
    every child (each marks itself CANCELLED). A parent run that has already
    reached a terminal state is rejected by the runtime.
    """
    if parent is not None and parent.status.is_terminal:
        raise ValueError(f"parent run '{parent.id}' is already terminal")
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _execute(job: Job) -> Run:
        async with semaphore:
            run = runtime.create_run(
                job.agent_id,
                job.input,
                parent_run_id=parent.id if parent is not None else None,
            )
            return await runtime.execute_run(run)

    return list(await asyncio.gather(*(_execute(job) for job in jobs)))
