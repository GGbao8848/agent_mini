"""MCPConnection: one live server connection with an explicit lifecycle.

The SDK session is an async context manager whose exit must happen in the
same task that entered it (anyio cancel scopes are task-bound — uvicorn runs
every request in a fresh task). A supervisor task therefore *owns* the
session: :meth:`start` spawns it and waits for the handshake, :meth:`close`
signals shutdown and joins the task, so the context always opens and closes
inside that one task no matter which request triggered it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from agent_core.domain.mcp import MCPServerDefinition
from agent_core.mcp.client import MCPSession
from agent_core.mcp.credentials import CredentialResolver  # noqa: F401  (docs)

SessionOpener = Callable[
    [MCPServerDefinition, str | None], AbstractAsyncContextManager[MCPSession]
]
"""Opens one session for a server definition; injectable for tests."""


class MCPConnection:
    """Holds one open MCP session in a dedicated owner task."""

    def __init__(
        self,
        definition: MCPServerDefinition,
        *,
        credential: str | None,
        opener: SessionOpener,
    ) -> None:
        self.definition = definition
        self.session: MCPSession | None = None
        self._credential = credential
        self._opener = opener
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._closing = asyncio.Event()
        self._start_error: Exception | None = None
        self._close_error: Exception | None = None

    async def start(self) -> MCPSession:
        """Open the underlying session (handshake included)."""
        self._task = asyncio.create_task(self._run(), name=f"mcp-conn-{self.definition.id}")
        await self._ready.wait()
        if self._start_error is not None:
            raise self._start_error
        assert self.session is not None
        return self.session

    async def close(self) -> None:
        """Close the underlying session; safe to call when never started."""
        if self._task is None:
            return
        self._closing.set()
        await self._task
        if self._close_error is not None:
            error, self._close_error = self._close_error, None
            raise error
        self._task = None
        self.session = None

    async def _run(self) -> None:
        try:
            async with self._opener(self.definition, self._credential) as session:
                self.session = session
                self._ready.set()
                await self._closing.wait()
        except Exception as exc:  # noqa: BLE001  (owner task must never die silently)
            if not self._ready.is_set():
                self._start_error = exc
                self._ready.set()
            else:
                self._close_error = exc
