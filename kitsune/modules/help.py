from __future__ import annotations

import inspect

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER


class HelpModule(KitsuneModule):
    """Список команд и модулей."""

    name        = "help"
    description = "Список команд и модулей"
    author      = "@Mikasu32"
    _builtin    = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue(
                "core_emoji",
                default="▪️",
                doc="Эмодзи для встроенных модулей. Можно вставить tg-emoji.",
            ),
            ConfigValue(
                "plain_emoji",
                default="▫️",
                doc="Эмодзи для пользовательских модулей.",
            ),
            ConfigValue(
                "desc_icon",
                default="🦊",
                doc="Иконка перед заголовком .help.",
            ),
            ConfigValue(
                "command_emoji",
                default="▫️",
                doc="Эмодзи перед каждой командой в детальном .help <модуль>.",
            ),
            ConfigValue(
                "banner_url",
                default=None,
                doc="Прямая ссылка на баннер (gif/mp4/jpg). Оставь пустым чтобы убрать.",
            ),
        )

    strings_ru = {
        "header":     "{count} модулей доступно, {hidden} скрыто:",
        "no_modules": "⚙️ Модули не загружены.",
        "no_mod":     "❌ Модуль <code>{name}</code> не найден.",
    }

    # ─── helpers ──────────────────────────────────────────────────────────

    def _prefix(self) -> str:
        d = getattr(self.client, "_kitsune_dispatcher", None)
        return d._prefix if d else "."

    def _loader(self):
        return getattr(self.client, "_kitsune_loader", None)

    def _inline(self):
        return getattr(self.client, "_kitsune_inline", None)

    @staticmethod
    def _get_cmds(mod: KitsuneModule) -> list[str]:
        out = []
        for attr in dir(mod):
            m = getattr(mod, attr, None)
            if callable(m) and getattr(m, "_is_command", False):
                out.append(m._command_name)
        return sorted(out)

    # ─── команды ──────────────────────────────────────────────────────────

    @command("help", required=OWNER)
    async def help_cmd(self, event) -> None:
        """.help [модуль] — список всех модулей или детали модуля."""
        args = self.get_args(event).strip()
        loader = self._loader()

        if not loader or not loader.modules:
            await event.message.edit(self.strings("no_modules"), parse_mode="html")
            return

        if args:
            mod = loader.modules.get(args.lower())
            if not mod:
                await event.message.edit(
                    self.strings("no_mod").format(name=args),
                    parse_mode="html",
                )
                return
            await self._mod_help(event, mod)
            return

        await self._full_help(event, loader)

    async def _full_help(self, event, loader) -> None:
        hidden: list[str] = self.db.get("kitsune.help", "hidden", []) if self.db else []

        core_lines:  list[str] = []
        plain_lines: list[str] = []

        for name, mod in sorted(loader.modules.items(), key=lambda x: x[0].lower()):
            cmds = self._get_cmds(mod)
            if not cmds:
                continue
            is_core = getattr(mod, "_is_builtin", False)
            icon    = self.config["core_emoji"] if is_core else self.config["plain_emoji"]
            display = mod.name or name.capitalize()
            hidden_mark = " 🙈" if name in hidden else ""
            line = f"\n{icon} <code>{display}</code>{hidden_mark}: ( {' | '.join(cmds)} )"
            if is_core:
                core_lines.append(line)
            else:
                plain_lines.append(line)

        total        = len(loader.modules)
        hidden_count = len(hidden)

        body = (
            f"{self.config['desc_icon']} "
            f"<b>{self.strings('header').format(count=total, hidden=hidden_count)}</b>"
        )

        if core_lines:
            body += (
                "\n<blockquote expandable collapsed>"
                + "".join(core_lines)
                + "\n</blockquote>"
            )

        if plain_lines:
            body += (
                "\n<blockquote expandable collapsed>"
                + "".join(plain_lines)
                + "\n</blockquote>"
            )

        banner = self.config["banner_url"]
        inline = self._inline()

        if banner and inline and getattr(inline, "_bot", None):
            try:
                await inline.form(
                    text=body,
                    message=event.message,
                    reply_markup=[],
                    gif=banner,
                )
                return
            except Exception:
                pass

        await event.message.edit(body, parse_mode="html")

    async def _mod_help(self, event, mod: KitsuneModule) -> None:
        prefix  = self._prefix()
        icon    = self.config["desc_icon"]
        display = mod.name or mod.__class__.__name__
        version = getattr(mod, "version", "")
        ver_str = f" <i>v{version}</i>" if version else ""

        header = f"{icon} <b>{display}</b>{ver_str}:"
        if mod.description:
            header += f"\n<i>ℹ️ {mod.description}</i>"

        cmd_lines = []
        for attr in sorted(dir(mod)):
            m = getattr(mod, attr, None)
            if not (callable(m) and getattr(m, "_is_command", False)):
                continue
            cmd_name = m._command_name
            doc = (inspect.getdoc(m) or "").strip()
            if "—" in doc:
                doc = doc.split("—", 1)[-1].strip()
            elif doc.lower().startswith(f"{prefix}{cmd_name}") or doc.lower().startswith(f".{cmd_name}"):
                doc = ""
            cmd_lines.append(
                f"{self.config['command_emoji']} <code>{prefix}{cmd_name}</code>"
                + (f" — {doc}" if doc else "")
            )

        body = header
        if cmd_lines:
            body += (
                "\n<blockquote expandable collapsed>\n"
                + "\n".join(cmd_lines)
                + "\n</blockquote>"
            )

        await event.message.edit(body, parse_mode="html")

    @command("helphide", required=OWNER)
    async def helphide_cmd(self, event) -> None:
        """.helphide <модуль> — скрыть/показать модуль в .help."""
        args = self.get_args(event).strip().lower()
        if not args:
            await event.message.edit("❌ Укажи имя модуля.", parse_mode="html")
            return

        hidden: list[str] = self.db.get("kitsune.help", "hidden", []) if self.db else []
        if args in hidden:
            hidden.remove(args)
            status = f"👁 Модуль <code>{args}</code> снова виден в .help."
        else:
            hidden.append(args)
            status = f"🙈 Модуль <code>{args}</code> скрыт из .help."

        if self.db:
            await self.db.set("kitsune.help", "hidden", hidden)

        await event.message.edit(status, parse_mode="html")