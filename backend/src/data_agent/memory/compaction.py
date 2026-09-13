"""Conversation history compaction (N4).

core pydantic-ai 2.43 has no built-in auto-compaction, so we mount a
ProcessHistory capability whose processor folds old turns into a compact summary
request once the history exceeds a size threshold, keeping the most recent
`keep` messages verbatim (recency is what makes the coding loop work:
last gate errors, current asset ids, kernel variable mentions).

The summary is deliberately lossy-but-safe: tool-call pairs are dropped as units
(never half a call/result), and any asset/dataset ids found in raw text are
carried over in an "active refs" line so a compacted session keeps pointing at
the same canvas assets.
"""

from __future__ import annotations

import re
from typing import Any

_ID_RE = re.compile(r"\b(?:ca|ds|se|rn|ad)_[0-9a-f]{6,}\b")


def compact_messages(messages: list[Any], *, keep: int = 16, threshold: int = 24) -> list[Any]:
    """Fold messages[:len-keep] into one summary ModelRequest when len > threshold."""
    if len(messages) <= threshold:
        return messages
    old, recent = messages[:-keep], messages[-keep:]
    # never start the kept window mid tool-pair: extend old until recent begins
    # with a non-tool-result message
    while recent and _is_orphan_tool_result(recent[0]):
        old = old + [recent[0]]
        recent = recent[1:]
    summary_text = _summarize(old)
    if not summary_text:
        return messages
    return [_make_summary_request(summary_text), *recent]


def _is_orphan_tool_result(msg: Any) -> bool:
    parts = getattr(msg, "parts", None) or getattr(msg, "content", None) or []
    return any(type(p).__name__ in ("ToolReturnPart",) for p in parts)


def _summarize(old: list[Any]) -> str:
    lines: list[str] = [f"（历史已压缩：省略 {len(old)} 条早期消息）"]
    ids: list[str] = []
    user_texts: list[str] = []
    for m in old:
        role = getattr(m, "message", None) and getattr(m.message, "role", None) or \
            ("model" if type(m).__name__ == "ModelResponse" else "user")
        text = _text_of(m)
        if not text:
            continue
        ids.extend(_ID_RE.findall(text))
        if role == "user" and len(user_texts) < 5:
            user_texts.append(text[:120])
    if user_texts:
        lines.append("用户近期诉求：" + " | ".join(user_texts))
    if ids:
        uniq = list(dict.fromkeys(ids))[-12:]
        lines.append("会话中出现过的 ID（仍然有效）：" + ", ".join(uniq))
    return "\n".join(lines) if len(lines) > 1 else ""


def _text_of(msg: Any) -> str:
    out: list[str] = []
    parts = getattr(msg, "parts", None) or []
    for p in parts:
        c = getattr(p, "content", None)
        if isinstance(c, str):
            out.append(c)
        elif isinstance(getattr(p, "args", None), str):
            out.append(p.args)
    return " ".join(out)[:4000]


def _make_summary_request(text: str) -> Any:
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    return ModelRequest(parts=[
        UserPromptPart(content=f"<conversation-summary>\n{text}\n</conversation-summary>")])


def make_capability() -> Any:
    from pydantic_ai.capabilities import ProcessHistory

    async def _processor(messages: list[Any], *_args: Any, **_kw: Any) -> list[Any]:
        return compact_messages(messages)

    return ProcessHistory(_processor)
