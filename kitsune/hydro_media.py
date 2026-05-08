from __future__ import annotations
import asyncio
import io
import logging
import os
import time
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

_LARGE_FILE_THRESHOLD = 10 * 1024 * 1024

# Phase 3: внутренние счётчики деградации Hydrogram
_HYDRO_FAIL_THRESHOLD = 3      # после стольких подряд провалов считаем мёртвым
_HYDRO_REVIVE_TTL_S   = 300.0  # через 5 минут попробуем заново

_hydro_consecutive_fails: int = 0
_hydro_dead_until: float = 0.0


def _is_hydro_dead() -> bool:
    """Помечен ли Hydrogram как «мёртвый» (cooldown ещё не истёк)?"""
    if _hydro_dead_until <= 0:
        return False
    if time.monotonic() >= _hydro_dead_until:
        return False
    return True

def _hydro_record_failure(reason: str) -> None:
    global _hydro_consecutive_fails, _hydro_dead_until
    _hydro_consecutive_fails += 1
    if _hydro_consecutive_fails >= _HYDRO_FAIL_THRESHOLD:
        _hydro_dead_until = time.monotonic() + _HYDRO_REVIVE_TTL_S
        logger.warning(
            "hydro_media: Hydrogram marked dead for %.0fs after %d failures (%s)",
            _HYDRO_REVIVE_TTL_S, _hydro_consecutive_fails, reason,
        )
        try:
            from .core.reliability import flags as _deg_flags
            _deg_flags.mark_hydrogram_failed(reason)
        except Exception:
            pass

def _hydro_record_success() -> None:
    global _hydro_consecutive_fails, _hydro_dead_until
    if _hydro_consecutive_fails > 0 or _hydro_dead_until > 0:
        logger.info("hydro_media: Hydrogram recovered after %d failures",
                    _hydro_consecutive_fails)
    _hydro_consecutive_fails = 0
    _hydro_dead_until = 0.0
    try:
        from .core.reliability import flags as _deg_flags
        _deg_flags.clear_hydrogram_failed()
    except Exception:
        pass

def _hydro(client: typing.Any) -> typing.Any | None:
    """Получить hydrogram-клиент с учётом degradation flag.

    Возвращает None если Hydrogram «мёртв» по нашему breaker'у — тогда вся
    цепочка пойдёт через Telethon без попыток.
    """
    if _is_hydro_dead():
        return None
    return getattr(client, "hydrogram", None)

def _file_size(file: typing.Any) -> int:
    if isinstance(file, (str, Path)):
        try:
            return os.path.getsize(file)
        except Exception:
            return 0
    if hasattr(file, "seek") and hasattr(file, "tell"):
        try:
            pos = file.tell()
            file.seek(0, 2)
            size = file.tell()
            file.seek(pos)
            return size
        except Exception:
            return 0
    if isinstance(file, (bytes, bytearray)):
        return len(file)
    return 0

def _make_progress_bar(done: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    filled = int(width * done / total)
    return "█" * filled + "░" * (width - filled)

async def _edit_progress(
    client: typing.Any,
    chat_id: int,
    msg_id: int,
    current: int,
    total: int,
    caption: str,
    start_time: float,
) -> None:
    elapsed = time.monotonic() - start_time
    speed = current / elapsed if elapsed > 0 else 0
    eta = int((total - current) / speed) if speed > 0 else 0
    bar = _make_progress_bar(current, total)
    pct = int(100 * current / total) if total else 0
    done_mb = current / 1024 / 1024
    total_mb = total / 1024 / 1024
    speed_kb = speed / 1024
    text = (
        f"{caption}\n\n"
        f"<code>[{bar}]</code> {pct}%\n"
        f"📦 {done_mb:.1f} / {total_mb:.1f} МБ\n"
        f"⚡ {speed_kb:.0f} КБ/с  •  ⏱ ~{eta}с"
    )
    try:
        await client.edit_message(chat_id, msg_id, text, parse_mode="html")
    except Exception:
        pass

def _make_progress_cb(
    client: typing.Any,
    chat_id: int,
    msg_id: int,
    caption: str,
) -> typing.Callable:
    start_time = time.monotonic()
    last_update: list[float] = [0.0]

    def cb(current: int, total: int) -> None:
        now = time.monotonic()
        if now - last_update[0] < 2.0 and current < total:
            return
        last_update[0] = now
        asyncio.ensure_future(
            _edit_progress(client, chat_id, msg_id, current, total, caption, start_time)
        )

    return cb

async def send_file(
    client: typing.Any,
    chat_id: typing.Any,
    file: typing.Any,
    *,
    caption: str = "",
    parse_mode: str = "html",
    force_telethon: bool = False,
    progress_msg_id: int | None = None,
    reply_to: int | None = None,
) -> typing.Any:
    hydro = _hydro(client)

    buf_start: int = 0
    if hasattr(file, "seek") and hasattr(file, "tell"):
        try:
            buf_start = file.tell()
        except Exception:
            pass

    size = _file_size(file)
    is_large = size >= _LARGE_FILE_THRESHOLD

    if hydro and not force_telethon:
        try:
            try:
                await hydro.get_chat(chat_id)
            except Exception:
                pass
            pm = "html" if parse_mode.lower() == "html" else None
            kwargs: dict = dict(chat_id=chat_id, document=file, caption=caption, parse_mode=pm)
            if reply_to:
                kwargs["reply_to_message_id"] = reply_to
            if is_large and progress_msg_id:
                label = f"📤 Загружаю{(' — ' + caption) if caption else ''}..."
                kwargs["progress"] = _make_progress_cb(client, chat_id, progress_msg_id, label)
            result = await hydro.send_document(**kwargs)
            _hydro_record_success()
            logger.debug("hydro_media: sent via Hydrogram (%d bytes)", size)
            return result
        except Exception as exc:
            exc_str = str(exc)
            if "PEER_ID_INVALID" in exc_str:
                logger.debug("hydro_media: Hydrogram PEER_ID_INVALID for %s — falling back to Telethon", chat_id)
            else:
                logger.warning("hydro_media: Hydrogram send failed (%s), falling back to Telethon", exc)
                _hydro_record_failure(f"send_file: {type(exc).__name__}")
            if hasattr(file, "seek"):
                try:
                    file.seek(buf_start)
                except Exception:
                    pass

    if hasattr(file, "seek"):
        try:
            file.seek(buf_start)
        except Exception:
            pass

    kwargs_tl: dict = dict(caption=caption, parse_mode=parse_mode)
    if reply_to:
        kwargs_tl["reply_to"] = reply_to
    return await client.send_file(chat_id, file, **kwargs_tl)

async def send_photo(
    client: typing.Any,
    chat_id: typing.Any,
    photo: typing.Any,
    *,
    caption: str = "",
    parse_mode: str = "html",
    force_telethon: bool = False,
    reply_to: int | None = None,
) -> typing.Any:
    hydro = _hydro(client)

    buf_start: int = 0
    if hasattr(photo, "seek") and hasattr(photo, "tell"):
        try:
            buf_start = photo.tell()
        except Exception:
            pass

    if hydro and not force_telethon:
        try:
            pm = "html" if parse_mode.lower() == "html" else None
            kwargs: dict = dict(chat_id=chat_id, photo=photo, caption=caption, parse_mode=pm)
            if reply_to:
                kwargs["reply_to_message_id"] = reply_to
            result = await hydro.send_photo(**kwargs)
            _hydro_record_success()
            logger.debug("hydro_media: photo sent via Hydrogram")
            return result
        except Exception as exc:
            exc_str = str(exc)
            if "PEER_ID_INVALID" not in exc_str:
                _hydro_record_failure(f"send_photo: {type(exc).__name__}")
            logger.warning("hydro_media: Hydrogram photo send failed (%s), falling back", exc)
            if hasattr(photo, "seek"):
                try:
                    photo.seek(buf_start)
                except Exception:
                    pass

    if hasattr(photo, "seek"):
        try:
            photo.seek(buf_start)
        except Exception:
            pass

    kwargs_tl: dict = dict(caption=caption, parse_mode=parse_mode)
    if reply_to:
        kwargs_tl["reply_to"] = reply_to
    return await client.send_file(chat_id, photo, **kwargs_tl)

async def download_media(
    client: typing.Any,
    message: typing.Any,
    *,
    force_telethon: bool = False,
    progress_msg_id: int | None = None,
) -> bytes:
    hydro = _hydro(client)
    if hydro and not force_telethon:
        try:
            buf = io.BytesIO()
            file_ref = _get_hydro_file_ref(message)
            if not file_ref:
                raise ValueError("no file_ref")
            kwargs: dict = dict(file_name=buf)
            if progress_msg_id:
                chat_id = _msg_chat_id(message)
                kwargs["progress"] = _make_progress_cb(
                    client, chat_id, progress_msg_id, "📥 Скачиваю файл..."
                )
            await hydro.download_media(file_ref, **kwargs)
            buf.seek(0)
            data = buf.read()
            if data:
                _hydro_record_success()
                logger.debug("hydro_media: downloaded via Hydrogram (%d bytes)", len(data))
                return data
            raise ValueError("empty download")
        except Exception as exc:
            _hydro_record_failure(f"download_media: {type(exc).__name__}")
            logger.warning("hydro_media: Hydrogram download failed (%s), falling back to Telethon", exc)

    return await message.download_media(bytes)

def _msg_chat_id(message: typing.Any) -> int:
    cid = getattr(message, "chat_id", None)
    if cid:
        return int(cid)
    peer = getattr(message, "peer_id", None)
    if peer:
        return int(
            getattr(peer, "channel_id", None)
            or getattr(peer, "chat_id", None)
            or getattr(peer, "user_id", None)
            or 0
        )
    return 0

def _get_hydro_file_ref(message: typing.Any) -> str | None:
    media = getattr(message, "media", None)
    if media is None:
        return None
    for attr in ("document", "photo", "video", "audio", "voice", "sticker", "video_note"):
        obj = getattr(media, attr, None)
        if obj is None:
            continue
        file_id = getattr(obj, "file_id", None)
        if file_id:
            return file_id
        raw_id = getattr(obj, "id", None)
        if raw_id:
            return str(raw_id)
    return None

# ---------------------------------------------------------------------------
# Public introspection helpers (для health endpoint)
# ---------------------------------------------------------------------------

def hydro_status() -> dict:
    """Текущее состояние Hydrogram-fallback-логики."""
    remaining = max(0.0, _hydro_dead_until - time.monotonic()) if _hydro_dead_until else 0.0
    return {
        "consecutive_fails": _hydro_consecutive_fails,
        "fail_threshold": _HYDRO_FAIL_THRESHOLD,
        "dead": _is_hydro_dead(),
        "revive_in_s": round(remaining, 1),
        "revive_ttl_s": _HYDRO_REVIVE_TTL_S,
    }

def hydro_force_revive() -> None:
    """Сбросить deg-флаг Hydrogram (для команды/тестов)."""
    global _hydro_consecutive_fails, _hydro_dead_until
    _hydro_consecutive_fails = 0
    _hydro_dead_until = 0.0
    try:
        from .core.reliability import flags as _deg_flags
        _deg_flags.clear_hydrogram_failed()
    except Exception:
        pass

__all__ = [
    "send_file",
    "send_photo",
    "download_media",
    "hydro_status",
    "hydro_force_revive",
]
