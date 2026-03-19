"""
Kitsune built-in: Module Loader
Команды: .loadmod .unloadmod .updatemod .mods
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from ..core.loader import KitsuneModule, command, ModuleLoadError, ASTSecurityError
from ..core.security import OWNER

_DB_OWNER = "kitsune.loader"
_DB_KEY_MODS = "user_modules"


class LoaderModule(KitsuneModule):
    name        = "loader"
    description = "Управление модулями"
    author      = "Yushi"

    strings_ru = {
        "loading":       "⏳ Загружаю <code>{name}</code>...",
        "loaded":        "✅ Модуль <b>{name}</b> v{ver} загружен.",
        "unloaded":      "✅ Модуль <b>{name}</b> выгружен.",
        "not_found":     "❌ Модуль <code>{name}</code> не найден.",
        "security_err":  "🚫 Модуль отклонён (нарушение безопасности):\n<code>{err}</code>",
        "load_err":      "❌ Ошибка загрузки:\n<code>{err}</code>",
        "no_url":        "❌ Укажи URL: <code>.loadmod https://...</code>",
        "mods_header":   "📦 <b>Загружённые модули:</b>\n\n",
        "mod_line":      "  • <b>{name}</b> v{ver} — {desc}\n",
        "no_mods":       "Нет загруженных модулей.",
    }

    async def on_load(self) -> None:
        """Restore previously loaded user modules."""
        saved = self.db.get(_DB_OWNER, _DB_KEY_MODS, [])
        if not saved:
            return
        loader = self._get_loader()
        if loader is None:
            return
        for url in saved:
            try:
                await loader.load_from_url(url)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning("Loader: failed to restore %s — %s", url, exc)

    def _get_loader(self):
        return getattr(self.client, "_kitsune_loader", None)

    @command("loadmod", required=OWNER)
    async def loadmod_cmd(self, event) -> None:
        """.loadmod <url> — загрузить модуль по URL"""
        parts = event.message.text.split(maxsplit=1)
        if len(parts) < 2:
            await event.reply(self.strings("no_url"), parse_mode="html")
            return

        url = parts[1].strip()
        m = await event.reply(
            self.strings("loading").format(name=url.split("/")[-1]),
            parse_mode="html",
        )
        loader = self._get_loader()
        if loader is None:
            return

        try:
            mod = await loader.load_from_url(url)
            # Persist URL so it survives restart
            saved = list(self.db.get(_DB_OWNER, _DB_KEY_MODS, []))
            if url not in saved:
                saved.append(url)
                await self.db.set(_DB_OWNER, _DB_KEY_MODS, saved)
            await m.edit(
                self.strings("loaded").format(name=mod.name, ver=mod.version),
                parse_mode="html",
            )
        except ASTSecurityError as exc:
            await m.edit(self.strings("security_err").format(err=str(exc)), parse_mode="html")
        except ModuleLoadError as exc:
            await m.edit(self.strings("load_err").format(err=str(exc)), parse_mode="html")
        except Exception as exc:
            await m.edit(self.strings("load_err").format(err=str(exc)), parse_mode="html")

    @command("unloadmod", required=OWNER)
    async def unloadmod_cmd(self, event) -> None:
        """.unloadmod <name> — выгрузить модуль"""
        parts = event.message.text.split(maxsplit=1)
        if len(parts) < 2:
            await event.reply("❌ Укажи имя модуля.", parse_mode="html")
            return

        name = parts[1].strip().lower()
        loader = self._get_loader()
        if loader and await loader.unload(name):
            # Remove from persisted list
            saved = list(self.db.get(_DB_OWNER, _DB_KEY_MODS, []))
            saved = [u for u in saved if name not in u.lower()]
            await self.db.set(_DB_OWNER, _DB_KEY_MODS, saved)
            await event.reply(self.strings("unloaded").format(name=name), parse_mode="html")
        else:
            await event.reply(self.strings("not_found").format(name=name), parse_mode="html")

    @command("mods", required=OWNER)
    async def mods_cmd(self, event) -> None:
        """.mods — список загруженных модулей"""
        loader = self._get_loader()
        if not loader or not loader.modules:
            await event.reply(self.strings("no_mods"), parse_mode="html")
            return

        text = self.strings("mods_header")
        for name, mod in sorted(loader.modules.items()):
            text += self.strings("mod_line").format(
                name=mod.name or name,
                ver=mod.version,
                desc=mod.description or "—",
            )
        await event.reply(text, parse_mode="html")
