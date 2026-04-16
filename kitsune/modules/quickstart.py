from __future__ import annotations

import logging

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from .._internal import get_platform

logger = logging.getLogger(__name__)

_LS_OWNER = "kitsune.quickstart"
_LS_KEY   = "shown"

class QuickstartModule(KitsuneModule):
    name        = "quickstart"
    description = "Онбординг при первой установке"
    author      = "Kitsune Team"
    version     = "1.0"
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

    async def _maybe_show_welcome(self) -> None:
        try:
            from .._local_storage import get_storage
            ls = get_storage()
            if ls.get(_LS_OWNER, _LS_KEY):
                return

            import asyncio
            await asyncio.sleep(3)

            text = self.strings("welcome")
            plat = get_platform()
            text += f"\n\n{self.strings('platform_info').format(platform=plat)}"

            me = await self.client.get_me()
            group_title = f"Kitsune {me.first_name or ''}"
            if me.last_name:
                group_title += f" {me.last_name}"

            target = None
            async for dialog in self.client.iter_dialogs():
                if dialog.is_group and dialog.title == group_title:
                    target = dialog.entity
                    break

            if target is None:
                from telethon.tl.functions.messages import CreateChatRequest
                result = await self.client(CreateChatRequest(
                    users=[],
                    title=group_title,
                ))
                target = result.chats[0]

            await self.client.send_message(target, text, parse_mode="html")
            ls.set(_LS_OWNER, _LS_KEY, True)
            logger.info("Quickstart: приветствие отправлено")

        except Exception:
            logger.exception("Quickstart: ошибка отправки приветствия")

    @command("quickstart", required=OWNER)
    async def quickstart_cmd(self, event) -> None:
        args = self.get_args(event).strip().lower()

        if args == "reset":
            try:
                from .._local_storage import get_storage
                get_storage().delete(_LS_OWNER, _LS_KEY)
                await event.reply(self.strings("reset_done"), parse_mode="html")
            except Exception as exc:
                await event.reply(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")
            return

        try:
            from .._local_storage import get_storage
            ls = get_storage()
            if ls.get(_LS_OWNER, _LS_KEY) and not args:
                await event.reply(self.strings("already_shown"), parse_mode="html")
                return

            text = self.strings("welcome")
            plat = get_platform()
            text += f"\n\n{self.strings('platform_info').format(platform=plat)}"

            me = await self.client.get_me()
            group_title = f"Kitsune {me.first_name or ''}"
            if me.last_name:
                group_title += f" {me.last_name}"
            target = None
            async for dialog in self.client.iter_dialogs():
                if dialog.is_group and dialog.title == group_title:
                    target = dialog.entity
                    break
            if target is None:
                from telethon.tl.functions.messages import CreateChatRequest
                result = await self.client(CreateChatRequest(users=[], title=group_title))
                target = result.chats[0]
            await self.client.send_message(target, text, parse_mode="html")
            ls.set(_LS_OWNER, _LS_KEY, True)
        except Exception as exc:
            await event.reply(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")
