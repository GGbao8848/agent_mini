"""Notification channels: outbound messaging to the avatar's human.

Telegram first (Phase 19). Channels are configured via standard environment
variables and surface to agents as built-in tools through the normal gate.
"""

from agent_core.notify.telegram import (
    TelegramChannel,
    telegram_chat_id,
    telegram_token,
)

__all__ = ["TelegramChannel", "telegram_chat_id", "telegram_token"]
