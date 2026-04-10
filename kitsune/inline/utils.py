
from __future__ import annotations

import asyncio
import logging
import os
import time
import typing
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_edit_timestamps: dict[str, float] = {}
_EDIT_COOLDOWN = 0.3

def can_edit(key: str) -> bool:
    now = time.monotonic()
    last = _edit_timestamps.get(key, 0.0)
    if now - last < _EDIT_COOLDOWN:
        return False
    _edit_timestamps[key] = now
    return True

def throttle_key(unit_id: str) -> str:
    return f"edit:{unit_id}"

async def safe_edit(
    edit_fn: typing.Callable,
    key: str,
    *args: typing.Any,
    retries: int = 3,
    **kwargs: typing.Any,
) -> bool:
    if not can_edit(key):
        await asyncio.sleep(_EDIT_COOLDOWN)

    for attempt in range(retries):
        try:
            await edit_fn(*args, **kwargs)
            return True
        except Exception as exc:
            err = str(exc).lower()
            if "message is not modified" in err:
                return True
            if "retry" in err or "flood" in err:
                wait = 2 ** attempt
                logger.debug("safe_edit: flood/retry attempt %d, sleeping %ds", attempt + 1, wait)
                await asyncio.sleep(wait)
                continue
            if "message to edit not found" in err or "invalid message" in err:
                logger.debug("safe_edit: message gone, giving up")
                return False
            logger.warning("safe_edit: unexpected error: %s", exc)
            return False
    return False

_VIDEO_EXTS = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm"})
_GIF_EXTS   = frozenset({".gif"})
_PHOTO_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})
_AUDIO_EXTS = frozenset({".mp3", ".ogg", ".flac", ".m4a", ".wav"})
_DOC_EXTS   = frozenset({".pdf", ".zip", ".tar", ".gz", ".docx", ".xlsx"})

def detect_media_type(url: str) -> str:
    try:
        path = urlparse(url).path
        ext  = os.path.splitext(path)[1].lower()
    except Exception:
        return "unknown"

    if ext in _GIF_EXTS:
        return "gif"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _PHOTO_EXTS:
        return "photo"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _DOC_EXTS:
        return "document"
    return "unknown"

def is_url(value: str) -> bool:
    try:
        r = urlparse(value)
        return r.scheme in ("http", "https") and bool(r.netloc)
    except Exception:
        return False

def validate_button(btn: typing.Any) -> str | None:
    if not isinstance(btn, dict):
        return f"Кнопка должна быть dict, получен {type(btn).__name__}"

    if "text" not in btn:
        return "Кнопка не имеет поля 'text'"

    exclusive = {"url", "callback", "input", "data"}
    present   = exclusive & btn.keys()
    if len(present) > 1:
        return f"Кнопка содержит несовместимые поля: {present}"

    if "url" in btn and not is_url(str(btn["url"])):
        return f"Некорректный URL: {btn['url']!r}"

    if "callback" in btn and not callable(btn["callback"]):
        return f"Поле 'callback' должно быть callable, получен {type(btn['callback']).__name__}"

    return None

def normalize_rows(buttons: typing.Any) -> list[list[dict]]:
    if not buttons:
        return []

    rows: list[list[dict]] = []

    for item in buttons:
        if isinstance(item, dict):
            err = validate_button(item)
            if err:
                logger.warning("normalize_rows: невалидная кнопка: %s", err)
                continue
            rows.append([item])
        elif isinstance(item, (list, tuple)):
            row: list[dict] = []
            for btn in item:
                if isinstance(btn, dict):
                    err = validate_button(btn)
                    if err:
                        logger.warning("normalize_rows: невалидная кнопка: %s", err)
                        continue
                    row.append(btn)
            if row:
                rows.append(row)
        else:
            logger.warning("normalize_rows: неожиданный тип элемента %s", type(item))

    return rows

def split_rows(buttons: list[dict], row_size: int = 3) -> list[list[dict]]:
    return [buttons[i : i + row_size] for i in range(0, len(buttons), row_size)]

def truncate_title(text: str, max_len: int = 255) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"

def strip_html(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text)

def pluralize(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if 11 <= n % 100 <= 19:
        word = many
    elif n % 10 == 1:
        word = one
    elif 2 <= n % 10 <= 4:
        word = few
    else:
        word = many
    return f"{n} {word}"

def make_progress_bar(current: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width + " 0%"
    pct   = min(current / total, 1.0)
    filled = round(pct * width)
    bar   = "█" * filled + "░" * (width - filled)
    return f"{bar} {int(pct * 100)}%"

def cleanup_units(units: dict, *, force: bool = False) -> int:
    now     = time.time()
    stale   = [uid for uid, u in units.items() if force or u.get("ttl", now + 1) < now]
    for uid in stale:
        del units[uid]
    return len(stale)

def close_button(handler: typing.Callable, text: str = "🗑 Закрыть") -> list[dict]:
    return [{"text": text, "callback": handler, "args": ("close",)}]

def back_button(handler: typing.Callable, args: tuple = (), text: str = "👈 Назад") -> dict:
    return {"text": text, "callback": handler, "args": args}

def nav_row(
    handler: typing.Callable,
    current: int,
    total: int,
    *,
    prev_args: tuple | None = None,
    next_args: tuple | None = None,
) -> list[dict]:
    row: list[dict] = []

    if current > 0:
        row.append({
            "text":     "◀️",
            "callback": handler,
            "args":     prev_args if prev_args is not None else (current - 1,),
        })

    row.append({
        "text":     f"{current + 1}/{total}",
        "callback": handler,
        "args":     ("noop",),
    })

    if current < total - 1:
        row.append({
            "text":     "▶️",
            "callback": handler,
            "args":     next_args if next_args is not None else (current + 1,),
        })

    return row
