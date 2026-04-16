from __future__ import annotations

import asyncio
import logging
import re
import typing

from telethon import events
from telethon.tl.types import Message

from .rate_limiter import RateLimiter
from .security import SecurityManager, OWNER, SUDO

logger = logging.getLogger(__name__)

_FLOOD_REPLY = "⏳ <b>Too fast. Please wait a moment.</b>"

ALL_TAGS = [
    "no_commands", "only_commands", "out", "in_", "only_messages", "editable",
    "no_media", "only_media", "only_photos", "only_videos", "only_audios",
    "only_docs", "only_stickers", "only_inline", "only_channels", "only_groups",
    "only_pm", "no_pm", "no_channels", "no_groups", "no_inline", "no_stickers",
    "no_docs", "no_audios", "no_videos", "no_photos", "no_forwards", "no_reply",
    "no_mention", "mention", "only_reply", "only_forwards",
    "startswith", "endswith", "contains", "regex", "filter", "from_id", "chat_id",
]

def _mime_type(message: Message) -> str:
    if not isinstance(message, Message):
        return ""
    media = getattr(message, "media", None)
    if not media:
        return ""
    doc = getattr(media, "document", None)
    if doc:
        return getattr(doc, "mime_type", "") or ""
    return getattr(media, "mime_type", "") or ""

def _get_chat_id(message: Message) -> int:
    chat_id = getattr(message, "chat_id", None)
    if chat_id is not None:
        return int(chat_id)
    peer = getattr(message, "peer_id", None)
    if peer is None:
        return 0
    if hasattr(peer, "channel_id"):
        return -peer.channel_id
    if hasattr(peer, "chat_id"):
        return -peer.chat_id
    if hasattr(peer, "user_id"):
        return peer.user_id
    return 0

def _check_tag(tag: str, func: typing.Callable, m: Message) -> bool:
    mapping: dict[str, typing.Callable[[], bool]] = {
        "out":           lambda: bool(getattr(m, "out", True)),
        "in_":           lambda: not getattr(m, "out", True),
        "only_messages": lambda: isinstance(m, Message),
        "editable":      lambda: (
            not getattr(m, "out", False) and not getattr(m, "fwd_from", False)
            and not getattr(m, "sticker", False) and not getattr(m, "via_bot_id", False)
        ),
        "no_media":      lambda: not isinstance(m, Message) or not getattr(m, "media", False),
        "only_media":    lambda: isinstance(m, Message) and bool(getattr(m, "media", False)),
        "only_photos":   lambda: _mime_type(m).startswith("image/"),
        "only_videos":   lambda: _mime_type(m).startswith("video/"),
        "only_audios":   lambda: _mime_type(m).startswith("audio/"),
        "only_stickers": lambda: bool(getattr(m, "sticker", False)),
        "only_docs":     lambda: bool(getattr(m, "document", False)),
        "only_inline":   lambda: bool(getattr(m, "via_bot_id", False)),
        "only_channels": lambda: bool(getattr(m, "is_channel", False)) and not getattr(m, "is_group", False),
        "only_groups":   lambda: bool(getattr(m, "is_group", False)) or (
            not getattr(m, "is_private", False) and not getattr(m, "is_channel", False)
        ),
        "only_pm":       lambda: bool(getattr(m, "is_private", False)),
        "no_pm":         lambda: not getattr(m, "is_private", False),
        "no_channels":   lambda: not getattr(m, "is_channel", False),
        "no_groups":     lambda: not getattr(m, "is_group", False) or bool(getattr(m, "is_private", False)),
        "no_inline":     lambda: not getattr(m, "via_bot_id", False),
        "no_stickers":   lambda: not getattr(m, "sticker", False),
        "no_docs":       lambda: not getattr(m, "document", False),
        "no_audios":     lambda: not _mime_type(m).startswith("audio/"),
        "no_videos":     lambda: not _mime_type(m).startswith("video/"),
        "no_photos":     lambda: not _mime_type(m).startswith("image/"),
        "no_forwards":   lambda: not getattr(m, "fwd_from", False),
        "no_reply":      lambda: not getattr(m, "reply_to_msg_id", False),
        "only_reply":    lambda: bool(getattr(m, "reply_to_msg_id", False)),
        "only_forwards": lambda: bool(getattr(m, "fwd_from", False)),
        "mention":       lambda: bool(getattr(m, "mentioned", False)),
        "no_mention":    lambda: not getattr(m, "mentioned", False),
        "startswith":    lambda: isinstance(m, Message) and (m.raw_text or "").startswith(getattr(func, "startswith", "")),
        "endswith":      lambda: isinstance(m, Message) and (m.raw_text or "").endswith(getattr(func, "endswith", "")),
        "contains":      lambda: isinstance(m, Message) and getattr(func, "contains", "") in (m.raw_text or ""),
        "filter":        lambda: callable(getattr(func, "filter", None)) and func.filter(m),
        "from_id":       lambda: getattr(m, "sender_id", None) == getattr(func, "from_id", None),
        "chat_id":       lambda: _get_chat_id(m) == getattr(func, "chat_id", None),
        "regex":         lambda: isinstance(m, Message) and bool(re.search(getattr(func, "regex", ""), m.raw_text or "")),
    }
    if tag not in mapping:
        return False
    if not getattr(func, tag, False):
        return False
    try:
        return not mapping[tag]()
    except Exception:
        return False

def _should_skip_watcher(func: typing.Callable, message: Message) -> bool:
    return any(_check_tag(tag, func, message) for tag in ALL_TAGS)


class _CoOwnerMessageProxy:
    """
    Прокси над сообщением co-owner.
    edit() / respond() / reply() — отправляют новое сообщение от основного клиента,
    потому что редактировать чужое сообщение невозможно.
    Все остальные атрибуты проксируются к оригинальному message.
    """

    def __init__(self, message: typing.Any, client: typing.Any) -> None:
        object.__setattr__(self, "_msg", message)
        object.__setattr__(self, "_client", client)

    def __getattr__(self, name: str) -> typing.Any:
        return getattr(object.__getattribute__(self, "_msg"), name)

    def __setattr__(self, name: str, value: typing.Any) -> None:
        if name in ("_msg", "_client"):
            object.__setattr__(self, name, value)
        else:
            setattr(object.__getattribute__(self, "_msg"), name, value)

    async def edit(self, text: str, **kwargs) -> typing.Any:
        client = object.__getattribute__(self, "_client")
        msg    = object.__getattribute__(self, "_msg")
        return await client.send_message(msg.chat_id, text, **kwargs)

    async def respond(self, text: str, **kwargs) -> typing.Any:
        client = object.__getattribute__(self, "_client")
        msg    = object.__getattribute__(self, "_msg")
        return await client.send_message(msg.chat_id, text, **kwargs)

    async def reply(self, text: str, **kwargs) -> typing.Any:
        client = object.__getattribute__(self, "_client")
        msg    = object.__getattribute__(self, "_msg")
        return await client.send_message(
            msg.chat_id, text,
            reply_to=msg.id,
            **kwargs,
        )

    async def delete(self) -> None:
        # Не удаляем сообщение co-owner — просто игнорируем
        pass


class CommandDispatcher:

    def __init__(
        self,
        client: typing.Any,
        db: typing.Any,
        security: SecurityManager,
        prefix: str = ".",
    ) -> None:
        self._client   = client
        self._db       = db
        self._security = security
        self._prefix   = prefix
        self._limiter  = RateLimiter()
        self._loader: typing.Any = None

        self._commands: dict[str, tuple[typing.Callable, int]] = {}
        self._watchers: list[tuple[typing.Callable | None, typing.Callable]] = []

        self._client.add_event_handler(self._on_out_message,  events.NewMessage(outgoing=True))
        self._client.add_event_handler(self._on_in_message,   events.NewMessage(incoming=True))

    def register_command(self, name: str, handler: typing.Callable, required: int = OWNER) -> None:
        self._commands[name.lower()] = (handler, required)
        logger.debug("Dispatcher: registered command .%s (required=%d)", name, required)

    def unregister_command(self, name: str) -> None:
        self._commands.pop(name.lower(), None)

    def register_watcher(self, handler: typing.Callable, filter_func: typing.Callable | None = None) -> None:
        self._watchers.append((filter_func, handler))

    def unregister_watchers_for(self, module: typing.Any) -> None:
        self._watchers = [
            (f, h) for f, h in self._watchers
            if getattr(h, "__self__", None) is not module
        ]

    def set_prefix(self, prefix: str) -> None:
        self._prefix = prefix
        logger.info("Dispatcher: prefix changed to %r", prefix)

    def set_owner(self, owner_id: int) -> None:
        self._limiter.set_owner(owner_id)
        self._limiter.start_cleanup()

    async def _on_out_message(self, event: events.NewMessage.Event) -> None:
        await self._handle_message(event, is_own=True, is_co_owner=False)

    async def _on_in_message(self, event: events.NewMessage.Event) -> None:
        message = event.message
        if not message or not message.text:
            return
        sender_id = message.sender_id
        if not sender_id or sender_id == self._client.tg_id:
            return

        # ── Перехват ввода для inline-конфига ──────────────────────────────────
        # Когда пользователь вводит значение через бота (pending_input),
        # перехватываем сообщение здесь через Telethon, пока entities доступны,
        # и сохраняем HTML с форматированием (цитаты, жирный, прем-эмодзи).
        pending = self._db.get("kitsune.config", "pending_input", None)
        if pending:
            owner_id = self._db.get("kitsune.notifier", "owner_id", None)
            if sender_id == owner_id:
                try:
                    from telethon.extensions import html as tl_html
                    import copy
                    raw_text = message.raw_text or message.text or ""
                    entities = list(message.entities or [])
                    # Сериализуем в HTML сохраняя всё форматирование
                    html_value = tl_html.unparse(raw_text, entities) if entities else raw_text

                    mod_name = pending["mod"]
                    key = pending["key"]
                    await self._db.delete("kitsune.config", "pending_input")

                    loader = getattr(self._client, "_kitsune_loader", None)
                    if loader:
                        mod = loader.modules.get(mod_name)
                        if mod and key in mod.config:
                            orig = mod.config.get_default(key)
                            value = html_value
                            try:
                                if isinstance(orig, int):
                                    value = int(raw_text)
                                elif isinstance(orig, float):
                                    value = float(raw_text)
                            except (ValueError, TypeError):
                                pass
                            mod.config[key] = value
                            await self._db.set(
                                f"kitsune.config.{mod_name}", "values",
                                {k: mod.config[k] for k in mod.config.keys()}
                            )
                            try:
                                await self._db.force_save()
                            except Exception:
                                pass
                            # Обновляем сообщение бота с подтверждением
                            inline = getattr(self._client, "_kitsune_inline", None)
                            if inline and inline._bot:
                                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                                try:
                                    await inline._bot.edit_message_text(
                                        chat_id=pending["chat_id"],
                                        message_id=pending["msg_id"],
                                        text=f"✅ <b>{mod.name}</b> → <code>{key}</code> = <b>{value}</b>",
                                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                            InlineKeyboardButton(text="◀️ Назад", callback_data=f"cfg_mod:{mod_name}")
                                        ]]),
                                        parse_mode="HTML",
                                    )
                                except Exception:
                                    pass
                            try:
                                await message.delete()
                            except Exception:
                                pass
                            return  # Не передаём дальше в bot_runner
                except Exception:
                    pass  # При ошибке — bot_runner обработает как обычно
        # ── Конец перехвата ────────────────────────────────────────────────────

        sec = self._security
        sudo_users = sec.get_sudo_users() if sec else []
        co_owners  = self._db.get("kitsune.security", "co_owners", [])
        if sender_id not in sudo_users and sender_id not in co_owners:
            return
        is_co_owner = sender_id in co_owners
        await self._handle_message(event, is_own=False, is_co_owner=is_co_owner)

    async def _handle_message(self, event: events.NewMessage.Event, *, is_own: bool, is_co_owner: bool = False) -> None:
        message = event.message
        if not message or not message.text:
            return

        text: str = (message.raw_text or message.text or "").strip()

        if text.startswith(self._prefix):
            if (
                is_own
                and len(text) > len(self._prefix) * 2
                and text.startswith(self._prefix * 2)
                and any(s != self._prefix for s in text)
            ):
                try:
                    await message.edit(text[len(self._prefix):])
                except Exception:
                    pass
                return

            raw = text[len(self._prefix):]
            parts = raw.split(maxsplit=1)
            if not parts:
                return

            cmd_name = parts[0].lower().split("@")[0]
            entry = self._commands.get(cmd_name)
            if entry is None:
                return

            handler, required = entry

            # Co-owner выполняет команду от лица основного аккаунта.
            # Редактировать его сообщение нельзя, поэтому оборачиваем message
            # в прокси: edit()/respond() → send_message от нашего клиента.
            if is_co_owner:
                message._sender_id = self._client.tg_id
                message._client = self._client
                event._client = self._client
                event.message = _CoOwnerMessageProxy(message, self._client)
                is_own = True
                is_co_owner = False

            # Sudo-пользователи (не co-owner) не могут выполнять OWNER-команды
            if not is_own and not is_co_owner and required >= OWNER:
                return

            sender_id = message.sender_id or 0

            if not await self._limiter.check(sender_id, cmd_name):
                if is_own:
                    try:
                        await message.respond(_FLOOD_REPLY, parse_mode="html")
                    except Exception:
                        pass
                return

            try:
                allowed = await self._security.check(message, required)
            except Exception:
                logger.exception("Dispatcher: security check failed for .%s", cmd_name)
                return

            if not allowed:
                return

            asyncio.ensure_future(self._safe_call(handler, event, cmd_name))
            return

        if is_own:
            for filter_func, handler in list(self._watchers):
                try:
                    if filter_func is not None and not filter_func(message):
                        continue
                except Exception:
                    continue

                if _should_skip_watcher(handler, message):
                    continue

                asyncio.ensure_future(
                    self._safe_call(handler, event, f"watcher:{handler.__name__}")
                )

    async def _safe_call(self, handler: typing.Callable, event: typing.Any, label: str) -> None:
        try:
            await handler(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Dispatcher: unhandled exception in %s", label)
