"""ApprovalManager: pending approval requests + async wakeup for the gate.

The gate creates a request and awaits :meth:`ApprovalManager.wait`; the API
layer (Phase 7) resolves it via :meth:`ApprovalManager.resolve`, which wakes
the waiting gate. v1 keeps everything in memory with no TTL.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from agent_core.domain.action import Action, ApprovalRequest, ApprovalStatus
from agent_core.errors.exceptions import ApprovalError, RegistryError


class ApprovalManager:
    """In-memory store of approval requests keyed by id."""

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._resolved: dict[str, ApprovalRequest] = {}
        self._wakeups: dict[str, asyncio.Event] = {}

    def create(self, action: Action, *, reason: str = "") -> ApprovalRequest:
        """Create a pending request for ``action``."""
        request = ApprovalRequest(
            run_id=action.run_id,
            agent_id=action.agent_id,
            action_id=action.id,
            tool_name=action.tool_name,
            arguments=dict(action.arguments),
            risk_level=action.risk_level,
            reason=reason or action.reason,
        )
        self._pending[request.id] = request
        self._wakeups[request.id] = asyncio.Event()
        return request

    def get(self, approval_id: str) -> ApprovalRequest:
        """Return a pending or resolved request by id."""
        if approval_id in self._pending:
            return self._pending[approval_id]
        if approval_id in self._resolved:
            return self._resolved[approval_id]
        raise RegistryError(kind="approval", key=approval_id, detail="not found")

    def list_pending(self) -> list[ApprovalRequest]:
        """Snapshot of all pending requests."""
        return list(self._pending.values())

    async def wait(self, approval_id: str) -> ApprovalRequest:
        """Block until ``approval_id`` is resolved; returns the resolved request."""
        if approval_id not in self._wakeups:
            if approval_id in self._resolved:
                return self._resolved[approval_id]
            raise RegistryError(kind="approval", key=approval_id, detail="not found")
        await self._wakeups[approval_id].wait()
        return self._resolved[approval_id]

    def resolve(
        self,
        approval_id: str,
        status: ApprovalStatus,
        *,
        resolved_by: str = "user",
        edited_arguments: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Resolve a pending request and wake the waiting gate."""
        request = self._pending.pop(approval_id, None)
        if request is None:
            if approval_id in self._resolved:
                raise ApprovalError(
                    f"Approval '{approval_id}' is not pending",
                    details={"approval_id": approval_id},
                )
            raise RegistryError(kind="approval", key=approval_id, detail="not found")
        if status is ApprovalStatus.PENDING:
            raise ApprovalError(
                "Cannot resolve an approval to PENDING",
                details={"approval_id": approval_id},
            )
        request.status = status
        request.resolved_by = resolved_by
        request.resolved_at = datetime.now(UTC)
        if edited_arguments is not None:
            request.edited_arguments = dict(edited_arguments)
        self._resolved[approval_id] = request
        self._wakeups[approval_id].set()
        return request
