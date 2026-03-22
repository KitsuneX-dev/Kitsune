from __future__ import annotations

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

_BUILTIN_NAMES = {
    "backup", "config", "eval", "health", "help", "info",
    "loader", "notifier", "paste", "ping",
    "security", "settings", "updater",
}

_DISPLAY_NAMES: dict[str, str] = {
    "backup":   "Backup",
    "config":   "Config",
    "eval":     "Evaluator",
    "health":   "Health",
    "help":     "Help",
    "info":     "Info",
    "loader":   "Loader",
    "notifier": "Notifier",
    "paste":    "Pastebin",
    "ping":     "Tester",
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
        "sys_header": "▪ <b>Системные модули:</b>\n",
        "usr_header": "\n▫️ <b>Пользовательские модули:</b>\n",
        "module_sys": "▪ <b>{name}:</b> ( {cmds} )\n",
        "module_usr": "▫️ <b>{name}:</b> ( {cmds} )\n",
        "no_modules": "Модули не загружены.",
    }

    @command("help", required=OWNER)
    async def help_cmd(self, event) -> None:
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

        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        prefix = dispatcher._prefix if dispatcher else "."

        count = len(loader.modules)
        text = self.strings("header").format(count=count)

        sys_mods = {}
        usr_mods = {}
        for name, mod in sorted(loader.modules.items()):
            if getattr(mod, "_is_builtin", name in _BUILTIN_NAMES):
                sys_mods[name] = mod
            else:
                usr_mods[name] = mod

        if sys_mods:
            text += self.strings("sys_header")
            for name, mod in sys_mods.items():
                cmds = self._get_commands(mod)
                display = _DISPLAY_NAMES.get(name) or (mod.name or name).capitalize()
                cmds_str = " | ".join(f"<code>{prefix}{c}</code>" for c in cmds) if cmds else "—"
                text += self.strings("module_sys").format(name=display, cmds=cmds_str)

        if usr_mods:
            text += self.strings("usr_header")
            for name, mod in usr_mods.items():
                cmds = self._get_commands(mod)
                display = _DISPLAY_NAMES.get(name) or (mod.name or name).capitalize()
                cmds_str = " | ".join(f"<code>{prefix}{c}</code>" for c in cmds) if cmds else "—"
                text += self.strings("module_usr").format(name=display, cmds=cmds_str)

        await event.reply(text, parse_mode="html")

    async def _send_module_help(self, event, mod: KitsuneModule) -> None:
        import inspect
        lines = [
            f"📦 <b>{mod.name}</b>  v{mod.version}",
            f"<i>{mod.description or '—'}</i>\n",
        ]
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        prefix = dispatcher._prefix if dispatcher else "."
        for attr_name in dir(mod):
            method = getattr(mod, attr_name, None)
            if callable(method) and hasattr(method, "_kitsune_command"):
                doc = (inspect.getdoc(method) or "").strip()
                cmd_name = method._kitsune_command
                if doc.startswith(("." + cmd_name, prefix + cmd_name)):
                    doc = doc[len(prefix) + len(cmd_name):].lstrip(" —-")
                lines.append(f"  • <code>{prefix}{cmd_name}</code> — {doc or '—'}")
        await event.reply("\n".join(lines), parse_mode="html")

    @staticmethod
    def _get_commands(mod: KitsuneModule) -> list[str]:
        cmds = []
        for attr in dir(mod):
            method = getattr(mod, attr, None)
            if callable(method) and hasattr(method, "_kitsune_command"):
                cmds.append(method._kitsune_command)
        return sorted(cmds)
