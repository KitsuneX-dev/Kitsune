
import io
import logging
import shlex
import typing

logger = logging.getLogger(__name__)

def get_args(message) -> typing.List[str]:
    text = getattr(message, "text", None) or getattr(message, "message", "")
    if not text:
        return []

    parts = text.split(maxsplit=1)
    if len(parts) <= 1:
        return []

    raw = parts[1]
    try:
        return list(filter(None, shlex.split(raw)))
    except ValueError:
        return list(filter(None, raw.split()))

def get_args_raw(message) -> str:
    text = getattr(message, "text", None) or getattr(message, "message", "")
    if not text:
        return ""

    parts = text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""

def get_args_html(message) -> str:
    try:
        from telethon.extensions import html as tl_html

        raw_text = getattr(message, "text", "") or getattr(message, "message", "")
        entities = getattr(message, "entities", None) or []

        if not raw_text:
            return ""

        space_idx = raw_text.find(" ")
        if space_idx == -1:
            return ""

        command_len = space_idx + 1
        args_text = raw_text[command_len:]

        shifted_entities = []
        for entity in entities:
            new_offset = entity.offset - command_len
            if new_offset < 0:
                if new_offset + entity.length > 0:
                    import copy
                    e = copy.copy(entity)
                    e.length = new_offset + entity.length
                    e.offset = 0
                    shifted_entities.append(e)
                continue
            import copy
            e = copy.copy(entity)
            e.offset = new_offset
            shifted_entities.append(e)

        if not shifted_entities:
            return args_text

        return tl_html.unparse(args_text, shifted_entities)

    except ImportError:
        return get_args_raw(message)
    except Exception:
        logger.debug("get_args_html: не удалось извлечь HTML аргументы", exc_info=True)
        return get_args_raw(message)

async def answer(
    message,
    response: typing.Union[str, bytes, io.IOBase],
    *,
    parse_mode: str = "HTML",
    link_preview: bool = False,
    reply_markup=None,
    **kwargs,
):
    if isinstance(message, int):
        client = kwargs.pop("client", None)
        if client is None:
            raise ValueError("answer: передан int message без client=")
        return await client.send_message(
            message,
            response,
            parse_mode=parse_mode,
            link_preview=link_preview,
            **kwargs,
        )

    if isinstance(response, str) and len(response.encode("utf-16le")) // 2 > 4096:
        try:
            from telethon.extensions.html import parse as _tl_parse
            from .utils import smart_split as _smart_split
            text, entities = _tl_parse(response)
            parts = list(_smart_split(text, entities, length=4096))
        except Exception:
            parts = []

        if len(parts) > 1:
            first = parts[0]
            is_own = (
                getattr(message, "out", False)
                and not getattr(message, "via_bot_id", None)
                and not getattr(message, "fwd_from", None)
            )
            try:
                if is_own:
                    result = await message.edit(first, parse_mode="html", link_preview=link_preview)
                else:
                    result = await message.respond(first, parse_mode="html", link_preview=link_preview)
                for part in parts[1:]:
                    await message.respond(part, parse_mode="html", link_preview=False)
                return result
            except Exception:
                pass

        try:
            buf = io.BytesIO(response.encode("utf-8"))
            buf.name = "command_result.txt"
            peer = getattr(message, "peer_id", None) or getattr(message, "chat_id", None)
            client = message.client
            result = await client.send_file(
                peer,
                buf,
                caption="📄 Результат слишком длинный для сообщения",
                **{k: v for k, v in kwargs.items() if k in ("reply_to",)},
            )
            if getattr(message, "out", False):
                try:
                    await message.delete()
                except Exception:
                    pass
            return result
        except Exception:
            response = response[:4090] + "…"

    is_own = (
        getattr(message, "out", False)
        and not getattr(message, "via_bot_id", None)
        and not getattr(message, "fwd_from", None)
    )

    if is_own:
        try:
            return await message.edit(
                response,
                parse_mode=parse_mode,
                link_preview=link_preview,
                **kwargs,
            )
        except Exception as e:
            if "message is not modified" in str(e).lower():
                return message
            logger.debug("answer: edit failed, falling back to respond", exc_info=True)

    if "reply_to" not in kwargs:
        reply_to = getattr(message, "reply_to_msg_id", None)
        if reply_to:
            kwargs["reply_to"] = reply_to

    return await message.respond(
        response,
        parse_mode=parse_mode,
        link_preview=link_preview,
        **kwargs,
    )

async def answer_file(
    message,
    file: typing.Union[str, bytes, io.IOBase],
    caption: typing.Optional[str] = None,
    *,
    force_document: bool = False,
    **kwargs,
):
    client = message.client

    peer = getattr(message, "peer_id", None) or getattr(message, "chat_id", None)
    if peer is None:
        raise ValueError("answer_file: не удалось определить peer из message")

    if "reply_to" not in kwargs:
        reply_to = getattr(message, "reply_to_msg_id", None)
        if reply_to:
            kwargs["reply_to"] = reply_to

    if isinstance(file, bytes):
        file = io.BytesIO(file)

    try:
        result = await client.send_file(
            peer,
            file,
            caption=caption,
            force_document=force_document,
            **kwargs,
        )
    except Exception:
        if caption:
            logger.warning("answer_file: отправка файла не удалась, шлём текст", exc_info=True)
            return await answer(message, caption)
        raise

    if getattr(message, "out", False):
        try:
            await message.delete()
        except Exception:
            pass

    return result

def escape_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

def get_chat_id(message) -> typing.Optional[int]:
    if isinstance(message, int):
        return message

    peer = getattr(message, "peer_id", None)
    if peer is not None:
        chat_id = getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None) or getattr(peer, "user_id", None)
        if chat_id:
            return chat_id

    chat = getattr(message, "chat", None)
    if chat is not None:
        return getattr(chat, "id", None)

    return getattr(message, "chat_id", None)

