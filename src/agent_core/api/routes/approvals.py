"""Human-in-the-loop approval endpoints.

The Action Gate parks a run in WAITING_APPROVAL and creates a request here;
resolving it wakes the waiting run. ``decision`` is validated at the schema
level; PENDING/EXPIRED are rejected by the application layer (409).
"""

from __future__ import annotations

from fastapi import APIRouter

from agent_core.api.deps import ServiceDep
from agent_core.api.schemas import ApprovalOut, ApprovalResolveRequest
from agent_core.domain.action import ApprovalStatus

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/pending", response_model=list[ApprovalOut])
def list_pending(service: ServiceDep) -> list[ApprovalOut]:
    return [ApprovalOut.of(request) for request in service.list_pending_approvals()]


@router.get("/{approval_id}", response_model=ApprovalOut)
def get_approval(approval_id: str, service: ServiceDep) -> ApprovalOut:
    return ApprovalOut.of(service.runtime.approvals.get(approval_id))


@router.post("/{approval_id}/resolve", response_model=ApprovalOut)
def resolve_approval(
    approval_id: str, payload: ApprovalResolveRequest, service: ServiceDep
) -> ApprovalOut:
    request = service.resolve_approval(
        approval_id,
        ApprovalStatus(payload.decision),
        resolved_by=payload.resolved_by,
        edited_arguments=payload.edited_arguments,
    )
    return ApprovalOut.of(request)
