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

ALL_TAGS = (
    "no_commands", "only_commands", "out", "in_", "only_messages", "editable",
    "no_media", "only_media", "only_photos", "only_videos", "only_audios",
    "only_docs", "only_stickers", "only_inline", "only_channels", "only_groups",
    "only_pm", "no_pm", "no_channels", "no_groups", "no_inline", "no_stickers",
    "no_docs", "no_audios", "no_videos", "no_photos", "no_forwards", "no_reply",
    "no_mention", "mention", "only_reply", "only_forwards",
    "startswith", "endswith", "contains", "regex", "filter", "from_id", "chat_id",
)

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
def _tag_check_out(func, m):           return bool(getattr(m, "out", True))

def _tag_check_in(func, m):            return not getattr(m, "out", True)

def _tag_check_only_messages(func, m): return isinstance(m, Message)

def _tag_check_editable(func, m):
    return (
        not getattr(m, "out", False) and not getattr(m, "fwd_from", False)
        and not getattr(m, "sticker", False) and not getattr(m, "via_bot_id", False)
    )
def _tag_check_no_media(func, m):      return not isinstance(m, Message) or not getattr(m, "media", False)

def _tag_check_only_media(func, m):    return isinstance(m, Message) and bool(getattr(m, "media", False))

def _tag_check_only_photos(func, m):   return _mime_type(m).startswith("image/")

def _tag_check_only_videos(func, m):   return _mime_type(m).startswith("video/")

def _tag_check_only_audios(func, m):   return _mime_type(m).startswith("audio/")

def _tag_check_only_stickers(func, m): return bool(getattr(m, "sticker", False))

def _tag_check_only_docs(func, m):     return bool(getattr(m, "document", False))

def _tag_check_only_inline(func, m):   return bool(getattr(m, "via_bot_id", False))

def _tag_check_only_channels(func, m):
    return bool(getattr(m, "is_channel", False)) and not getattr(m, "is_group", False)
def _tag_check_only_groups(func, m):
    return bool(getattr(m, "is_group", False)) or (
        not getattr(m, "is_private", False) and not getattr(m, "is_channel", False)
    )
def _tag_check_only_pm(func, m):       return bool(getattr(m, "is_private", False))

def _tag_check_no_pm(func, m):         return not getattr(m, "is_private", False)

def _tag_check_no_channels(func, m):   return not getattr(m, "is_channel", False)

def _tag_check_no_groups(func, m):
    return not getattr(m, "is_group", False) or bool(getattr(m, "is_private", False))
def _tag_check_no_inline(func, m):     return not getattr(m, "via_bot_id", False)

def _tag_check_no_stickers(func, m):   return not getattr(m, "sticker", False)

def _tag_check_no_docs(func, m):       return not getattr(m, "document", False)

def _tag_check_no_audios(func, m):     return not _mime_type(m).startswith("audio/")

def _tag_check_no_videos(func, m):     return not _mime_type(m).startswith("video/")

def _tag_check_no_photos(func, m):     return not _mime_type(m).startswith("image/")

def _tag_check_no_forwards(func, m):   return not getattr(m, "fwd_from", False)

def _tag_check_no_reply(func, m):      return not getattr(m, "reply_to_msg_id", False)

def _tag_check_only_reply(func, m):    return bool(getattr(m, "reply_to_msg_id", False))

def _tag_check_only_forwards(func, m): return bool(getattr(m, "fwd_from", False))

def _tag_check_mention(func, m):       return bool(getattr(m, "mentioned", False))

def _tag_check_no_mention(func, m):    return not getattr(m, "mentioned", False)

def _tag_check_startswith(func, m):
    return isinstance(m, Message) and (m.raw_text or "").startswith(getattr(func, "startswith", ""))
def _tag_check_endswith(func, m):
    return isinstance(m, Message) and (m.raw_text or "").endswith(getattr(func, "endswith", ""))
def _tag_check_contains(func, m):
    return isinstance(m, Message) and getattr(func, "contains", "") in (m.raw_text or "")
def _tag_check_filter(func, m):
    f = getattr(func, "filter", None)
    return callable(f) and f(m)
def _tag_check_from_id(func, m):
    return getattr(m, "sender_id", None) == getattr(func, "from_id", None)
def _tag_check_chat_id(func, m):
    return _get_chat_id(m) == getattr(func, "chat_id", None)
def _tag_check_regex(func, m):
    return isinstance(m, Message) and bool(re.search(getattr(func, "regex", ""), m.raw_text or ""))
_TAG_CHECKS: dict[str, typing.Callable] = {
    "out": _tag_check_out,
    "in_": _tag_check_in,
    "only_messages": _tag_check_only_messages,
    "editable": _tag_check_editable,
    "no_media": _tag_check_no_media,
    "only_media": _tag_check_only_media,
    "only_photos": _tag_check_only_photos,
    "only_videos": _tag_check_only_videos,
    "only_audios": _tag_check_only_audios,
    "only_stickers": _tag_check_only_stickers,
    "only_docs": _tag_check_only_docs,
    "only_inline": _tag_check_only_inline,
    "only_channels": _tag_check_only_channels,
    "only_groups": _tag_check_only_groups,
    "only_pm": _tag_check_only_pm,
    "no_pm": _tag_check_no_pm,
    "no_channels": _tag_check_no_channels,
    "no_groups": _tag_check_no_groups,
    "no_inline": _tag_check_no_inline,
    "no_stickers": _tag_check_no_stickers,
    "no_docs": _tag_check_no_docs,
    "no_audios": _tag_check_no_audios,
    "no_videos": _tag_check_no_videos,
    "no_photos": _tag_check_no_photos,
    "no_forwards": _tag_check_no_forwards,
    "no_reply": _tag_check_no_reply,
    "only_reply": _tag_check_only_reply,
    "only_forwards": _tag_check_only_forwards,
    "mention": _tag_check_mention,
    "no_mention": _tag_check_no_mention,
    "startswith": _tag_check_startswith,
    "endswith": _tag_check_endswith,
    "contains": _tag_check_contains,
    "filter": _tag_check_filter,
    "from_id": _tag_check_from_id,
    "chat_id": _tag_check_chat_id,
    "regex": _tag_check_regex,
}

def _collect_active_tags(handler: typing.Callable) -> tuple[str, ...]:
    return tuple(t for t in ALL_TAGS if getattr(handler, t, False) and t in _TAG_CHECKS)
def _should_skip_watcher(handler: typing.Callable, active_tags: tuple[str, ...], message: Message) -> bool:
    for tag in active_tags:
        check = _TAG_CHECKS[tag]
        try:
            if not check(handler, message):
                return True
        except Exception:
            return True
    return False
class _CoOwnerMessageProxy:
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
        self._commands: dict[str, tuple[typing.Callable, typing.Any, typing.Any]] = {}
        self._watchers: list[tuple[typing.Callable | None, typing.Callable, tuple[str, ...]]] = []
        self._pending_input: dict | None = None
        self._co_owners_cache: list[int] = []
        self._co_owners_dirty: bool = True
        self._client.add_event_handler(self._on_out_message,  events.NewMessage(outgoing=True))
        self._client.add_event_handler(self._on_in_message,   events.NewMessage(incoming=True))
    def register_command(
        self,
        name: str,
        handler: typing.Callable,
        required: "int | str" = OWNER,
        *,
        module: typing.Any = None,
    ) -> None:
        if module is None:
            module = getattr(handler, "__self__", None)
        self._commands[name.lower()] = (handler, required, module)
        if isinstance(required, str):
            logger.debug(
                "Dispatcher: registered command .%s (role=%r, module=%s)",
                name, required,
                getattr(module, "name", type(module).__name__ if module else "?"),
            )
        else:
            logger.debug("Dispatcher: registered command .%s (required=%d)", name, int(required or 0))
    def unregister_command(self, name: str) -> None:
        self._commands.pop(name.lower(), None)
    def _resolve_role_db_owner(self, module: typing.Any) -> str:
        if module is None:
            return ""
        custom = getattr(module, "role_db_owner", None)
        if isinstance(custom, str) and custom.strip():
            return custom.strip()
        name = getattr(module, "name", None) or type(module).__name__
        return str(name)
    def _get_role_users(self, module: typing.Any, role_name: str) -> list[int]:
        owner = self._resolve_role_db_owner(module)
        if not owner or not role_name:
            return []
        raw = self._db.get(owner, f"{role_name}_users", []) or []
        if not isinstance(raw, (list, tuple, set)):
            return []
        users: list[int] = []
        for item in raw:
            try:
                users.append(int(item))
            except (TypeError, ValueError):
                continue
        return users
    def _check_role(self, module: typing.Any, role_name: str, sender_id: int) -> bool:
        if not sender_id:
            return False
        own_id = getattr(self._client, "tg_id", None)
        if own_id and sender_id == own_id:
            return True
        if sender_id in self._get_co_owners():
            return True
        return sender_id in self._get_role_users(module, role_name)
    def register_watcher(self, handler: typing.Callable, filter_func: typing.Callable | None = None) -> None:
        active_tags = _collect_active_tags(handler)
        self._watchers.append((filter_func, handler, active_tags))
    def unregister_watchers_for(self, module: typing.Any) -> None:
        self._watchers = [
            (f, h, t) for f, h, t in self._watchers
            if getattr(h, "__self__", None) is not module
        ]
    def set_prefix(self, prefix: str) -> None:
        self._prefix = prefix
        logger.info("Dispatcher: prefix changed to %r", prefix)
    def set_owner(self, owner_id: int) -> None:
        self._limiter.set_owner(owner_id)
        self._limiter.start_cleanup()
    def set_pending_input(self, data: dict | None) -> None:
        self._pending_input = data
    def get_pending_input(self) -> dict | None:
        return self._pending_input
    def invalidate_co_owners(self) -> None:
        self._co_owners_dirty = True
    def _get_co_owners(self) -> list[int]:
        if self._co_owners_dirty:
            self._co_owners_cache = self._db.get("kitsune.security", "co_owners", []) or []
            self._co_owners_dirty = False
        return self._co_owners_cache
    async def _on_out_message(self, event: events.NewMessage.Event) -> None:
        await self._handle_message(event, is_own=True, is_co_owner=False)
    async def _on_in_message(self, event: events.NewMessage.Event) -> None:
        message = event.message
        if not message or not message.text:
            return
        sender_id = message.sender_id
        own_id = getattr(self._client, "tg_id", 0) or 0
        if not sender_id or sender_id == own_id:
            return
        pending = self._pending_input
        if pending is None:
            pending = self._db.get("kitsune.config", "pending_input", None)
            if pending:
                self._pending_input = pending
        if pending:
            owner_id = self._db.get("kitsune.notifier", "owner_id", None)
            if sender_id == owner_id:
                try:
                    from telethon.extensions import html as tl_html
                    raw_text = message.raw_text or message.text or ""
                    entities = list(message.entities or [])
                    html_value = tl_html.unparse(raw_text, entities) if entities else raw_text
                    mod_name = pending["mod"]
                    key = pending["key"]
                    self._pending_input = None
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
                                logger.warning("Dispatcher: force_save after config update failed")
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
                                except Exception as _ie:
                                    logger.debug("Dispatcher: inline edit after cfg update failed: %s", _ie)
                            try:
                                await message.delete()
                            except Exception:
                                pass
                            return
                except Exception:
                    logger.warning("Dispatcher: config-edit handler failed", exc_info=True)
        sec = self._security
        sudo_users = sec.get_sudo_users() if sec else []
        co_owners  = self._get_co_owners()
        is_co_owner = sender_id in co_owners
        text = (message.raw_text or message.text or "").strip()
        if text.startswith(self._prefix):
            raw = text[len(self._prefix):].lstrip()
            parts = raw.split(maxsplit=1)
            if parts:
                cmd_name = parts[0].lower().split("@")[0]
                entry = self._commands.get(cmd_name)
                if entry is not None:
                    handler, _required, _module = entry
                    if getattr(handler, "_incoming", False):
                        await self._handle_message(
                            event, is_own=False, is_co_owner=is_co_owner, is_incoming=True,
                        )
                        return
        if sender_id not in sudo_users and not is_co_owner:
            # Обычное входящее сообщение (ответ бота, чужое сообщение и т.п.).
            # Командой оно не является (иначе ушло бы выше), поэтому отдаём его
            # watcher'ам напрямую — раньше такие сообщения просто терялись и
            # watcher'ы модулей (например, Iris) их не видели.
            self._dispatch_watchers(event, message)
            return
        await self._handle_message(event, is_own=False, is_co_owner=is_co_owner)
    async def _handle_message(self, event: events.NewMessage.Event, *, is_own: bool, is_co_owner: bool = False, is_incoming: bool = False) -> None:
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
            raw = text[len(self._prefix):].lstrip()
            parts = raw.split(maxsplit=1)
            if not parts:
                return
            cmd_name = parts[0].lower().split("@")[0]
            entry = self._commands.get(cmd_name)
            if entry is None:
                return
            handler, required, module = entry
            if is_co_owner:
                message._sender_id = self._client.tg_id
                message._client = self._client
                event._client = self._client
                event.message = _CoOwnerMessageProxy(message, self._client)
                is_own = True
                is_co_owner = False
            is_str_role = isinstance(required, str)
            if (
                not is_incoming
                and not is_own
                and not is_co_owner
                and not is_str_role
                and isinstance(required, int)
                and required >= OWNER
            ):
                return
            sender_id = message.sender_id or 0
            if not await self._limiter.check(sender_id, cmd_name):
                if is_own:
                    try:
                        await message.respond(_FLOOD_REPLY, parse_mode="html")
                    except Exception:
                        pass
                return
            if is_str_role:
                try:
                    if is_own:
                        allowed = True
                    else:
                        allowed = self._check_role(module, required, sender_id)
                except Exception:
                    logger.exception(
                        "Dispatcher: role check failed for .%s (role=%r)",
                        cmd_name, required,
                    )
                    return
            else:
                try:
                    allowed = await self._security.check(message, required)
                except Exception:
                    logger.exception("Dispatcher: security check failed for .%s", cmd_name)
                    return
            if not allowed:
                return
            asyncio.ensure_future(self._safe_call(handler, event, cmd_name))
            return
        # Сообщение не является командой -> отдаём его watcher'ам.
        # Раньше этот блок выполнялся только при is_own (исходящие), из-за чего
        # watcher'ы НИКОГДА не получали входящие сообщения (ответы ботов, чужие
        # сообщения). Теперь watcher'ы вызываются для любых сообщений, а нужное
        # направление каждый watcher выбирает сам через теги out=/in_=.
        self._dispatch_watchers(event, message)
    def _dispatch_watchers(self, event: events.NewMessage.Event, message: Message) -> None:
        """Прогоняет все зарегистрированные watcher'ы по сообщению.

        Направление (исходящее/входящее) и прочие условия фильтруются самими
        watcher'ами через теги (out=, in_=, chat_id=, from_id= и т.д.).
        Watcher без тегов получает И исходящие, И входящие сообщения.
        """
        if not self._watchers:
            return
        for filter_func, handler, active_tags in self._watchers:
            try:
                if filter_func is not None and not filter_func(message):
                    continue
            except Exception:
                logger.debug(
                    "Dispatcher: watcher filter raised, skipping: %s",
                    handler.__name__, exc_info=True,
                )
                continue
            if active_tags and _should_skip_watcher(handler, active_tags, message):
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
