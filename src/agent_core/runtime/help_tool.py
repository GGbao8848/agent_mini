"""Built-in ``request_help`` tool: the agent's direct line to its human.

Available to every agent with an ``autonomy`` policy. Calling it parks the
run in ``NEEDS_INPUT``; the human's answer (the approval's ``resolved_note``)
becomes the tool result, so the agent continues with real guidance instead
of guessing. This tool is deliberately NOT registered in the ToolRegistry:
it is a meta-tool whose handler is the ActionGate itself — putting it
through the normal gate path would double-gate it and subject it to tool
policies that exist for external side effects, not for asking questions.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agent_core.errors.exceptions import StateError
from agent_core.permissions.gate import ActionGate
from agent_core.runtime.context import current_run

HELP_TOOL_NAME = "request_help"


class HelpInput(BaseModel):
    """Arguments for the request_help tool."""

    question: str = Field(
        min_length=1, description="What you need from the human, stated precisely"
    )
    context: str = Field(
        default="", description="What you tried, what happened, and why you are blocked"
    )


def make_help_tool(gate: ActionGate) -> StructuredTool:
    """Build the ``request_help`` tool bound to ``gate``."""

    async def _ask(question: str, context: str = "") -> str:
        run = current_run.get()
        if run is None:
            raise StateError("request_help can only be called inside a run")
        full_question = question if not context else f"{question}\n\nContext: {context}"
        return await gate.request_help(run=run, question=full_question, reason="agent request")

    return StructuredTool.from_function(
        coroutine=_ask,
        name=HELP_TOOL_NAME,
        description=(
            "Ask the human operator for help when you are blocked or a decision is "
            "not yours to make. Use it when you have exhausted reasonable attempts, "
            "when required information is missing, or when an action is irreversible. "
            "The human's answer is returned as this tool's result."
        ),
        args_schema=HelpInput,
    )


def autonomy_prompt_addendum() -> str:
    """System-prompt note appended for agents with an autonomy policy."""
    return (
        "\n\n# Autonomy rules\n"
        "- You are verified on the quality of your final answer; make it complete "
        "and factual rather than fast.\n"
        "- Never repeat an identical tool call expecting a different result; if a "
        "call keeps failing or returning the same thing, change approach.\n"
        "- When you are genuinely blocked or a decision belongs to a human, call "
        f"the '{HELP_TOOL_NAME}' tool with a precise question and the context of what "
        "you already tried. Do not guess or fabricate instead of asking."
    )
