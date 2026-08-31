"""Telegram notification channel (outbound).

The avatar's line to its human: send messages and files through the official
Bot API. Configuration follows the standard environment convention (secrets are
never part of Settings or code): ``TELEGRAM_BOT_TOKEN`` and
``TELEGRAM_CHAT_ID``. HTTP calls are plain ``httpx`` with ``trust_env`` — they
go through the process proxy automatically, and ``NO_PROXY`` keeps them honest
about it.
"""

from __future__ import annotations

import os
from pathlib import Path
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
    """Thin async client over the Telegram Bot API (sendMessage/sendDocument/getMe)."""

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

    async def send_document(
        self,
        path: Path,
        *,
        chat_id: str | None = None,
        caption: str | None = None,
    ) -> int:
        """Upload a file to the chat via sendDocument; returns the message id.

        ``path`` must exist and be readable; the filename is sent as-is so
        Telegram preserves it (non-ASCII names are fine).
        """
        target = chat_id or self._chat_id
        if not target:
            raise ConfigurationError(
                "No Telegram chat id configured; set TELEGRAM_CHAT_ID "
                "(scripts/smoke_telegram.py discovers it for you)",
                details={"channel": "telegram"},
            )
        if not path.is_file():
            raise ToolError(
                f"Artifact file not found: {path}", details={"path": str(path)}
            )
        data = await self._call_upload(
            "sendDocument",
            fields={"chat_id": target},
            file_path=path,
            caption=caption,
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

    async def _call_upload(
        self,
        method: str,
        *,
        fields: dict[str, str],
        file_path: Path,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """POST a multipart upload (sendDocument) to the Bot API."""
        url = f"{TELEGRAM_API_BASE_URL}/bot{self._token}/{method}"
        upload_fields: dict[str, Any] = dict(fields)
        if caption:
            upload_fields["caption"] = caption
        try:
            async with httpx.AsyncClient(
                timeout=60.0, transport=self._transport
            ) as client:
                with file_path.open("rb") as handle:
                    response = await client.post(
                        url,
                        data=upload_fields,
                        files={"document": (file_path.name, handle)},
                    )
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
