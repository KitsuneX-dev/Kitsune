from __future__ import annotations

import shlex
import typing

def get_args(message: typing.Any) -> list[str]:
    raw = get_args_raw(message)
    if not raw:
        return []
    try:
        return list(filter(None, shlex.split(raw)))
    except ValueError:
        return list(filter(None, raw.split()))

def get_args_raw(message: typing.Any) -> str:
    text = getattr(message, "text", None) or getattr(message, "message", "")
    if not text:
        return ""
    parts = text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""

def get_args_html(message: typing.Any) -> str:
    try:
        from telethon.extensions import html as tl_html
        import copy

        raw_text = getattr(message, "text", "") or getattr(message, "message", "")
        entities = getattr(message, "entities", None) or []

        if not raw_text:
            return ""

        space_idx = raw_text.find(" ")
        if space_idx == -1:
            return ""

        command_len = space_idx + 1
        args_text   = raw_text[command_len:]

        shifted: list = []
        for entity in entities:
            new_offset = entity.offset - command_len
            if new_offset < 0:
                if new_offset + entity.length > 0:
                    e = copy.copy(entity)
                    e.length = new_offset + entity.length
                    e.offset = 0
                    shifted.append(e)
                continue
            e = copy.copy(entity)
            e.offset = new_offset
            shifted.append(e)

        return tl_html.unparse(args_text, shifted) if shifted else args_text
    except ImportError:
        return get_args_raw(message)
    except Exception:
        return get_args_raw(message)

def split_args(message: typing.Any, n: int = 1) -> tuple[list[str], str]:
    raw  = get_args_raw(message)
    head = raw.split(maxsplit=n)
    if not head:
        return [], ""
    rest = head[n] if len(head) > n else ""
    return head[:n], rest
