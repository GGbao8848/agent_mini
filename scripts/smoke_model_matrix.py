"""Model adapter matrix: local + OpenRouter models through OUR factory.

Every probe goes through ``agent_core.runtime.model.build_model`` — the same
adapter path production runs use — so provider/adapter bugs surface here,
not in a live task. Capabilities probed per model:

  completion    plain text completion
  tool_call     function calling (bind_tools)
  json          strict single-line JSON output
  vision_user   image content block in a user message (baseline vision)
  vision_tool   image content blocks returned from a tool result (agent path)

Usage:
  uv run --env-file .env python scripts/smoke_model_matrix.py [--strict]

``--strict`` exits non-zero when any probe FAILs (CI-ready). Vision probes
are marked FAIL only under --strict; otherwise they are informational.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import struct
import sys
import time
import zlib

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from agent_core.config.settings import get_settings
from agent_core.runtime.model import build_model

get_settings()  # applies AGENT_CORE_PROXY_URL for outbound calls

OPENROUTER_MODELS = [
    "minimax/minimax-m3:free",
    "dots-studio/dots-3-note-preview:free",
]

TIMEOUT_SECONDS = 120
PROBES = ["completion", "tool_call", "json", "vision_user", "vision_tool"]


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"{city}: 22°C, sunny"


@tool
def look_at_image(path: str) -> list[dict[str, str | dict[str, str]]]:
    """Show an image file to the model (multimodal tool result)."""
    return [
        {"type": "text", "text": f"Image at {path}"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{RED_PNG_B64}"}},
    ]


def _solid_png(rgb: tuple[int, int, int], size: int = 8) -> bytes:
    """Minimal PNG (stdlib only): a solid-color square for vision probes."""
    row = b"\x00" + bytes(rgb) * size
    raw = row * size

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


RED_PNG_B64 = base64.b64encode(_solid_png((228, 40, 40))).decode()


def build_model_list() -> list[str]:
    models: list[str] = []
    if os.environ.get("LOCAL_LLM_BASE_URL"):
        local_model = os.environ.get("LOCAL_LLM_MODEL", "qwen3.8-27b")
        models.append(f"local:{local_model}")
    if os.environ.get("OPENROUTER_API_KEY"):
        models.extend(f"openrouter:{m}" for m in OPENROUTER_MODELS)
    return models


def text_of(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return " ".join(
        str(block.get("text", "")) for block in content if isinstance(block, dict)
    )


def probe_completion(spec: str) -> tuple[bool, str]:
    answer = text_of(build_model(spec).invoke("用一句话回答：1+1等于几？"))
    ok = bool(answer.strip())
    return ok, answer.strip()[:60]


def probe_tool_call(spec: str) -> tuple[bool, str]:
    llm = build_model(spec).bind_tools([get_weather])
    response = llm.invoke("北京今天天气怎么样？必须调用工具查询。")
    calls = getattr(response, "tool_calls", None) or []
    return bool(calls), calls[0]["name"] if calls else "no tool call"


def probe_json(spec: str) -> tuple[bool, str]:
    answer = text_of(
        build_model(spec).invoke(
            '只输出一个 JSON 对象，不要其他文字：{"ok": true, "n": 2}'
        )
    )
    try:
        data = json.loads(answer[answer.find("{") : answer.rfind("}") + 1])
        return data.get("ok") is True and data.get("n") == 2, answer[:60]
    except json.JSONDecodeError:
        return False, answer[:60]


def _vision_answer(spec: str, messages: list) -> str:
    response = build_model(spec).invoke(messages)
    return text_of(response).strip().lower()


def probe_vision_user(spec: str) -> tuple[bool, str]:
    data_url = f"data:image/png;base64,{RED_PNG_B64}"
    answer = _vision_answer(
        spec,
        [
            HumanMessage(
                content=[
                    {"type": "text", "text": "这张图片是什么颜色？只回答颜色名。"},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]
            )
        ],
    )
    return _is_red(answer), answer[:60]


def probe_vision_tool(spec: str) -> tuple[bool, str]:
    """The agent path: model calls a tool whose RESULT carries the image."""
    question = "调用 look_at_image 工具查看 test.png，然后告诉我图片是什么颜色。"
    llm = build_model(spec).bind_tools([look_at_image])
    first = llm.invoke(question)
    calls = getattr(first, "tool_calls", None) or []
    if not calls:
        return False, "no tool call"
    call = calls[0]
    result = look_at_image.invoke({"path": "test.png"})
    answer = _vision_answer(
        spec,
        [
            HumanMessage(content=question),
            AIMessage(content="", tool_calls=calls),
            ToolMessage(content=result, tool_call_id=call["id"]),
            HumanMessage(content="图片是什么颜色？只回答颜色名。"),
        ],
    )
    return _is_red(answer), answer[:60]


def _is_red(answer: str) -> bool:
    return any(word in answer for word in ("红", "red"))


def run_probe(spec: str, probe: str) -> tuple[bool | None, str, float]:
    """Returns (ok / None=error, detail, elapsed)."""
    functions = {
        "completion": probe_completion,
        "tool_call": probe_tool_call,
        "json": probe_json,
        "vision_user": probe_vision_user,
        "vision_tool": probe_vision_tool,
    }
    start = time.monotonic()
    try:
        ok, detail = functions[probe](spec)
    except Exception as exc:  # noqa: BLE001  (probe must survive any adapter bug)
        return None, f"{type(exc).__name__}: {exc}"[:80], time.monotonic() - start
    return ok, detail, time.monotonic() - start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit 1 on any FAIL")
    args = parser.parse_args()

    models = build_model_list()
    if not models:
        print("No models configured: set LOCAL_LLM_BASE_URL and/or OPENROUTER_API_KEY.")
        return 1
    print(f"Probing {len(models)} model(s) x {len(PROBES)} capabilities "
          f"(strict={args.strict})\n")

    failures = 0
    results: dict[str, dict[str, tuple[bool | None, str, float]]] = {}
    for spec in models:
        print(f"== {spec}")
        results[spec] = {}
        for probe in PROBES:
            ok, detail, elapsed = run_probe(spec, probe)
            results[spec][probe] = (ok, detail, elapsed)
            mark = {True: "OK  ", False: "FAIL", None: "ERR "}[ok]
            print(f"  {probe:<12} {mark} {elapsed:5.1f}s  {detail}")
            if ok is not True:
                failures += 1
        print()

    print("Matrix (OK/FAIL/ERR):")
    header = f"{'model':<44}" + "".join(f"{p:<13}" for p in PROBES)
    print(header)
    for spec, row in results.items():
        cells = "".join(
            f"{({True: 'OK', False: 'FAIL', None: 'ERR'}[row[p][0]]):<13}" for p in PROBES
        )
        print(f"{spec:<44}{cells}")

    failed = sum(1 for row in results.values() for ok, _, _ in row.values() if ok is not True)
    if args.strict and failed:
        print(f"\nSTRICT: {failed} probe(s) failed")
        return 1
    print(f"\n{failed} non-OK probe(s) (informational; use --strict to fail the run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
