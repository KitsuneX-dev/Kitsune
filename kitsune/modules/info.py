from __future__ import annotations

import time

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER
from ..utils import auto_delete

_DB_OWNER = "kitsune.info"

class InfoModule(KitsuneModule):
    name        = "info"
    description = "Информация об аккаунте и UserBot"
    author      = "Yushi"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue("custom_text",  default="🦊 <b>Kitsune Userbot</b>", doc="Текст заголовка в .info"),
            ConfigValue("show_uid",     default=True,  doc="Показывать ID аккаунта"),
            ConfigValue("show_version", default=True,  doc="Показывать версию"),
            ConfigValue("show_uptime",  default=True,  doc="Показывать аптайм"),
            ConfigValue("show_prefix",  default=True,  doc="Показывать префикс"),
            ConfigValue("show_branch",  default=False, doc="Показывать ветку git"),
        )

    strings_ru = {
        "info": (
            "{custom}\n\n"
            "👤 <b>Аккаунт:</b> {name}\n"
            "🆔 <b>ID:</b> <code>{uid}</code>\n"
            "💠 <b>Версия:</b> <code>{version}</code>\n"
            "⏱ <b>Аптайм:</b> <code>{uptime}</code>\n"
            "⌨️ <b>Префикс:</b> <code>{prefix}</code>\n"
            "🌿 <b>Ветка:</b> <code>{branch}</code>"
        ),
        "no_custom":    "🦊 <b>Kitsune Userbot</b>",
        "set_done":     "✅ Инфо-сообщение обновлено.",
        "set_no_args":  "❌ Укажи текст: <code>.setinfo Привет, я Kitsune!</code>",
        "reset_done":   "✅ Инфо-сообщение сброшено.",
    }

    def _fmt_uptime(self) -> str:
        stored = self.db.get("kitsune.ping", "start_time", None)
        secs = int(time.time() - (float(stored) if stored else time.time()))
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        parts = []
        if days:    parts.append(f"{days}д")
        if hours:   parts.append(f"{hours}ч")
        parts.append(f"{minutes}м")
        return " ".join(parts)

    @command("info", required=OWNER)
    async def info_cmd(self, event) -> None:
        from ..version import __version_str__, branch
        me = await self.client.get_me()
        name = me.first_name + (f" {me.last_name}" if me.last_name else "")
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        prefix = dispatcher._prefix if dispatcher else "."
        custom = self.config["custom_text"] if self.config else self.db.get(_DB_OWNER, "custom_text", None) or self.strings("no_custom")

        text = self.strings("info").format(
            custom=custom,
            name=name,
            uid=me.id,
            version=__version_str__,
            uptime=self._fmt_uptime(),
            prefix=prefix,
            branch=branch,
        )
        msg = await event.reply(text, parse_mode="html")
        await auto_delete(msg, delay=30)

    @command("setinfo", required=OWNER)
    async def setinfo_cmd(self, event) -> None:
        args = self.get_args(event)
        if not args:
            await event.reply(self.strings("set_no_args"), parse_mode="html")
            return
        await self.db.set(_DB_OWNER, "custom_text", args)
        if self.config:
            self.config["custom_text"] = args
        m = await event.reply(self.strings("set_done"), parse_mode="html")
        await auto_delete(m)

    @command("resetinfo", required=OWNER)
    async def resetinfo_cmd(self, event) -> None:
        await self.db.delete(_DB_OWNER, "custom_text")
        m = await event.reply(self.strings("reset_done"), parse_mode="html")
        await auto_delete(m)
