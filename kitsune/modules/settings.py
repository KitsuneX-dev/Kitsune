"""
Kitsune built-in: Settings
Команды: .prefix .lang .setowner
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

_DB_OWNER = "kitsune.core"


class SettingsModule(KitsuneModule):
    name        = "settings"
    description = "Настройки Kitsune"
    author      = "Yushi"

    strings_ru = {
        "prefix_set":    "✅ Префикс изменён на <code>{p}</code>",
        "prefix_same":   "ℹ️ Префикс уже <code>{p}</code>",
        "prefix_usage":  "Использование: <code>.prefix &lt;символ&gt;</code>",
        "lang_set":      "✅ Язык изменён на <code>{lang}</code>",
        "lang_usage":    "Использование: <code>.lang &lt;ru|en|de|...&gt;</code>",
        "info_header":   "🦊 <b>Kitsune Userbot</b>\n\n",
        "info_line":     "<b>{key}:</b> <code>{val}</code>\n",
    }

    @command("prefix", required=OWNER)
    async def prefix_cmd(self, event) -> None:
        """.prefix <символ> — сменить префикс команд"""
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        current_prefix = dispatcher._prefix if dispatcher else "."
        # Strip prefix + command name to get the argument
        raw = event.message.text[len(current_prefix):].split(maxsplit=1)
        if len(raw) < 2 or not raw[1].strip():
            await event.reply(self.strings("prefix_usage"), parse_mode="html")
            return

        new_prefix = raw[1].strip()[:3]
        # Берём текущий префикс из диспетчера (не из БД), чтобы сравнение было точным
        old_prefix = dispatcher._prefix if dispatcher else self.db.get(_DB_OWNER, "prefix", ".")

        if new_prefix == old_prefix:
            await event.reply(
                self.strings("prefix_same").format(p=new_prefix), parse_mode="html"
            )
            return

        await self.db.set(_DB_OWNER, "prefix", new_prefix)

        # Apply to dispatcher immediately
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        if dispatcher:
            dispatcher.set_prefix(new_prefix)

        # Save to config.toml so it persists after restart
        try:
            import toml
            from pathlib import Path
            cfg_path = Path(__file__).parent.parent.parent / "config.toml"
            if cfg_path.exists():
                cfg = toml.loads(cfg_path.read_text(encoding="utf-8"))
                cfg["prefix"] = new_prefix
                cfg_path.write_text(toml.dumps(cfg), encoding="utf-8")
        except Exception:
            pass

        await event.reply(self.strings("prefix_set").format(p=new_prefix), parse_mode="html")

    @command("lang", required=OWNER)
    async def lang_cmd(self, event) -> None:
        """.lang <код> — сменить язык интерфейса"""
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        current_prefix = dispatcher._prefix if dispatcher else "."
        raw = event.message.text[len(current_prefix):].split(maxsplit=1)
        if len(raw) < 2 or not raw[1].strip():
            await event.reply(self.strings("lang_usage"), parse_mode="html")
            return

        lang = raw[1].strip().lower()[:5]
        await self.db.set(_DB_OWNER, "lang", lang)
        await event.reply(self.strings("lang_set").format(lang=lang), parse_mode="html")

    @command("info", required=OWNER)
    async def info_cmd(self, event) -> None:
        """.info — информация о боте и системе"""
        import platform, sys, psutil
        from ..version import __version_str__
        from ..utils import IS_TERMUX, IS_DOCKER

        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.2)

        env_tag = (
            "Termux" if IS_TERMUX
            else "Docker" if IS_DOCKER
            else platform.system()
        )

        loader = getattr(self.client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0

        lines = [
            self.strings("info_header"),
            self.strings("info_line").format(key="Версия",   val=__version_str__),
            self.strings("info_line").format(key="Python",   val=sys.version.split()[0]),
            self.strings("info_line").format(key="Среда",    val=env_tag),
            self.strings("info_line").format(key="Модули",   val=mod_count),
            self.strings("info_line").format(key="ОЗУ",      val=f"{mem.used // 1024 // 1024} / {mem.total // 1024 // 1024} МБ"),
            self.strings("info_line").format(key="CPU",      val=f"{cpu:.1f}%"),
        ]
        await event.reply("".join(lines), parse_mode="html")
