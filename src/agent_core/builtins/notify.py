"""Built-in ``telegram_notify`` tool: the agent messages its human.

Registered only when BOTH ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` are
set. Uses the same Tool Registry → Action Gate path as any other tool, so
agents expose it explicitly via ``AgentSpec.tools``.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import RegistryError
from agent_core.notify.telegram import TelegramChannel, telegram_chat_id, telegram_token
from agent_core.registries import ToolRegistry

TELEGRAM_NOTIFY_TOOL = "telegram_notify"


def make_telegram_notify(
    token: str,
    chat_id: str,
    *,
    channel: TelegramChannel | None = None,
) -> tuple[ToolDefinition, Any]:
    """Handler bound to a fixed bot token + chat (the operator's chat)."""
    channel = channel or TelegramChannel(token, chat_id)

    async def telegram_notify(message: str) -> str:
        message_id = await channel.send_message(message)
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
        metadata={"builtin": True, "channel": "telegram"},
    )
    return definition, telegram_notify


def register_builtin_tools(registry: ToolRegistry) -> list[str]:
    """Register ``telegram_notify`` when the channel is fully configured."""
    token = telegram_token()
    chat_id = telegram_chat_id()
    if not token or not chat_id:
        return []
    definition, handler = make_telegram_notify(token, chat_id)
    try:
        registry.register(definition, handler)
    except RegistryError:
        # Definition persisted from a previous run: re-attach the executable.
        registry.set_handler(definition.name, handler)
    return [definition.name]
