"""ToolExecutor: run a tool handler with a timeout and normalized errors.

Sync handlers run in a worker thread so they cannot block the event loop;
async handlers are awaited directly. Every failure surfaces as one of the
unified :mod:`agent_core.errors` types with a correct ``retryable`` flag.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_core.errors.exceptions import (
    AgentError,
    ToolError,
    ToolInvalidArgumentsError,
    ToolTimeoutError,
)
from agent_core.registries import ToolHandler


class ToolExecutor:
    """Invokes tool handlers under a time budget."""

    def __init__(self, default_timeout_seconds: float = 60.0) -> None:
        self._default_timeout = default_timeout_seconds

    async def execute(
        self,
        tool_name: str,
        handler: ToolHandler,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Run ``handler(**arguments)`` and return its result."""
        timeout = timeout_seconds if timeout_seconds is not None else self._default_timeout
        try:
            return await asyncio.wait_for(self._invoke(handler, arguments), timeout=timeout)
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise ToolTimeoutError(tool_name, timeout) from exc
        except AgentError:
            raise
        except TypeError as exc:
            raise ToolInvalidArgumentsError(tool_name, str(exc)) from exc
        except Exception as exc:
            raise ToolError(
                f"Tool '{tool_name}' failed: {exc}", details={"tool": tool_name}
            ) from exc

    async def _invoke(self, handler: ToolHandler, arguments: dict[str, Any]) -> Any:
        if asyncio.iscoroutinefunction(handler):
            return await handler(**arguments)
        return await asyncio.to_thread(handler, **arguments)
