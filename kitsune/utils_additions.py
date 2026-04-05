# 🦊 Kitsune Userbot — utils_additions.py
# Добавь эти функции в свой utils.py (или импортируй отдельно).
#
# Решает проблему: модули делают message.edit() вручную, что ломается
# когда команда вызвана не из своего сообщения.
#
# Основное добавление:
#   answer()       — умный ответ: edit если своё, respond если чужое
#   answer_file()  — умная отправка файла
#   get_args_raw() — аргументы командой строкой (без split)
#   get_args_html() — аргументы с HTML-разметкой

import io
import logging
import shlex
import typing

logger = logging.getLogger(__name__)


# ─── get_args helpers ─────────────────────────────────────────────────────────

def get_args(message) -> typing.List[str]:
    """
    Аргументы команды как список (split по пробелам, учитывает кавычки).

    Пример:
        message.text = ".cmd foo bar baz"
        get_args(message)  # ["foo", "bar", "baz"]

        message.text = '.cmd "hello world" baz'
        get_args(message)  # ["hello world", "baz"]
    """
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
        # Незакрытые кавычки — вернём как есть
        return list(filter(None, raw.split()))


def get_args_raw(message) -> str:
    """
    Аргументы команды одной строкой (всё после первого слова).

    Пример:
        message.text = ".cmd hello world"
        get_args_raw(message)  # "hello world"
    """
    text = getattr(message, "text", None) or getattr(message, "message", "")
    if not text:
        return ""

    parts = text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def get_args_html(message) -> str:
    """
    Аргументы команды с сохранением HTML-форматирования.
    Использует telethon entities для восстановления разметки.

    Пример:
        message.text = ".cmd <b>жирный</b> текст"
        get_args_html(message)  # "<b>жирный</b> текст"

    Требует telethon. Если нет entities — возвращает get_args_raw().
    """
    try:
        from herokutl.extensions import html as tl_html

        raw_text = getattr(message, "text", "") or getattr(message, "message", "")
        entities = getattr(message, "entities", None) or []

        if not raw_text:
            return ""

        # Находим где заканчивается команда (первое слово)
        space_idx = raw_text.find(" ")
        if space_idx == -1:
            return ""

        command_len = space_idx + 1
        args_text = raw_text[command_len:]

        # Пересчитываем entity offset относительно начала аргументов
        shifted_entities = []
        for entity in entities:
            new_offset = entity.offset - command_len
            if new_offset < 0:
                # entity начинается до аргументов
                if new_offset + entity.length > 0:
                    # entity частично захватывает аргументы
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
        # Нет telethon — вернём plain text
        return get_args_raw(message)
    except Exception:
        logger.debug("get_args_html: не удалось извлечь HTML аргументы", exc_info=True)
        return get_args_raw(message)


# ─── answer() — умный ответ ───────────────────────────────────────────────────

async def answer(
    message,
    response: typing.Union[str, bytes, io.IOBase],
    *,
    parse_mode: str = "HTML",
    link_preview: bool = False,
    reply_markup=None,
    **kwargs,
):
    """
    Умный ответ на сообщение.

    Логика:
      • Своё сообщение (message.out=True) + нет fwd/via_bot → edit()
      • Чужое сообщение → respond() / reply()
      • Если передан reply_markup → используй inline (реализуй под свой стек)

    :param message: telethon Message (или int chat_id — тогда только send).
    :param response: Текст или файло-подобный объект.
    :param parse_mode: "HTML" по умолчанию.
    :param link_preview: Показывать превью ссылок.
    :param reply_markup: Inline keyboard (dict / list of lists).
    :param kwargs: Доп. параметры для edit/respond/send_message.

    :return: Отправленное/отредактированное сообщение.

    Примеры:
        await answer(message, "Готово!")
        await answer(message, f"<b>Результат:</b> {result}")
        await answer(message, "Текст", reply_to=some_msg_id)
    """
    # Если message — просто int (chat_id), отправляем напрямую
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

    # Определяем: редактировать или отвечать
    is_own = (
        getattr(message, "out", False)
        and not getattr(message, "via_bot_id", None)
        and not getattr(message, "fwd_from", None)
    )

    if is_own:
        # Редактируем своё сообщение
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
            # При ошибке редактирования — пробуем ответить
            logger.debug("answer: edit failed, falling back to respond", exc_info=True)

    # Отвечаем на чужое (или если edit упал)
    # Если есть reply_to_msg_id — отвечаем в тот же тред
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


# ─── answer_file() — умная отправка файла ────────────────────────────────────

async def answer_file(
    message,
    file: typing.Union[str, bytes, io.IOBase],
    caption: typing.Optional[str] = None,
    *,
    force_document: bool = False,
    **kwargs,
):
    """
    Умная отправка файла — всегда в нужный чат, убирает исходное сообщение.

    :param message: telethon Message.
    :param file: URL строка, bytes, путь к файлу или file-like объект.
    :param caption: Подпись к файлу.
    :param force_document: Отправить как документ (не как медиа).
    :param kwargs: Доп. параметры для send_file.

    :return: Отправленное сообщение.

    Примеры:
        await answer_file(message, "result.txt")
        await answer_file(message, b"binary data", caption="Вот файл")
        await answer_file(message, "https://example.com/photo.jpg", caption="Фото")
    """
    client = message.client

    # Определяем peer
    peer = getattr(message, "peer_id", None) or getattr(message, "chat_id", None)
    if peer is None:
        raise ValueError("answer_file: не удалось определить peer из message")

    # reply_to для тредов
    if "reply_to" not in kwargs:
        reply_to = getattr(message, "reply_to_msg_id", None)
        if reply_to:
            kwargs["reply_to"] = reply_to

    # Оборачиваем bytes в BytesIO
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
        # Если не удалось отправить файл — шлём caption как текст
        if caption:
            logger.warning("answer_file: отправка файла не удалась, шлём текст", exc_info=True)
            return await answer(message, caption)
        raise

    # Удаляем исходное сообщение если оно наше
    if getattr(message, "out", False):
        try:
            await message.delete()
        except Exception:
            pass

    return result


# ─── Короткие утилиты ─────────────────────────────────────────────────────────

def escape_html(text: str) -> str:
    """Экранировать HTML спецсимволы."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def get_chat_id(message) -> typing.Optional[int]:
    """
    Универсально получить chat_id из сообщения.
    Работает с telethon Message, aiogram Message и int.
    """
    if isinstance(message, int):
        return message

    # telethon
    peer = getattr(message, "peer_id", None)
    if peer is not None:
        chat_id = getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None) or getattr(peer, "user_id", None)
        if chat_id:
            return chat_id

    # aiogram / pyrogram
    chat = getattr(message, "chat", None)
    if chat is not None:
        return getattr(chat, "id", None)

    return getattr(message, "chat_id", None)


# ─── Документация / Примеры использования ────────────────────────────────────
#
# В loader.py / base Module добавь:
#
#   from .utils_additions import answer, answer_file, get_args, get_args_raw, get_args_html
#
# Потом в модулях вместо:
#   await event.edit("Готово!")        # ломается на чужих сообщениях
#   await event.respond("Готово!")     # не редактирует свои
#
# Пиши:
#   await utils.answer(message, "Готово!")           # всегда правильно
#   await utils.answer_file(message, file, "Файл")   # для файлов
#
# Аргументы команды:
#   args = utils.get_args(message)        # ["foo", "bar"]
#   raw  = utils.get_args_raw(message)    # "foo bar"
#   html = utils.get_args_html(message)   # "<b>жирный</b> текст"
