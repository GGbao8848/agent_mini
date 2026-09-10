"""Error→Lesson: turn a user correction into a durable constraint.

The first memory attempt extracted memories automatically every turn and was
rolled back as noisy. This module is the opposite: a tiny, deterministic hint
appended to the prompt **only when the user's message looks like a correction**
("不对", "以后要…", "记住…", "don't do X again"). It nudges the agent to call
``remember`` with type ``lesson``/``error_fix`` — no LLM extraction, no cost on
ordinary turns, and nothing is written unless the agent decides it is durable.

Retrieval (in :mod:`agent_core.memory`) is what closes the loop: on a later,
similar request the lesson is surfaced and the agent avoids the repeat.
"""

from __future__ import annotations

import re

# Obvious correction / standing-instruction phrases. Kept deliberately small
# and high-precision: a false negative just means the agent may not record a
# lesson, while a false positive would nudge on ordinary turns.
_CORRECTION_RE = re.compile(
    r"(不对|错了|不是这样|别再|不要再|以后|下次|记住|务必|一定要|"
    r"不该|应该先|纠正|请注意|注意：|"
    r"\bdon'?t\b|\bnever\b|\balways\b|\bfrom now on\b|\bremember\b|\binstead\b)",
    re.IGNORECASE,
)


def looks_like_correction(text: str | None) -> bool:
    """True when ``text`` reads like a correction or standing instruction."""
    if not text:
        return False
    return _CORRECTION_RE.search(text) is not None


def lesson_hint(text: str | None) -> str:
    """A short system-prompt nudge to record a lesson, or empty.

    Empty on ordinary turns so nothing is injected (and nothing is recorded)
    unless the user is actually correcting the agent.
    """
    if not looks_like_correction(text):
        return ""
    return (
        "\n\n## 纠错提示\n"
        "用户本轮像是在纠正你或给出长期要求。如果这是一条以后都应遵守的经验，"
        "请在回复后调用 `remember` 工具，type 用 `lesson` 或 `error_fix`，"
        "内容写成一句可复用的规则（例：生成 PPT 后必须先确认文件存在再报成功）。"
        "如果只是本次的一次性要求，就不要记录。\n"
    )
