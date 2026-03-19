"""
Kitsune built-in: Help
Команда .help — список всех модулей и команд.
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

# Human-friendly display names for built-in modules
_DISPLAY_NAMES: dict[str, str] = {
    "backup":   "Backup",
    "eval":     "Evaluator",
    "health":   "Health",
    "help":     "Help",
    "loader":   "Loader",
    "notifier": "Notifier",
    "paste":    "Pastebin",
    "ping":     "Ping",
    "security": "Security",
    "settings": "Settings",
    "updater":  "Updater",
}


class HelpModule(KitsuneModule):
    name        = "help"
    description = "Список команд и модулей"
    author      = "Yushi"

    strings_ru = {
        "header":     "🦊 <b>Kitsune Userbot</b> — {count} модулей загружено:\n\n",
        "module_fmt": "▫️ <b>{name}:</b> ( {cmds} )\n",
        "no_modules": "Модули не загружены.",
    }

    @command("help", required=OWNER)
    async def help_cmd(self, event) -> None:
        """.help [module] — показать помощь"""
        args = self.get_args(event)
        loader = getattr(self.client, "_kitsune_loader", None)

        if args:
            mod_name = args.lower()
            if loader:
                mod = loader.modules.get(mod_name)
                if mod:
                    await self._send_module_help(event, mod)
                    return
            await event.reply(f"❌ Модуль <code>{mod_name}</code> не найден.", parse_mode="html")
            return

        if not loader or not loader.modules:
            await event.reply(self.strings("no_modules"), parse_mode="html")
            return

        # Get current prefix for showing commands
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        prefix = dispatcher._prefix if dispatcher else "."

        count = len(loader.modules)
        text = self.strings("header").format(count=count)

        for name, mod in sorted(loader.modules.items()):
            cmds = self._get_commands(mod)
            display = _DISPLAY_NAMES.get(name) or (mod.name or name).capitalize()
            cmds_str = " | ".join(f"<code>{prefix}{c}</code>" for c in cmds) if cmds else "—"
            text += self.strings("module_fmt").format(name=display, cmds=cmds_str)

        await event.reply(text, parse_mode="html")

    async def _send_module_help(self, event, mod: KitsuneModule) -> None:
        import inspect
        lines = [
            f"📦 <b>{mod.name}</b>  v{mod.version}",
            f"<i>{mod.description or '—'}</i>\n",
        ]
        for attr_name in dir(mod):
            method = getattr(mod, attr_name, None)
            if callable(method) and hasattr(method, "_kitsune_command"):
                doc = (inspect.getdoc(method) or "").strip()
                lines.append(f"  • <code>.{method._kitsune_command}</code> — {doc or '—'}")
        await event.reply("\n".join(lines), parse_mode="html")

    @staticmethod
    def _get_commands(mod: KitsuneModule) -> list[str]:
        cmds = []
        for attr in dir(mod):
            method = getattr(mod, attr, None)
            if callable(method) and hasattr(method, "_kitsune_command"):
                cmds.append(method._kitsune_command)
        return sorted(cmds)
