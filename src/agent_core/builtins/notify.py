"""Built-in Telegram tools: message the human, and ship them a finished artifact.

Registered always, so the console can show their availability state. Both are
marked unavailable (and their handlers raise a clear error) until BOTH
``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` are set. Use the same Tool
Registry → Action Gate path as any other tool.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_core.artifacts import artifact_abs_path, task_workspace
from agent_core.domain.tool import ToolDefinition, ToolSource
from agent_core.errors.exceptions import RegistryError, ToolError
from agent_core.notify.telegram import TelegramChannel, telegram_chat_id, telegram_token
from agent_core.registries import ToolRegistry
from agent_core.runtime.context import get_current_task_id

TELEGRAM_NOTIFY_TOOL = "telegram_notify"
TELEGRAM_SEND_ARTIFACT_TOOL = "telegram_send_artifact"


def _available(token: str | None, chat_id: str | None) -> bool:
    return bool(token and chat_id)


def make_telegram_notify(
    token: str | None,
    chat_id: str | None,
    *,
    channel: TelegramChannel | None = None,
) -> tuple[ToolDefinition, Any]:
    """Handler bound to a fixed bot token + chat (the operator's chat)."""
    available = _available(token, chat_id)

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


def make_telegram_send_artifact(
    token: str | None,
    chat_id: str | None,
    workspace_dir: str,
    *,
    channel: TelegramChannel | None = None,
) -> tuple[ToolDefinition, Any]:
    """Handler that uploads a finished workspace artifact to the human's chat.

    ``path`` is task-relative (the same convention as the console's artifact
    download): resolved against the *current* task's private directory, so an
    agent sends ``album/index.html`` and it resolves under
    ``workspace/tasks/<task_id>/album/index.html``. The workspace is the only
    place files are served from, so ``..`` escapes, absolute paths and dotfiles
    are rejected before the file is ever opened.
    """
    available = _available(token, chat_id)
    workspace = Path(workspace_dir)

    async def telegram_send_artifact(path: str) -> str:
        if not token or not chat_id:
            raise ToolError(
                "telegram_send_artifact is not available: TELEGRAM_BOT_TOKEN / "
                "TELEGRAM_CHAT_ID are not configured",
                details={"tool": TELEGRAM_SEND_ARTIFACT_TOOL},
            )
        task_id = get_current_task_id()
        # Files live in the task's own directory; fall back to the shared root
        # for one-shot runs (no task context).
        target = None
        if task_id is not None:
            target = artifact_abs_path(task_workspace(workspace, task_id), path)
        if target is None:
            target = artifact_abs_path(workspace, path)
        if target is None:
            raise ToolError(
                f"Artifact '{path}' not found in workspace — it must be a "
                "task-relative path (e.g. album/index.html)",
                details={"path": path, "tool": TELEGRAM_SEND_ARTIFACT_TOOL},
            )
        resolved = channel or TelegramChannel(token, chat_id)
        message_id = await resolved.send_document(target)
        return f"Sent {target.name} to chat {chat_id} (message {message_id})."

    definition = ToolDefinition(
        name=TELEGRAM_SEND_ARTIFACT_TOOL,
        description=(
            "Send a finished artifact (pptx, pdf, png, zip, ...) to your human "
            "operator via Telegram as a downloadable file. Use it when you have "
            "produced a deliverable in the workspace and want to hand it over. "
            "Pass the workspace-relative path of the file, e.g. "
            "'album/2026-spring.pptx' or 'report.pdf'."
        ),
        source=ToolSource.PYTHON,
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative path of the artifact file to send",
                },
            },
            "required": ["path"],
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
    return definition, telegram_send_artifact


def register_builtin_tools(registry: ToolRegistry, settings: Any = None) -> list[str]:
    """Register the Telegram tools (unavailable until the channel is configured).

    ``settings`` is optional for backwards-compatibility with the existing test
    call sites; when absent the workspace default is used.
    """
    token, chat_id = telegram_token(), telegram_chat_id()
    workspace = (
        getattr(settings, "workspace_dir", "./workspace") if settings is not None else "./workspace"
    )
    names: list[str] = []
    for definition, handler in (
        make_telegram_notify(token, chat_id),
        make_telegram_send_artifact(token, chat_id, workspace),
    ):
        try:
            registry.register(definition, handler)
        except RegistryError:
            # Definition persisted from a previous run or boot: refresh metadata
            # (availability tracks the current credentials) and re-attach handler.
            registry.replace_with_handler(definition, handler)
        names.append(definition.name)
    return names
