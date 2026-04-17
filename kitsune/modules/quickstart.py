from __future__ import annotations

import logging

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from .._internal import get_platform

logger = logging.getLogger(__name__)

_LS_OWNER = "kitsune.quickstart"
_LS_KEY   = "shown"

# Описание всех служебных чатов которые должны быть в папке
_KITSUNE_CHATS = [
    {"key": "logs",   "title": "Kitsune-logs",   "type": "channel", "about": "Логи Kitsune Userbot"},
    {"key": "backup", "title": "KitsuneBackup",   "type": "group",   "about": "Резервные копии Kitsune Userbot"},
    {"key": "assets", "title": "kitsune-assets",  "type": "channel", "about": "Медиа и ресурсы Kitsune"},
]


class QuickstartModule(KitsuneModule):
    name        = "quickstart"
    description = "Онбординг при первой установке"
    author      = "Kitsune Team"
    version     = "1.2"
    icon        = "🎉"
    category    = "system"

    strings_ru = {
        "welcome": (
            "🦊 <b>Добро пожаловать в Kitsune Userbot!</b>\n\n"
            "Kitsune успешно запущен и готов к работе.\n\n"
            "<b>Быстрый старт:</b>\n"
            "• <code>.help</code> — список всех команд\n"
            "• <code>.ping</code> — проверить работу\n"
            "• <code>.cfg</code> — настройка модулей\n"
            "• <code>.dlm &lt;url&gt;</code> — установить модуль\n\n"
            "<b>Безопасность:</b>\n"
            "• <code>.security</code> — управление доступом\n"
            "• <code>.backup</code> — резервная копия БД\n\n"
            "<b>Полезные ссылки:</b>\n"
            "• Репозиторий: github.com/youshi-dev/Kitsune\n"
            "• Разработчик: @Mikasu32\n\n"
            "🎉 <i>Приятного использования!</i>"
        ),
        "already_shown": "✅ Онбординг уже был показан.",
        "reset_done":    "♻️ Флаг онбординга сброшен. Перезапусти Kitsune.",
        "platform_info": "🖥 Платформа: <b>{platform}</b>",
    }

    async def on_load(self) -> None:
        await self._maybe_show_welcome()

    # ------------------------------------------------------------------
    # Core: sync folder
    # ------------------------------------------------------------------

    async def _sync_kitsune_folder(self) -> dict:
        """
        1. Сканирует существующую папку «Kitsune» (если есть).
        2. Проверяет наличие каждого служебного чата по названию среди диалогов.
        3. Если чата нет — создаёт его.
        4. Если чата нет в папке — добавляет в папку.
        5. Добавляет аккаунт самого бота в папку (если ещё не там).

        Возвращает dict {key: entity} для всех чатов.
        """
        from telethon.tl.functions.messages import (
            GetDialogFiltersRequest,
            UpdateDialogFilterRequest,
        )
        from telethon.tl.types import DialogFilter, InputPeerSelf

        # ── Шаг 1: загружаем все диалоги один раз ────────────────────
        all_dialogs = []
        async for d in self.client.iter_dialogs():
            all_dialogs.append(d)

        # ── Шаг 2: находим / создаём каждый чат ─────────────────────
        result_entities = {}
        for cfg in _KITSUNE_CHATS:
            entity = self._find_in_dialogs(all_dialogs, cfg["title"], cfg["type"])
            if entity is None:
                logger.info("Quickstart: «%s» не найден — создаю...", cfg["title"])
                entity = await self._create_chat(cfg)
            else:
                logger.info("Quickstart: «%s» уже существует", cfg["title"])
            result_entities[cfg["key"]] = entity

        # ── Шаг 3: собираем InputPeer для всех чатов ─────────────────
        all_input_peers = []
        for entity in result_entities.values():
            if entity is None:
                continue
            try:
                peer = await self.client.get_input_entity(entity)
                all_input_peers.append(peer)
            except Exception:
                logger.exception("Quickstart: не удалось получить input_entity")

        # Добавляем самого себя (бота)
        all_input_peers.append(InputPeerSelf())

        # ── Шаг 4: ищем папку «Kitsune» ─────────────────────────────
        try:
            filters_result = await self.client(GetDialogFiltersRequest())
            all_filters = getattr(filters_result, "filters", filters_result)

            existing_folder: DialogFilter | None = next(
                (f for f in all_filters
                 if isinstance(f, DialogFilter) and f.title == "Kitsune"),
                None,
            )

            if existing_folder is None:
                # Папки нет — создаём с нуля
                logger.info("Quickstart: папка «Kitsune» не найдена — создаю...")
                used_ids = {f.id for f in all_filters if hasattr(f, "id")}
                folder_id = next(i for i in range(2, 256) if i not in used_ids)
                folder = DialogFilter(
                    id=folder_id,
                    title="Kitsune",
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
                created = True
            else:
                # Папка есть — проверяем, каких пиров не хватает
                logger.info("Quickstart: папка «Kitsune» найдена — синхронизирую...")
                folder = existing_folder

                # Строим множество уже добавленных id
                already = set()
                for p in folder.include_peers:
                    already.add(getattr(p, "channel_id", None))
                    already.add(getattr(p, "chat_id", None))
                    already.add(getattr(p, "user_id", None))
                already.discard(None)

                added = 0
                for p in all_input_peers:
                    cid = (
                        getattr(p, "channel_id", None)
                        or getattr(p, "chat_id", None)
                        or getattr(p, "user_id", None)
                    )
                    if cid not in already:
                        folder.include_peers.append(p)
                        already.add(cid)
                        added += 1

                logger.info("Quickstart: добавлено %d новых чатов в папку", added)
                created = False

            await self.client(UpdateDialogFilterRequest(id=folder.id, filter=folder))
            logger.info(
                "Quickstart: папка «Kitsune» %s (id=%s)",
                "создана" if created else "обновлена",
                folder.id,
            )

        except Exception:
            logger.exception("Quickstart: не удалось синхронизировать папку «Kitsune»")

        return result_entities

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_in_dialogs(dialogs, title: str, chat_type: str):
        """Ищет диалог по названию и типу (channel / group)."""
        for d in dialogs:
            if d.title != title:
                continue
            if chat_type == "channel" and d.is_channel and not d.is_group:
                return d.entity
            if chat_type == "group" and d.is_group:
                return d.entity
        return None

    async def _create_chat(self, cfg: dict):
        """Создаёт канал или мегагруппу по описанию из _KITSUNE_CHATS."""
        from telethon.tl.functions.channels import CreateChannelRequest
        if cfg["type"] == "channel":
            result = await self.client(CreateChannelRequest(
                title=cfg["title"],
                about=cfg["about"],
                broadcast=True,
                megagroup=False,
            ))
        else:
            result = await self.client(CreateChannelRequest(
                title=cfg["title"],
                about=cfg["about"],
                broadcast=False,
                megagroup=True,
            ))
        logger.info("Quickstart: создан «%s» (%s)", cfg["title"], cfg["type"])
        return result.chats[0]

    # ------------------------------------------------------------------
    # Welcome flow
    # ------------------------------------------------------------------

    async def _maybe_show_welcome(self) -> None:
        try:
            from .._local_storage import get_storage
            ls = get_storage()
            if ls.get(_LS_OWNER, _LS_KEY):
                return

            import asyncio
            await asyncio.sleep(3)

            chats = await self._sync_kitsune_folder()

            text = self.strings("welcome")
            plat = get_platform()
            text += f"\n\n{self.strings('platform_info').format(platform=plat)}"

            # Отправляем приветствие в KitsuneBackup (основная группа)
            target = chats.get("backup")
            if target is None:
                # Фолбэк: личная группа с именем пользователя
                me = await self.client.get_me()
                group_title = f"Kitsune {me.first_name or ''}".strip()
                if me.last_name:
                    group_title += f" {me.last_name}"
                from telethon.tl.functions.messages import CreateChatRequest
                result = await self.client(CreateChatRequest(users=[], title=group_title))
                target = result.chats[0]

            await self.client.send_message(target, text, parse_mode="html")
            ls.set(_LS_OWNER, _LS_KEY, True)
            logger.info("Quickstart: приветствие отправлено")

        except Exception:
            logger.exception("Quickstart: ошибка отправки приветствия")

    # ------------------------------------------------------------------
    # Command
    # ------------------------------------------------------------------

    @command("quickstart", required=OWNER)
    async def quickstart_cmd(self, event) -> None:
        args = self.get_args(event).strip().lower()

        # .quickstart reset — сбрасывает флаг онбординга
        if args == "reset":
            try:
                from .._local_storage import get_storage
                get_storage().delete(_LS_OWNER, _LS_KEY)
                await event.reply(self.strings("reset_done"), parse_mode="html")
            except Exception as exc:
                await event.reply(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")
            return

        # .quickstart folder — вручную синхронизировать папку
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

        # .quickstart — показать онбординг снова
        try:
            from .._local_storage import get_storage
            ls = get_storage()
            if ls.get(_LS_OWNER, _LS_KEY) and not args:
                await event.reply(self.strings("already_shown"), parse_mode="html")
                return

            text = self.strings("welcome")
            plat = get_platform()
            text += f"\n\n{self.strings('platform_info').format(platform=plat)}"

            chats = await self._sync_kitsune_folder()
            target = chats.get("backup")

            if target is None:
                me = await self.client.get_me()
                group_title = f"Kitsune {me.first_name or ''}".strip()
                if me.last_name:
                    group_title += f" {me.last_name}"
                from telethon.tl.functions.messages import CreateChatRequest
                result = await self.client(CreateChatRequest(users=[], title=group_title))
                target = result.chats[0]

            await self.client.send_message(target, text, parse_mode="html")
            ls.set(_LS_OWNER, _LS_KEY, True)
        except Exception as exc:
            await event.reply(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")
