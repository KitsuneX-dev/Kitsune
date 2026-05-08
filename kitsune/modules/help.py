from __future__ import annotations
import inspect
from telethon.extensions import html as tl_html
from telethon.tl.types import MessageEntityBlockquote
from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

PAGE_SIZE = 30

class HelpModule(KitsuneModule):

    name        = "help"

    description = "Список команд и модулей"


    version     = "1.3.0"

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

        )

    strings_ru = {

        "header":     "{count} модулей доступно, {hidden} скрыто:",

        "header_page": "{count} модулей доступно, {hidden} скрыто • Страница {page}/{total}:",

        "no_modules": "⚙️ Модули не загружены.",

        "no_mod":     "❌ Модуль <code>{name}</code> не найден.",

        "prev_btn":   "◀️ Назад",

        "next_btn":   "Вперёд ▶️",

        "page_btn":   "{page}/{total}",

    }

    @staticmethod

    async def _edit_collapsed(message, html_text: str) -> None:

        text, entities = tl_html.parse(html_text)

        for e in entities:

            if isinstance(e, MessageEntityBlockquote):

                e.collapsed = True

        await message.edit(text, formatting_entities=entities)

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

    @command("help", required=OWNER)

    async def help_cmd(self, event) -> None:

        """help — показать список модулей или подробную справку по конкретному модулю."""

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

        await self._full_help(event, loader, page=0)

    def _collect_visible_modules(self, loader) -> list[tuple[str, "KitsuneModule"]]:

        hidden: list[str] = self.db.get("kitsune.help", "hidden", []) if self.db else []

        visible: list[tuple[str, KitsuneModule]] = []

        for name, mod in sorted(loader.modules.items(), key=lambda x: x[0].lower()):

            if name in hidden:

                continue

            if not self._get_cmds(mod):

                continue

            visible.append((name, mod))

        return visible

    def _build_page_body(self, loader, page: int) -> tuple[str, int, int]:

        prefix = self._prefix()

        hidden: list[str] = self.db.get("kitsune.help", "hidden", []) if self.db else []

        visible = self._collect_visible_modules(loader)

        total_modules_with_cmds = len(visible)

        total_pages = max(1, -(-total_modules_with_cmds // PAGE_SIZE))

        page = max(0, min(page, total_pages - 1))

        start = page * PAGE_SIZE

        end   = start + PAGE_SIZE

        page_slice = visible[start:end]

        core_lines:  list[str] = []

        plain_lines: list[str] = []

        for name, mod in page_slice:

            cmds = self._get_cmds(mod)

            is_core = getattr(mod, "_is_builtin", False)

            icon    = self.config["core_emoji"] if is_core else self.config["plain_emoji"]

            display = mod.name or name.capitalize()

            line = f"\n{icon} <code>{display}</code>: ( {' | '.join(prefix + c for c in cmds)} )"

            if is_core:

                core_lines.append(line)

            else:

                plain_lines.append(line)

        total        = len(loader.modules)

        hidden_count = len(hidden)

        if total_pages > 1:

            header_text = self.strings("header_page").format(

                count=total, hidden=hidden_count,

                page=page + 1, total=total_pages,

            )

        else:

            header_text = self.strings("header").format(count=total, hidden=hidden_count)

        body = f"{self.config['desc_icon']} <b>{header_text}</b>"

        if core_lines:

            body += "\n<blockquote expandable>" + "".join(core_lines) + "\n</blockquote>"

        if plain_lines:

            body += "\n<blockquote expandable>" + "".join(plain_lines) + "\n</blockquote>"

        return body, page, total_pages

    def _build_nav_kb(self, page: int, total_pages: int) -> list:

        if total_pages <= 1:

            return []

        nav_row = []

        if page > 0:

            nav_row.append({

                "text": self.strings("prev_btn"),

                "callback": self._cb_help_page,

                "args": (page - 1,),

            })

        nav_row.append({

            "text": self.strings("page_btn").format(page=page + 1, total=total_pages),

            "callback": self._cb_help_noop,

        })

        if page < total_pages - 1:

            nav_row.append({

                "text": self.strings("next_btn"),

                "callback": self._cb_help_page,

                "args": (page + 1,),

            })

        return [nav_row]

    async def _full_help(self, event, loader, page: int = 0) -> None:

        body, page, total_pages = self._build_page_body(loader, page)

        if total_pages > 1:

            inline = self._inline()

            if inline is not None and getattr(inline, "_bot", None):

                kb = self._build_nav_kb(page, total_pages)

                try:

                    await event.message.edit("🦊 <b>Загрузка...</b>", parse_mode="html")

                except Exception:

                    pass

                try:

                    await inline.form(body, event.message, kb)

                    return

                except Exception:

                    pass

        await self._edit_collapsed(event.message, body)

    async def _cb_help_page(self, call, page: int) -> None:

        loader = self._loader()

        if not loader:

            await call.answer(self.strings("no_modules"), show_alert=True)

            return

        body, page, total_pages = self._build_page_body(loader, page)

        kb = self._build_nav_kb(page, total_pages)

        inline = self._inline()

        if inline is None:

            await call.answer("Inline недоступен.", show_alert=True)

            return

        await inline.edit(call, body, kb)

    async def _cb_help_noop(self, call) -> None:

        try:

            await call.answer("")

        except Exception:

            pass

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

            body += "\n<blockquote expandable>\n" + "\n".join(cmd_lines) + "\n</blockquote>"

        await self._edit_collapsed(event.message, body)

    @command("helphide", required=OWNER)

    async def helphide_cmd(self, event) -> None:

        """helphide — скрыть/показать модуль в выдаче .help."""

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
