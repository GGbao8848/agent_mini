"""MCPConnection: one live server connection with an explicit lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from agent_core.domain.mcp import MCPServerDefinition
from agent_core.mcp.client import MCPSession

SessionOpener = Callable[[MCPServerDefinition, str | None], AbstractAsyncContextManager[MCPSession]]
"""Opens one session for a server definition; injectable for tests."""


class MCPConnection:
    """Holds one open MCP session; start/close are managed by :class:`MCPManager`."""

    def __init__(
        self,
        definition: MCPServerDefinition,
        *,
        credential: str | None,
        opener: SessionOpener,
    ) -> None:
        self.definition = definition
        self._credential = credential
        self._opener = opener
        self._cm: AbstractAsyncContextManager[MCPSession] | None = None
        self.session: MCPSession | None = None

    async def start(self) -> MCPSession:
        """Open the underlying session (handshake included)."""
        self._cm = self._opener(self.definition, self._credential)
        self.session = await self._cm.__aenter__()
        return self.session

    async def close(self) -> None:
        """Close the underlying session; safe to call when never started."""
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)
            self._cm = None
            self.session = None
