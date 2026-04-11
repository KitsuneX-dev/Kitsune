
from __future__ import annotations

import time

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

def _fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    parts.append(f"{minutes}м")
    return " ".join(parts)

class PingModule(KitsuneModule):
    name        = "ping"
    description = "Пинг и базовая информация"
    author      = "Yushi"
    version     = "1.0"

    strings_ru = {
        "pong": (
            "━━━━━━━━━━━━━━\n"
            " \n"
            "🛰 Задержка: <code>{ms:.0f} мс</code>\n"
            "⏱ Аптайм: <code>{uptime}</code>\n"
            "💠 Версия: <code>{version}</code>\n"
            "🌑 Статус: <code>Beta (Stable)</code>\n"
            " \n"
            "━━━━━━━━━━━━━━"
        ),
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

    _start_time: float = time.time()

    async def on_load(self) -> None:
        PingModule._start_time = time.time()
        await self.db.set("kitsune.ping", "start_time", PingModule._start_time)

    @command("ping", required=OWNER)
    async def ping_cmd(self, event) -> None:
        from ..version import __version_str__

        start = time.perf_counter()
        msg = await event.reply("⏳", parse_mode="html")
        ms = (time.perf_counter() - start) * 1000

        stored_start = self.db.get("kitsune.ping", "start_time", None)
        uptime_sec = time.time() - (float(stored_start) if stored_start else self._start_time)

        await msg.edit(
            self.strings("pong").format(
                ms=ms,
                uptime=_fmt_uptime(uptime_sec),
                version=__version_str__,
            ),
            parse_mode="html",
        )

    @command("me", required=OWNER)
    async def me_cmd(self, event) -> None:
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
