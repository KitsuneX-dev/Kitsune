
from __future__ import annotations

import re

_TG_EMOJI_VALID = re.compile(
    r'<tg-emoji\s+emoji-id\s*=\s*["\']?(\d+)["\']?\s*>(.*?)</tg-emoji>',
    re.DOTALL | re.IGNORECASE,
)
_TG_EMOJI_ANY_OPEN = re.compile(r'<tg-emoji\b[^>]*>', re.IGNORECASE)
_TG_EMOJI_ANY_CLOSE = re.compile(r'</tg-emoji\s*>', re.IGNORECASE)

_TG_ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "span", "tg-spoiler", "a", "code", "pre", "blockquote", "tg-emoji",
    "br",
}
_TG_VOID_TAGS = {"br"}
_HTML_TAG_RE = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9-]*)\b([^>]*)>')

def _normalize_tg_emoji(text: str) -> str:
    if not text or "tg-emoji" not in text.lower():
        return text
    def _fix(m: re.Match) -> str:
        emoji_id = m.group(1)
        inner = m.group(2)
        return f'<tg-emoji emoji-id="{emoji_id}">{inner}</tg-emoji>'
    return _TG_EMOJI_VALID.sub(_fix, text)

def _strip_tg_emoji(text: str) -> str:
    if not text or "tg-emoji" not in text.lower():
        return text
    text = _TG_EMOJI_ANY_OPEN.sub("", text)
    text = _TG_EMOJI_ANY_CLOSE.sub("", text)
    return text

def _sanitize_tg_html(text: str) -> str:
    if not text or "<" not in text:
        return text
    text = _normalize_tg_emoji(text)
    parts: list[str] = []
    stack: list[tuple[str, str]] = []
    pos = 0
    for m in _HTML_TAG_RE.finditer(text):
        parts.append(text[pos:m.start()])
        pos = m.end()
        is_close = m.group(1) == "/"
        tag = m.group(2).lower()
        attrs = m.group(3) or ""
        if tag not in _TG_ALLOWED_TAGS:
            continue
        if tag in _TG_VOID_TAGS:
            if not is_close:
                parts.append(f"<{tag}>")
            continue
        if not is_close:
            parts.append(f"<{tag}{attrs}>")
            stack.append((tag, attrs))
            continue
        if not stack:
            continue
        if stack[-1][0] == tag:
            stack.pop()
            parts.append(f"</{tag}>")
            continue
        idx = None
        for i in range(len(stack) - 1, -1, -1):
            if stack[i][0] == tag:
                idx = i
                break
        if idx is None:
            continue
        reopen: list[tuple[str, str]] = []
        while len(stack) > idx + 1:
            top_tag, top_attrs = stack.pop()
            parts.append(f"</{top_tag}>")
            reopen.append((top_tag, top_attrs))
        stack.pop()
        parts.append(f"</{tag}>")
        for r_tag, r_attrs in reversed(reopen):
            parts.append(f"<{r_tag}{r_attrs}>")
            stack.append((r_tag, r_attrs))
    parts.append(text[pos:])
    while stack:
        top_tag, _ = stack.pop()
        parts.append(f"</{top_tag}>")
    result = "".join(parts)
    prev = None
    empty_pair = re.compile(r'<([a-zA-Z][a-zA-Z0-9-]*)\b[^>]*>\s*</\1>')
    while prev != result:
        prev = result
        result = empty_pair.sub("", result)
    return result

def _strip_all_html(text: str) -> str:
    if not text or "<" not in text:
        return text
    return _HTML_TAG_RE.sub("", text)
