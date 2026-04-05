from __future__ import annotations

import logging
import re

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_NOTIFIER = "kitsune.notifier"


class InlineStuffModule(KitsuneModule):
    """Управление inline-ботом Kitsune."""

    name        = "InlineStuff"
    description = "Смена бота / токена для уведомлений"
    author      = "@Mikasu32"
    version     = "1.0"
    _builtin    = True

    strings_ru = {
        "token_invalid":   "❌ Неверный формат токена. Формат: <code>123456789:AAaabbcc...</code>",
        "token_saved":     "✅ Токен бота сохранён. Перезапусти Kitsune чтобы применить: <code>.restart</code>",
        "bot_updated":     "✅ Юзернейм бота обновлён. Перезапусти Kitsune: <code>.restart</code>",
        "bot_invalid":     "❌ Неверный юзернейм бота. Должен оканчиваться на <code>bot</code>.",
        "bot_occupied":    "❌ Этот юзернейм занят не ботом.",
        "no_args":         "❌ Укажи токен: <code>.ch_bot_token 123456:TOKEN</code>",
        "no_args_bot":     "❌ Укажи юзернейм: <code>.ch_kitsune_bot mybot_bot</code>",
        "current":         (
            "🤖 <b>Текущий inline-бот</b>\n\n"
            "Юзернейм: <code>@{username}</code>\n"
            "Токен: <code>{token}</code>\n\n"
            "Для смены: <code>.ch_bot_token TOKEN</code> или <code>.ch_kitsune_bot USERNAME</code>"
        ),
    }

    # ─── helpers ──────────────────────────────────────────────────────────

    def _get_notifier(self):
        loader = getattr(self.client, "_kitsune_loader", None)
        return loader.modules.get("notifier") if loader else None

    # ─── команды ──────────────────────────────────────────────────────────

    @command("ch_bot_token", required=OWNER)
    async def ch_bot_token_cmd(self, event) -> None:
        """.ch_bot_token <TOKEN> — установить токен inline-бота."""
        token = self.get_args(event).strip()
        if not token:
            await event.message.edit(self.strings("no_args"), parse_mode="html")
            return

        if not re.match(r"[0-9]{8,10}:[a-zA-Z0-9_-]{34,36}", token):
            await event.message.edit(self.strings("token_invalid"), parse_mode="html")
            return

        await self.db.set(_DB_NOTIFIER, "bot_token", token)
        await event.message.edit(self.strings("token_saved"), parse_mode="html")

    @command("ch_kitsune_bot", required=OWNER)
    async def ch_kitsune_bot_cmd(self, event) -> None:
        """.ch_kitsune_bot <@username> — установить юзернейм inline-бота."""
        username = self.get_args(event).strip().lstrip("@")
        if not username:
            await event.message.edit(self.strings("no_args_bot"), parse_mode="html")
            return

        if not username.lower().endswith("bot") or len(username) <= 4:
            await event.message.edit(self.strings("bot_invalid"), parse_mode="html")
            return

        # check if it's actually a bot
        try:
            entity = await self.client.get_entity(f"@{username}")
            if not getattr(entity, "bot", False):
                await event.message.edit(self.strings("bot_occupied"), parse_mode="html")
                return
        except Exception:
            pass  # not found = probably free

        await self.db.set(_DB_NOTIFIER, "custom_bot", username)
        # clear old token so it gets re-obtained
        await self.db.set(_DB_NOTIFIER, "bot_token", None)
        await event.message.edit(self.strings("bot_updated"), parse_mode="html")
