"""Built-in ``telegram_notify`` tool: the agent messages its human.

Registered always, so the console can show its availability state. It is
marked unavailable (and its handler raises a clear error) until BOTH
``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` are set. Uses the same Tool
Registry → Action Gate path as any other tool.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import RegistryError, ToolError
from agent_core.notify.telegram import TelegramChannel, telegram_chat_id, telegram_token
from agent_core.registries import ToolRegistry

TELEGRAM_NOTIFY_TOOL = "telegram_notify"


def make_telegram_notify(
    token: str | None,
    chat_id: str | None,
    *,
    channel: TelegramChannel | None = None,
) -> tuple[ToolDefinition, Any]:
    """Handler bound to a fixed bot token + chat (the operator's chat)."""
    available = bool(token and chat_id)

    async def telegram_notify(message: str) -> str:
        if not token or not chat_id:
            raise ToolError(
                "telegram_notify is not available: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID "
                "are not configured",
                details={"tool": TELEGRAM_NOTIFY_TOOL},
            )
        resolved = channel or TelegramChannel(token, chat_id)
        message_id = await resolved.send_message(message)
        return f"Delivered to chat {chat_id} (message {message_id})."

    definition = ToolDefinition(
        name=TELEGRAM_NOTIFY_TOOL,
        description=(
            "Send a message to your human operator via Telegram. Use it to report "
            "completed work, ask for input when blocked, or flag anything urgent. "
            "Keep the message self-contained and readable."
        ),
        source=ToolSource.PYTHON,
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message text to send"},
            },
            "required": ["message"],
        },
        metadata={
            "builtin": True,
            "channel": "telegram",
            "available": available,
            "availability_reason": (
                "" if available else "未配置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID"
            ),
        },
    )
    return definition, telegram_notify


def register_builtin_tools(registry: ToolRegistry) -> list[str]:
    """Register ``telegram_notify`` (unavailable until the channel is configured)."""
    definition, handler = make_telegram_notify(telegram_token(), telegram_chat_id())
    try:
        registry.register(definition, handler)
    except RegistryError:
        # Definition persisted from a previous run or boot: refresh metadata
        # (availability tracks the current credentials) and re-attach handler.
        registry.replace_with_handler(definition, handler)
    return [definition.name]
