"""Team domain model.

A Team composes already-registered agents into a coordinated unit: a lead
coordinator plus the workers it may delegate to. The coordinator spec itself
is generated at composition time (see ``orchestration.team``) so teams stay
pure data, and delegation/parallelism come from DeepAgents' native ``task``
tool — the lead issues several ``task`` calls in one turn and they run
concurrently.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TeamSpec(BaseModel):
    """Declarative definition of one coordinated agent team."""

    id: str = Field(min_length=1, description="Registry id of the generated coordinator")
    name: str = Field(min_length=1)
    worker_agent_ids: list[str] = Field(
        min_length=1, description="Registered agents the coordinator may delegate to"
    )
    lead_agent_id: str | None = Field(
        default=None,
        description="Use this registered agent as coordinator instead of the generated one",
    )
    guidance: str = Field(
        default="", description="Extra coordination instructions appended to the lead prompt"
    )
    merge_instructions: str = Field(
        default="",
        description=(
            "Team-specific MERGE rules injected into the generated coordinator prompt, "
            "e.g. 'transcribe every figure verbatim from worker output'"
        ),
    )
    metadata: dict[str, str] = Field(default_factory=dict)
