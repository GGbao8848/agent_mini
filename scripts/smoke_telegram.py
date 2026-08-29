"""Set up and smoke-test the Telegram notification channel.

Steps:
  1. verify the bot token (getMe) through the configured proxy
  2. discover your chat id if TELEGRAM_CHAT_ID is not set: send the bot any
     message in Telegram within 90 seconds; it is then appended to .env
  3. send a test message and confirm delivery

Usage: uv run --env-file .env python scripts/smoke_telegram.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from agent_core.config.settings import get_settings
from agent_core.errors.exceptions import AgentError
from agent_core.notify.telegram import TelegramChannel, telegram_chat_id, telegram_token

ENV_FILE = Path(".env")


async def discover_chat_id(channel: TelegramChannel, deadline_seconds: int = 90) -> str | None:
    """Poll getUpdates until the user messages the bot; returns the chat id."""
    print(
        f"TELEGRAM_CHAT_ID is not set. Open Telegram, find your bot, press Start "
        f"and send it any message (waiting up to {deadline_seconds}s)..."
    )
    offset: int | None = None
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        try:
            updates = await channel.recent_updates(offset=offset)
        except AgentError as exc:
            print(f"  getUpdates failed: {exc.message}")
            return None
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message") or update.get("edited_message") or {}
            chat = message.get("chat") or {}
            if chat.get("id") is not None:
                sender = message.get("from", {}).get("first_name", "unknown")
                print(f"  message received from {sender}: chat_id = {chat['id']}")
                return str(chat["id"])
        elapsed = int(time.monotonic() - (deadline - deadline_seconds))
        print(f"  ...nothing yet ({elapsed}/{deadline_seconds}s)")
    return None


def persist_chat_id(chat_id: str) -> None:
    """Append TELEGRAM_CHAT_ID to .env so future runs pick it up."""
    if ENV_FILE.exists():
        content = ENV_FILE.read_text()
        if "TELEGRAM_CHAT_ID" in content:
            print("  .env already mentions TELEGRAM_CHAT_ID; not modifying it")
            return
        if not content.endswith("\n"):
            content += "\n"
        content += f"TELEGRAM_CHAT_ID={chat_id}\n"
        ENV_FILE.write_text(content)
    else:
        ENV_FILE.write_text(f"TELEGRAM_CHAT_ID={chat_id}\n")
    print(f"  saved TELEGRAM_CHAT_ID={chat_id} to {ENV_FILE} (gitignored)")


async def main() -> int:
    get_settings()  # applies AGENT_CORE_PROXY_URL / NO_PROXY for outbound calls
    token = telegram_token()
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set; add it to .env first.")
        return 1

    channel = TelegramChannel(token, telegram_chat_id())
    try:
        bot = await channel.verify()
    except AgentError as exc:
        print(f"getMe failed: {exc.message}")
        print("Check the token and the proxy (AGENT_CORE_PROXY_URL) settings.")
        return 1
    username = bot.get("username", "?")
    print(f"Bot verified: @{username}")

    chat_id = telegram_chat_id()
    if not chat_id:
        chat_id = await discover_chat_id(channel)
        if not chat_id:
            print("No message received; start the bot in Telegram and rerun this script.")
            return 1
        persist_chat_id(chat_id)

    try:
        message_id = await channel.send_message(
            "✅ agent-core Telegram channel is connected.", chat_id=chat_id
        )
    except AgentError as exc:
        print(f"sendMessage failed: {exc.message}")
        return 1
    print(f"Test message delivered (message_id={message_id}, chat_id={chat_id}).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
