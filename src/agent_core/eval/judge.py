"""LLM-as-judge: subjectively grade an answer's quality on a 0-10 rubric.

Deterministic verifiers (see ``tasks.py``) prove hard facts; the judge adds a
soft quality signal (accuracy, completeness, conciseness, instruction
following). The judge itself is just a registered agent — the rubric lives in
its system prompt, so execution reuses the normal Run machinery.
"""

from __future__ import annotations

import json
import re
import time

from pydantic import BaseModel, Field

JUDGE_SYSTEM_PROMPT = (
    "你是一名严格、客观的评审员。根据任务要求评估给定输出的质量，"
    "从四个维度打分（0-10，可有一位小数）：\n"
    "- accuracy: 输出是否自洽、与任务给定信息一致、无内部矛盾\n"
    "- completeness: 是否覆盖任务要求的全部要点\n"
    "- conciseness: 是否简洁、无冗余\n"
    "- instruction_following: 是否严格遵守任务的格式与指令\n"
    "\n"
    "职责边界：数据真伪由确定性校验器负责，不由你判断——"
    "不要因为看不到工具调用记录或无法核实数据来源而扣分；"
    "输出中出现的日期以输入给出的评审日期为基准判断。\n"
    "\n"
    "comment 用一句话点评，其中不要出现英文双引号。\n"
    "\n"
    "只输出一个 JSON 对象，不要任何其他文字：\n"
    '{"dimensions": {"accuracy": 0, "completeness": 0, "conciseness": 0, '
    '"instruction_following": 0}, "overall": 0, "comment": "一句话点评"}'
)


class JudgeResult(BaseModel):
    """Parsed verdict of one judge run; ``parsed=False`` means unusable output."""

    parsed: bool = False
    dimensions: dict[str, float] = Field(default_factory=dict)
    overall: float = 0.0
    comment: str = ""
    raw: str = ""


def build_judge_input(task_name: str, task_prompt: str, output: str) -> str:
    """Assemble the judge run's user input from a task and its answer."""
    return (
        f"评审日期：{time.strftime('%Y-%m-%d')}\n\n"
        f"任务名称：{task_name}\n\n任务要求：\n{task_prompt}\n\n"
        f"待评审的最终输出：\n{output}\n\n"
        "请按系统提示的四个维度评审，只输出 JSON。"
    )


_SCORE_FIELDS = re.compile(
    r'"(accuracy|completeness|conciseness|instruction_following|overall)"\s*:\s*'
    r"(-?\d+(?:\.\d+)?)"
)


def parse_judge_output(text: str) -> JudgeResult:
    """Extract the judge's JSON verdict; tolerate fenced blocks and prose."""
    for candidate in _json_candidates(text):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return _verdict_from(data, text)
    # Models sometimes emit invalid JSON (e.g. unescaped quotes inside the
    # comment); score fields are still recoverable with a targeted regex.
    fallback = _regex_fallback(text)
    if fallback is not None:
        return fallback
    return JudgeResult(parsed=False, raw=text[:500])


def _json_candidates(text: str) -> list[str]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    brace = text.find("{")
    if brace >= 0:
        candidates.append(text[brace : text.rfind("}") + 1])
    return candidates


def _verdict_from(data: dict[str, object], text: str) -> JudgeResult:
    dimensions = _dimensions(data.get("dimensions"))
    raw_overall = data.get("overall")
    if isinstance(raw_overall, (int, float)):
        overall = _clamp(raw_overall)
    elif dimensions:
        overall = sum(dimensions.values()) / len(dimensions)
    else:
        overall = 0.0
    return JudgeResult(
        parsed=True,
        dimensions=dimensions,
        overall=overall,
        comment=str(data.get("comment", "")),
        raw=text[:500],
    )


def _regex_fallback(text: str) -> JudgeResult | None:
    scores = dict(_SCORE_FIELDS.findall(text))
    if not scores:
        return None
    dimensions = {
        name: _clamp(value) for name, value in scores.items() if name != "overall"
    }
    if "overall" in scores:
        overall = _clamp(scores["overall"])
    elif dimensions:
        overall = sum(dimensions.values()) / len(dimensions)
    else:
        overall = 0.0
    comment_match = re.search(r'"comment"\s*:\s*"(.*)"\s*\}', text, re.S)
    comment = comment_match.group(1).strip() if comment_match else ""
    return JudgeResult(
        parsed=True, dimensions=dimensions, overall=overall, comment=comment, raw=text[:500]
    )


def _dimensions(raw: object) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): _clamp(value)
        for key, value in raw.items()
        if isinstance(value, (int, float))
    }


def _clamp(value: object) -> float:
    try:
        return max(0.0, min(10.0, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
