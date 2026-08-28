"""Orchestration: composing and coordinating multiple agents.

Two complementary control styles over the same native machinery:

- :mod:`orchestration.team` — model-driven: compose registered workers under
  a coordinator whose prompt makes DeepAgents' parallel ``task`` calls the
  default strategy. The model analyzes the task and decides.
- :mod:`orchestration.fanout` — code-driven: explicit jobs executed as
  concurrent child runs with a concurrency cap, for deterministic pipelines.
"""

from agent_core.orchestration.fanout import Job, run_parallel
from agent_core.orchestration.team import compose_team

__all__ = ["Job", "compose_team", "run_parallel"]
