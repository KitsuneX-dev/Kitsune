from __future__ import annotations

import io
import os
import typing
from pathlib import Path

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

_SIZE_LIMIT = 2 * 1024 * 1024 * 1024  # 2 GB — лимит Telegram


def _fmt_size(size: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} ТБ"


class UploadModule(KitsuneModule):
    name        = "upload"
    description = "Загрузка и скачивание файлов через Hydrogram"
    author      = "Yushi"
    version     = "1.0"

    strings_ru = {
        "no_path":      "❌ Укажи путь к файлу: <code>.upload /path/to/file</code>",
        "not_found":    "❌ Файл не найден: <code>{path}</code>",
        "too_large":    "❌ Файл слишком большой ({size}). Лимит Telegram — 2 ГБ.",
        "starting":     "📤 Отправляю <code>{name}</code> ({size})...",
        "done":         "✅ <code>{name}</code> ({size}) — отправлено через Hydrogram за {elapsed}с",
        "done_tl":      "✅ <code>{name}</code> ({size}) — отправлено через Telethon за {elapsed}с",
        "no_media":     "❌ Ответь на сообщение с медиа.",
        "dl_starting":  "📥 Скачиваю медиа...",
        "dl_done":      "✅ Скачано {size} за {elapsed}с\n📁 <code>{path}</code>",
        "dl_err":       "❌ Ошибка при скачивании: <code>{err}</code>",
    }

    # ── .upload /path/to/file [caption] ──────────────────────────────────────

    @command("upload", required=OWNER)
    async def upload_cmd(self, event) -> None:
        args = self.get_args(event).strip()
        if not args:
            await event.reply(self.strings("no_path"), parse_mode="html")
            return

        # Разбиваем: первый токен — путь, остальное — caption
        parts = args.split(maxsplit=1)
        file_path = Path(parts[0].strip("'\""))
        caption   = parts[1] if len(parts) > 1 else ""

        if not file_path.exists():
            await event.reply(
                self.strings("not_found").format(path=file_path),
                parse_mode="html",
            )
            return

        size = file_path.stat().st_size
        if size > _SIZE_LIMIT:
            await event.reply(
                self.strings("too_large").format(size=_fmt_size(size)),
                parse_mode="html",
            )
            return

        m = await event.reply(
            self.strings("starting").format(name=file_path.name, size=_fmt_size(size)),
            parse_mode="html",
        )

        import time
        start = time.monotonic()

        from ..hydro_media import send_file as _send
        via_hydro = True
        try:
            await _send(
                self.client,
                event.chat_id,
                str(file_path),
                caption=caption,
                reply_to=event.message.id,
                progress_msg_id=m.id,
            )
        except Exception:
            # Если hydro_media упала полностью — это не должно случиться,
            # но на всякий случай пробуем Telethon напрямую
            via_hydro = False
            await self.client.send_file(
                event.chat_id,
                str(file_path),
                caption=caption,
                reply_to=event.message.id,
            )

        elapsed = round(time.monotonic() - start, 1)
        key = "done" if via_hydro else "done_tl"
        await m.edit(
            self.strings(key).format(
                name=file_path.name,
                size=_fmt_size(size),
                elapsed=elapsed,
            ),
            parse_mode="html",
        )

    # ── .download  (ответ на сообщение с медиа) ──────────────────────────────

    @command("download", required=OWNER)
    async def download_cmd(self, event) -> None:
        reply = await event.message.get_reply_message()
        if not reply or not getattr(reply, "media", None):
            await event.reply(self.strings("no_media"), parse_mode="html")
            return

        m = await event.reply(self.strings("dl_starting"), parse_mode="html")

        import time
        start = time.monotonic()

        try:
            from ..hydro_media import download_media as _dl
            data: bytes = await _dl(
                self.client,
                reply,
                progress_msg_id=m.id,
            )

            # Определяем имя файла
            fname = _guess_filename(reply)
            save_path = Path.home() / ".kitsune" / "downloads" / fname
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(data)

            elapsed = round(time.monotonic() - start, 1)
            await m.edit(
                self.strings("dl_done").format(
                    size=_fmt_size(len(data)),
                    elapsed=elapsed,
                    path=str(save_path),
                ),
                parse_mode="html",
            )
        except Exception as exc:
            await m.edit(
                self.strings("dl_err").format(err=str(exc)[:200]),
                parse_mode="html",
            )


def _guess_filename(message: typing.Any) -> str:
    """Пытается получить имя файла из медиа-объекта Telethon."""
    media = getattr(message, "media", None)
    if media is None:
        return "file"
    doc = getattr(media, "document", None)
    if doc:
        attrs = getattr(doc, "attributes", [])
        for a in attrs:
            name = getattr(a, "file_name", None)
            if name:
                return name
        mime = getattr(doc, "mime_type", "")
        ext  = _mime_to_ext(mime)
        return f"document{ext}"
    if getattr(media, "photo", None):
        return "photo.jpg"
    return "file"


def _mime_to_ext(mime: str) -> str:
    return {
        "video/mp4":        ".mp4",
        "video/webm":       ".webm",
        "audio/mpeg":       ".mp3",
        "audio/ogg":        ".ogg",
        "audio/mp4":        ".m4a",
        "image/jpeg":       ".jpg",
        "image/png":        ".png",
        "image/gif":        ".gif",
        "image/webp":       ".webp",
        "application/pdf":  ".pdf",
        "application/zip":  ".zip",
        "text/plain":       ".txt",
    }.get(mime, "")
