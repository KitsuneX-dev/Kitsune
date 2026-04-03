from __future__ import annotations

import logging
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

def _hydro(client: typing.Any) -> typing.Any | None:
    return getattr(client, "hydrogram", None)

async def send_file(
    client: typing.Any,
    chat_id: typing.Any,
    file: typing.Any,
    *,
    caption: str = "",
    parse_mode: str = "html",
    force_telethon: bool = False,
) -> typing.Any:
    hydro = _hydro(client)
    if hydro and not force_telethon:
        try:
            pm = "html" if parse_mode.lower() == "html" else None
            if hasattr(file, "read") or isinstance(file, (str, Path)):
                result = await hydro.send_document(
                    chat_id=chat_id,
                    document=file,
                    caption=caption,
                    parse_mode=pm,
                )
            else:
                result = await hydro.send_document(
                    chat_id=chat_id,
                    document=file,
                    caption=caption,
                    parse_mode=pm,
                )
            logger.debug("hydro_media: sent via Hydrogram")
            return result
        except Exception as exc:
            logger.warning("hydro_media: Hydrogram send failed (%s), falling back to Telethon", exc)

    return await client.send_file(
        chat_id,
        file,
        caption=caption,
        parse_mode=parse_mode,
    )

async def download_media(
    client: typing.Any,
    message: typing.Any,
    *,
    force_telethon: bool = False,
) -> bytes:
    hydro = _hydro(client)
    if hydro and not force_telethon and getattr(message, "file", None):
        try:
            import io
            buf = io.BytesIO()
            file_id = _get_hydro_file_id(message)
            if file_id:
                await hydro.download_media(file_id, file_name=buf)
                buf.seek(0)
                data = buf.read()
                if data:
                    logger.debug("hydro_media: downloaded via Hydrogram (%d bytes)", len(data))
                    return data
        except Exception as exc:
            logger.warning("hydro_media: Hydrogram download failed (%s), falling back to Telethon", exc)

    return await message.download_media(bytes)

def _get_hydro_file_id(message: typing.Any) -> str | None:
    media = getattr(message, "media", None)
    if media is None:
        return None
    for attr in ("document", "photo", "video", "audio", "voice", "sticker"):
        obj = getattr(media, attr, None)
        if obj and hasattr(obj, "id"):
            return getattr(obj, "file_id", None) or str(obj.id)
    return None
