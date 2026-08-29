"""ApprovalManager: pending approval requests + async wakeup for the gate.

The gate creates a request and awaits :meth:`ApprovalManager.wait`; the API
layer (Phase 7) resolves it via :meth:`ApprovalManager.resolve`, which wakes
the waiting gate. The pending/resolved dicts are the read side; with an
optional :class:`~agent_core.persistence.store.SqliteStore` every change is
mirrored so a restart keeps the records (requests left pending by a previous
process are rejected — their run cannot resume across a restart).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from agent_core.domain.action import Action, ApprovalKind, ApprovalRequest, ApprovalStatus
from agent_core.errors.exceptions import ApprovalError, RegistryError
from agent_core.persistence.store import SqliteStore


class ApprovalManager:
    """In-memory store of approval requests keyed by id."""

    def __init__(self, store: SqliteStore | None = None) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._resolved: dict[str, ApprovalRequest] = {}
        self._wakeups: dict[str, asyncio.Event] = {}  # process-local; not persistable
        self._store = store

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
        self._save(request)
        return request

    def create_help(
        self, *, run_id: str, agent_id: str, question: str, reason: str = ""
    ) -> ApprovalRequest:
        """Create a task-level help request (autonomy layer, no tool execution)."""
        request = ApprovalRequest(
            run_id=run_id,
            agent_id=agent_id,
            kind=ApprovalKind.TASK_HELP,
            question=question,
            reason=reason,
        )
        self._pending[request.id] = request
        self._wakeups[request.id] = asyncio.Event()
        self._save(request)
        return request

    def hydrate(self) -> None:
        """Restore persisted approvals (no-op without a store).

        Requests still pending when the previous process ended are moved to
        ``REJECTED`` with ``resolved_by="restart"``: the run that awaited them
        is marked failed by the runtime, so there is nothing left to wake.
        """
        if self._store is None:
            return
        for data in self._store.load_approvals():
            request = ApprovalRequest.model_validate_json(data)
            if request.status is ApprovalStatus.PENDING:
                request.status = ApprovalStatus.REJECTED
                request.resolved_by = "restart"
                request.resolved_at = datetime.now(UTC)
                self._save(request)
            self._resolved[request.id] = request

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
        note: str | None = None,
    ) -> ApprovalRequest:
        """Resolve a pending request and wake the waiting gate.

        ``note`` carries the human's answer for task-help requests; the gate
        feeds it back to the agent as guidance.
        """
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
        if note is not None:
            request.resolved_note = note
        self._resolved[approval_id] = request
        self._wakeups[approval_id].set()
        self._save(request)
        return request

    def _save(self, request: ApprovalRequest) -> None:
        if self._store is not None:
            self._store.save_approval(request.id, request.status.value, request.model_dump_json())
