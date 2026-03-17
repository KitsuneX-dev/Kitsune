"""
Kitsune built-in: Help
Команда .help — список всех модулей и команд.
"""

# © Yushi (@Mikasu32), 2024-2025
# Kitsune Userbot — License: AGPLv3

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER


class HelpModule(KitsuneModule):
    name        = "help"
    description = "Список команд и модулей"
    author      = "Yushi"

    strings = {
        "header":     "🦊 <b>Kitsune Userbot</b> — список команд\n\n",
        "module_fmt": "📦 <b>{name}</b>  <i>{desc}</i>\n    Команды: {cmds}\n\n",
        "no_modules": "Модули не загружены.",
    }

    strings_ru = {
        "header":     "🦊 <b>Kitsune Userbot</b> — список команд\n\n",
        "module_fmt": "📦 <b>{name}</b>  <i>{desc}</i>\n    Команды: {cmds}\n\n",
        "no_modules": "Модули не загружены.",
    }

    @command("help", required=OWNER)
    async def help_cmd(self, event) -> None:
        """.help [module] — показать помощь"""
        args = event.message.text.split(maxsplit=1)
        loader = getattr(self.client, "_kitsune_loader", None)

        if len(args) > 1:
            # Help for a specific module
            mod_name = args[1].lower()
            if loader:
                mod = loader.modules.get(mod_name)
                if mod:
                    await self._send_module_help(event, mod)
                    return
            await event.reply(f"❌ Модуль <code>{mod_name}</code> не найден.", parse_mode="html")
            return

        # Full list
        if not loader or not loader.modules:
            await event.reply(self.strings("no_modules"), parse_mode="html")
            return

        text = self.strings("header")
        for name, mod in sorted(loader.modules.items()):
            cmds = self._get_commands(mod)
            text += self.strings("module_fmt").format(
                name=mod.name or name,
                desc=mod.description or "—",
                cmds=", ".join(f"<code>.{c}</code>" for c in cmds) if cmds else "—",
            )

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
