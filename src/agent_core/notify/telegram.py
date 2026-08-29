"""Telegram notification channel (outbound).

The avatar's line to its human: send messages through the official Bot API.
Configuration follows the standard environment convention (secrets are never
part of Settings or code): ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID``.
HTTP calls are plain ``httpx`` with ``trust_env`` — they go through the
process proxy automatically, and ``NO_PROXY`` keeps them honest about it.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from agent_core.errors.exceptions import ConfigurationError, ToolError

TELEGRAM_API_BASE_URL = "https://api.telegram.org"
_LONG_POLL_SECONDS = 25


def telegram_token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def telegram_chat_id() -> str | None:
    return os.environ.get("TELEGRAM_CHAT_ID")


class TelegramChannel:
    """Thin async client over the Telegram Bot API (sendMessage/getMe/getUpdates)."""

    def __init__(
        self,
        token: str,
        chat_id: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._transport = transport  # test seam; None = real network (trust_env proxy)

    async def verify(self) -> dict[str, Any]:
        """Validate the token via getMe; returns the bot's info dict."""
        data = await self._call("getMe")
        result: dict[str, Any] = data["result"]
        return result

    async def recent_updates(self, *, offset: int | None = None) -> list[dict[str, Any]]:
        """Long-poll getUpdates once (~25s); used by the setup flow to find the chat."""
        params: dict[str, Any] = {"timeout": _LONG_POLL_SECONDS}
        if offset is not None:
            params["offset"] = offset
        data = await self._call("getUpdates", params=params, extra_timeout=_LONG_POLL_SECONDS)
        return data.get("result") or []

    async def send_message(self, text: str, *, chat_id: str | None = None) -> int:
        """Send ``text`` to the chat; returns the Telegram message id."""
        target = chat_id or self._chat_id
        if not target:
            raise ConfigurationError(
                "No Telegram chat id configured; set TELEGRAM_CHAT_ID "
                "(scripts/smoke_telegram.py discovers it for you)",
                details={"channel": "telegram"},
            )
        data = await self._call(
            "sendMessage",
            json={"chat_id": target, "text": text},
        )
        return int(data["result"]["message_id"])

    async def _call(
        self,
        method: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        extra_timeout: float = 0.0,
    ) -> dict[str, Any]:
        url = f"{TELEGRAM_API_BASE_URL}/bot{self._token}/{method}"
        try:
            async with httpx.AsyncClient(
                timeout=30.0 + extra_timeout, transport=self._transport
            ) as client:
                response = await client.post(url, json=json, params=params)
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
        except httpx.HTTPError as exc:
            raise ToolError(
                f"Telegram API unreachable: {exc}",
                retryable=True,
                details={"method": method},
            ) from exc
        if not payload.get("ok"):
            raise ToolError(
                f"Telegram API rejected {method}: {payload.get('description', 'unknown error')}",
                details={"method": method},
            )
        return payload
