from __future__ import annotations
import logging
from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from .._internal import get_platform

logger = logging.getLogger(__name__)

_LS_OWNER = "kitsune.quickstart"

_LS_KEY   = "shown"

_LS_LEGACY_CHECK_KEY = "legacy_folder_check_done"

_KITSUNE_CHATS = [

    {"key": "logs",   "title": "Kitsune-logs",  "type": "channel", "about": "Логи Kitsune Userbot"},

    {"key": "backup", "title": "KitsuneBackup",  "type": "group",   "about": "Резервные копии Kitsune Userbot"},

    {"key": "assets", "title": "kitsune-assets", "type": "channel", "about": "Медиа и ресурсы Kitsune"},

]

def _make_filter_title(text: str):

    try:

        from telethon.tl.types import TextWithEntities

        return TextWithEntities(text=text, entities=[])

    except ImportError:

        return text

def _peer_id(peer) -> int | None:

    return (

        getattr(peer, "channel_id", None)

        or getattr(peer, "chat_id", None)

        or getattr(peer, "user_id", None)

    )

class QuickstartModule(KitsuneModule):

    name        = "quickstart"

    description = "Онбординг при первой установке"

    author      = "Kitsune Team"

    version     = "1.3.0"

    icon        = "🎉"

    category    = "system"

    strings_ru = {

        "already_shown": "✅ Онбординг уже был показан.",

        "reset_done":    "♻️ Флаг онбординга сброшен. Перезапусти Kitsune.",

    }

    async def on_load(self) -> None:

        await self._maybe_show_welcome()

    async def _sync_kitsune_folder(self) -> dict:

        import asyncio as _asyncio
        from telethon.tl.functions.messages import (

            GetDialogFiltersRequest,

            UpdateDialogFilterRequest,

        )

        from telethon.tl.types import DialogFilter, InputPeerSelf
        from telethon.errors import FloodWaitError

        _CACHE_KEY = "kitsune.quickstart"

        cached_ids: dict = self.db.get(_CACHE_KEY, "chat_ids", {}) or {}

        result_entities: dict = {}

        stale_keys = []

        for cfg in _KITSUNE_CHATS:

            cached_id = cached_ids.get(cfg["key"])

            entity = None

            if cached_id:

                try:

                    entity = await asyncio.wait_for(

                        self.client.get_entity(int(cached_id)), timeout=10

                    )

                    logger.info("Quickstart: «%s» найден по кэшу", cfg["title"])

                except Exception:

                    logger.info("Quickstart: кэш для «%s» устарел — ищу в диалогах", cfg["title"])

                    stale_keys.append(cfg["key"])

                    entity = None

            if entity is None:

                if not hasattr(self, "_dialogs_cache"):

                    self._dialogs_cache = []

                    for _attempt in range(3):

                        try:

                            async for d in self.client.iter_dialogs():

                                self._dialogs_cache.append(d)

                            break

                        except FloodWaitError as _e:

                            logger.warning("Quickstart: FloodWait %ds (попытка %d/3)", _e.seconds, _attempt + 1)

                            await _asyncio.sleep(_e.seconds + 1)

                            self._dialogs_cache.clear()

                entity = self._find_in_dialogs(self._dialogs_cache, cfg["title"], cfg["type"])

                if entity is None:

                    logger.info("Quickstart: «%s» не найден — создаю...", cfg["title"])

                    entity = await self._create_chat(cfg)

                else:

                    logger.info("Quickstart: «%s» уже существует", cfg["title"])

            result_entities[cfg["key"]] = entity

            if entity is not None:

                eid = getattr(entity, "id", None)

                if eid:

                    cached_ids[cfg["key"]] = eid

        await self.db.set(_CACHE_KEY, "chat_ids", cached_ids)

        if hasattr(self, "_dialogs_cache"):

            del self._dialogs_cache

        all_input_peers = []

        for entity in result_entities.values():

            if entity is None:

                continue

            try:

                peer = await self.client.get_input_entity(entity)

                all_input_peers.append(peer)

            except Exception:

                logger.exception("Quickstart: не удалось получить input_entity")

        try:

            bot_username = self.db.get("kitsune.notifier", "bot_username", None)

            inline = getattr(self.client, "_kitsune_inline", None)

            if not bot_username and inline:

                bot_username = getattr(inline, "_bot_username", None)

            if bot_username:

                bot_entity = await self.client.get_entity(f"@{bot_username.lstrip('@')}")

                bot_peer = await self.client.get_input_entity(bot_entity)

                all_input_peers.append(bot_peer)

                logger.info("Quickstart: inline-бот @%s добавлен в папку Kitsune", bot_username)

        except Exception:

            logger.debug("Quickstart: inline-бот пока недоступен — добавлю позже", exc_info=True)

        all_input_peers.append(InputPeerSelf())

        try:

            filters_result = await self.client(GetDialogFiltersRequest())

            all_filters = getattr(filters_result, "filters", filters_result)

            existing_folder: DialogFilter | None = next(

                (f for f in all_filters

                 if isinstance(f, DialogFilter) and _filter_title_str(f) == "Kitsune"),

                None,

            )

            if existing_folder is None:

                logger.info("Quickstart: папка «Kitsune» не найдена — создаю...")

                used_ids = {f.id for f in all_filters if hasattr(f, "id")}

                folder_id = next(i for i in range(2, 256) if i not in used_ids)

                folder = DialogFilter(

                    id=folder_id,

                    title=_make_filter_title("Kitsune"),

                    pinned_peers=[],

                    include_peers=all_input_peers,

                    exclude_peers=[],

                    contacts=False,

                    non_contacts=False,

                    groups=False,

                    broadcasts=False,

                    bots=False,

                    exclude_muted=False,

                    exclude_read=False,

                    exclude_archived=False,

                    emoticon="🦊",

                )

                verb = "создана"

            else:

                logger.info("Quickstart: папка «Kitsune» найдена — синхронизирую...")

                folder = existing_folder

                already = {_peer_id(p) for p in folder.include_peers}

                already.discard(None)

                added = 0

                for p in all_input_peers:

                    cid = _peer_id(p)

                    if cid not in already:

                        folder.include_peers.append(p)

                        already.add(cid)

                        added += 1

                folder.title = _make_filter_title("Kitsune")

                logger.info("Quickstart: добавлено %d новых чатов в папку", added)

                verb = "обновлена"

            await self.client(UpdateDialogFilterRequest(id=folder.id, filter=folder))

            logger.info("Quickstart: папка «Kitsune» %s (id=%s)", verb, folder.id)

        except Exception:

            logger.exception("Quickstart: не удалось синхронизировать папку «Kitsune»")

        return result_entities

    @staticmethod

    def _find_in_dialogs(dialogs, title: str, chat_type: str):

        for d in dialogs:

            if d.title != title:

                continue

            if chat_type == "channel" and d.is_channel and not d.is_group:

                return d.entity

            if chat_type == "group" and (d.is_group or d.is_channel):

                return d.entity

        return None

    async def _create_chat(self, cfg: dict):

        import asyncio as _asyncio
        from telethon.tl.functions.channels import CreateChannelRequest
        from telethon.errors import FloodWaitError

        for attempt in range(3):

            try:

                result = await self.client(CreateChannelRequest(

                    title=cfg["title"],

                    about=cfg["about"],

                    broadcast=(cfg["type"] == "channel"),

                    megagroup=(cfg["type"] == "group"),

                ))

                logger.info("Quickstart: создан «%s» (%s)", cfg["title"], cfg["type"])

                return result.chats[0]

            except FloodWaitError as e:

                logger.warning(

                    "Quickstart: FloodWait при создании «%s» — ждём %ds (попытка %d/3)",

                    cfg["title"], e.seconds, attempt + 1,

                )

                await _asyncio.sleep(e.seconds + 1)

        raise RuntimeError(

            f"Не удалось создать «{cfg['title']}» после 3 попыток (FloodWait)"

        )

    async def _maybe_show_welcome(self) -> None:

        try:

            from .._local_storage import get_storage

            ls = get_storage()

            import asyncio

            await asyncio.sleep(3)

            if not ls.get(_LS_OWNER, _LS_KEY):

                await self._sync_kitsune_folder()

                ls.set(_LS_OWNER, _LS_KEY, True)

                logger.info("Quickstart: папка Kitsune и чаты синхронизированы (приветствие отправляется ботом в DM)")

            if not ls.get(_LS_OWNER, _LS_LEGACY_CHECK_KEY):

                try:

                    await self._legacy_one_time_check()

                except Exception:

                    logger.exception("Quickstart: одноразовая проверка для старых пользователей провалилась")

                else:

                    ls.set(_LS_OWNER, _LS_LEGACY_CHECK_KEY, True)

                    logger.info(
                        "Quickstart: одноразовая проверка папки Kitsune завершена — "
                        "флаг сохранён, повторно запускаться не будет"
                    )

        except Exception:

            logger.exception("Quickstart: ошибка синхронизации папки")

    async def _legacy_one_time_check(self) -> None:
        from telethon.tl.functions.messages import (
            GetDialogFiltersRequest,
            UpdateDialogFilterRequest,
        )
        from telethon.tl.types import DialogFilter, InputPeerSelf

        logger.info("Quickstart: запускаю одноразовую проверку папки Kitsune (legacy users)")

        chats = await self._sync_kitsune_folder()
        for cfg in _KITSUNE_CHATS:
            entity = chats.get(cfg["key"])
            if entity is None:
                logger.warning(
                    "Quickstart[legacy]: не удалось получить «%s» — пропускаю в этой проверке",
                    cfg["title"],
                )

        bot_username = None
        try:
            bot_username = self.db.get("kitsune.notifier", "bot_username", None)
        except Exception:
            bot_username = None
        inline = getattr(self.client, "_kitsune_inline", None)
        if not bot_username and inline:
            bot_username = getattr(inline, "_bot_username", None)

        if bot_username:
            try:
                bot_entity = await self.client.get_entity(f"@{bot_username.lstrip('@')}")
                bot_input_peer = await self.client.get_input_entity(bot_entity)
                filters_result = await self.client(GetDialogFiltersRequest())
                all_filters = getattr(filters_result, "filters", filters_result)
                folder = next(
                    (f for f in all_filters
                     if isinstance(f, DialogFilter) and _filter_title_str(f) == "Kitsune"),
                    None,
                )
                if folder is not None:
                    bot_id = getattr(bot_entity, "id", None)
                    already = {_peer_id(p) for p in folder.include_peers}
                    if bot_id and bot_id not in already:
                        folder.include_peers.append(bot_input_peer)
                        await self.client(UpdateDialogFilterRequest(id=folder.id, filter=folder))
                        logger.info(
                            "Quickstart[legacy]: inline-бот @%s добавлен в папку Kitsune",
                            bot_username,
                        )
                    else:
                        logger.info(
                            "Quickstart[legacy]: inline-бот @%s уже в папке Kitsune",
                            bot_username,
                        )
            except Exception:
                logger.exception(
                    "Quickstart[legacy]: не удалось добавить inline-бота в папку Kitsune"
                )
        else:
            logger.info(
                "Quickstart[legacy]: bot_username ещё не известен — "
                "inline-бот не добавлен (флаг всё равно сохраняется, "
                "проверка одноразовая)"
            )

    @command("quickstart", required=OWNER)

    async def quickstart_cmd(self, event) -> None:

        """quickstart — запустить мастер первичной настройки UserBot."""

        args = self.get_args(event).strip().lower()

        if args == "reset":

            try:

                from .._local_storage import get_storage

                get_storage().delete(_LS_OWNER, _LS_KEY)

                await event.reply(self.strings("reset_done"), parse_mode="html")

            except Exception as exc:

                await event.reply(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")

            return

        if args == "folder":

            msg = await event.reply("⏳ Синхронизирую папку «Kitsune»…", parse_mode="html")

            try:

                chats = await self._sync_kitsune_folder()

                lines = []

                for cfg in _KITSUNE_CHATS:

                    e = chats.get(cfg["key"])

                    status = "✅" if e is not None else "❌"

                    lines.append(f"{status} <code>{cfg['title']}</code>")

                report = "\n".join(lines)

                await msg.edit(

                    f"🦊 <b>Папка Kitsune синхронизирована!</b>\n\n{report}",

                    parse_mode="html",

                )

            except Exception as exc:

                await msg.edit(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")

            return

        try:

            from .._local_storage import get_storage

            ls = get_storage()

            if ls.get(_LS_OWNER, _LS_KEY) and not args:

                await event.reply(self.strings("already_shown"), parse_mode="html")

                return

            chats = await self._sync_kitsune_folder()

            lines = []

            for cfg in _KITSUNE_CHATS:

                e = chats.get(cfg["key"])

                status = "✅" if e is not None else "❌"

                lines.append(f"{status} <code>{cfg['title']}</code>")

            report = "\n".join(lines)

            await event.reply(

                f"🦊 <b>Папка Kitsune синхронизирована!</b>\n\n{report}",

                parse_mode="html",

            )

            ls.set(_LS_OWNER, _LS_KEY, True)

        except Exception as exc:

            await event.reply(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")

def _filter_title_str(f) -> str:

    t = getattr(f, "title", "")

    if isinstance(t, str):

        return t

    return getattr(t, "text", str(t))
