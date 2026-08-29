"""Team composition: turn a TeamSpec into a runnable coordinator agent.

Delegation and parallel execution are DeepAgents-native: the coordinator gets
the ``task`` tool (via its subagents) and is prompted to issue several
``task`` calls in one turn so independent subtasks run concurrently. This
module only assembles the spec and prompt — it does not re-implement any
execution machinery.
"""

from __future__ import annotations

from agent_core.domain.agent import AgentLimits, AgentSpec, SubAgentRef
from agent_core.domain.team import TeamSpec
from agent_core.errors.exceptions import ConfigurationError
from agent_core.registries.agents import AgentRegistry

COORDINATOR_PROMPT = """You are the lead coordinator of an agent team.

Working method, in order:
1. ANALYZE the user's task. Decide whether it is best solved by one worker,
   several workers in parallel, or direct action by yourself.
2. PLAN: record the decomposition with the todo tool before delegating.
3. DELEGATE: for every independent subtask, issue the ``task`` tool calls in
   the SAME assistant turn — several calls in one turn run in parallel, which
   is the fastest way to finish. Give each call a self-contained description
   with all context the worker needs (workers cannot see this conversation),
   and tell each worker to report back ONLY the concrete facts or results it
   obtained — short and structured, no filler.
   Only run subtasks in parallel when they do not depend on each other.
4. MERGE: synthesize the workers' results into one final answer.
   - Copy every number, date, and proper name EXACTLY as the worker that
     reported it; never recompute, convert, round, or fill in values from
     your own memory.
   - Note which worker supplied each key figure.
   - If a worker result is missing, ambiguous, or conflicting, state that
     explicitly instead of guessing.
   - Keep the final answer compact.

Choose the option that minimizes total time and cost: do not delegate what
you can answer directly.

{workers_block}{merge_block}{guidance_block}"""


def compose_team(agents: AgentRegistry, team: TeamSpec) -> AgentSpec:
    """Build (and register) the coordinator spec for ``team``.

    Workers must already be registered. Composing an id that already exists
    replaces the previous coordinator so re-composition stays idempotent.
    """
    if team.lead_agent_id is not None:
        if team.lead_agent_id in team.worker_agent_ids:
            raise ConfigurationError(
                f"Team '{team.id}': lead '{team.lead_agent_id}' cannot also be a worker",
                details={"team_id": team.id},
            )
        base = agents.get(team.lead_agent_id)
        coordinator = base.model_copy(
            update={
                "id": team.id,
                "name": team.name,
                "description": f"Coordinator '{team.name}'",
                "subagents": [
                    SubAgentRef(agent_id=worker_id) for worker_id in team.worker_agent_ids
                ],
            }
        )
        return _register(agents, coordinator)

    workers = [agents.get(worker_id) for worker_id in team.worker_agent_ids]
    workers_block = "Worker agents you may delegate to:\n" + "\n".join(
        f"- {worker.id}: {worker.description or worker.name}" for worker in workers
    )
    guidance_block = f"\nTeam-specific guidance:\n{team.guidance}\n" if team.guidance else ""
    merge_block = (
        f"\nMerge rules for this team:\n{team.merge_instructions}\n"
        if team.merge_instructions
        else ""
    )
    coordinator = AgentSpec(
        id=team.id,
        name=team.name,
        description=f"Coordinator '{team.name}'",
        system_prompt=COORDINATOR_PROMPT.format(
            workers_block=workers_block, merge_block=merge_block, guidance_block=guidance_block
        ),
        subagents=[
            SubAgentRef(agent_id=worker.id, description=worker.description or worker.name)
            for worker in workers
        ],
        limits=AgentLimits(max_subagents=max(len(workers), 1)),
    )
    return _register(agents, coordinator)


def _register(agents: AgentRegistry, coordinator: AgentSpec) -> AgentSpec:
    if coordinator.id in agents:
        agents.remove(coordinator.id)
    agents.register(coordinator)
    return coordinator
