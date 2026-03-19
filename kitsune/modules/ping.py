"""
Kitsune built-in: Ping & Utils
Команды: .ping .id .me
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import time

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER


class PingModule(KitsuneModule):
    name        = "ping"
    description = "Пинг и базовая информация"
    author      = "Yushi"
    version     = "1.0"

    strings_ru = {
        "pong":    "🏓 <b>Понг!</b> <code>{ms:.0f} мс</code>",
        "me":      (
            "👤 <b>Профиль</b>\n\n"
            "  ID: <code>{id}</code>\n"
            "  Имя: {name}\n"
            "  Username: {username}\n"
            "  Phone: <code>{phone}</code>\n"
            "  Premium: {premium}"
        ),
        "id_msg":  "🆔 ID сообщения: <code>{mid}</code>\n👤 ID чата: <code>{cid}</code>",
        "id_reply": (
            "🆔 ID сообщения: <code>{mid}</code>\n"
            "↩️ ID ответа: <code>{rid}</code>\n"
            "👤 ID отправителя: <code>{sid}</code>"
        ),
    }

    @command("ping", required=OWNER)
    async def ping_cmd(self, event) -> None:
        """.ping — проверить задержку до Telegram"""
        start = time.perf_counter()
        msg = await event.reply("🏓", parse_mode="html")
        ms = (time.perf_counter() - start) * 1000
        await msg.edit(self.strings("pong").format(ms=ms), parse_mode="html")

    @command("me", required=OWNER)
    async def me_cmd(self, event) -> None:
        """.me — информация о своём аккаунте"""
        me = await self.client.get_me()
        name = me.first_name
        if me.last_name:
            name += f" {me.last_name}"
        await event.reply(
            self.strings("me").format(
                id=me.id,
                name=name,
                username=f"@{me.username}" if me.username else "—",
                phone=me.phone or "—",
                premium="✅" if getattr(me, "premium", False) else "❌",
            ),
            parse_mode="html",
        )

    @command("id", required=OWNER)
    async def id_cmd(self, event) -> None:
        """.id — ID текущего чата и сообщения (или ответа)"""
        reply = await event.message.get_reply_message()
        if reply:
            await event.reply(
                self.strings("id_reply").format(
                    mid=event.message.id,
                    rid=reply.id,
                    sid=reply.sender_id or "—",
                ),
                parse_mode="html",
            )
        else:
            await event.reply(
                self.strings("id_msg").format(
                    mid=event.message.id,
                    cid=event.chat_id,
                ),
                parse_mode="html",
            )
