from __future__ import annotations

import inspect

from telethon.extensions import html as tl_html
from telethon.tl.types import MessageEntityBlockquote

import logging
from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
logger = logging.getLogger(__name__)
from ..core.security import OWNER
from ..assets import GUIDE_BANNER

class HelpModule(KitsuneModule):

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
            ConfigValue(
                "show_banner",
                default=False,
                doc="Показывать баннер Kitsune Guide перед списком модулей. True/False.",
            ),
        )

    strings_ru = {
        "header":     "{count} модулей доступно, {hidden} скрыто:",
        "no_modules": "⚙️ Модули не загружены.",
        "no_mod":     "❌ Модуль <code>{name}</code> не найден.",
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

    # ── Конфиг страниц ────────────────────────────────────────────────────────
    # С баннером: 12 модулей (фото занимает место, меньше = читабельнее)
    # Без баннера: 20 модулей (чистый текст, Telegram лимит 4096 символов)
    MODS_PER_PAGE_BANNER = 12
    MODS_PER_PAGE_TEXT   = 20

    async def _full_help(self, event, loader) -> None:
        prefix = self._prefix()
        hidden: list[str] = self.db.get("kitsune.help", "hidden", []) if self.db else []

        # ── Собираем все строки модулей ───────────────────────────────────────
        entries: list[tuple[bool, str]] = []  # (is_core, line)
        for name, mod in sorted(loader.modules.items(), key=lambda x: x[0].lower()):
            if name in hidden:
                continue
            cmds = self._get_cmds(mod)
            if not cmds:
                continue
            is_core = getattr(mod, "_is_builtin", False)
            icon    = self.config["core_emoji"] if is_core else self.config["plain_emoji"]
            display = mod.name or name.capitalize()
            line    = f"{icon} <code>{display}</code>: ( {' | '.join(prefix + c for c in cmds)} )"
            entries.append((is_core, line))

        total        = len(loader.modules)
        hidden_count = len(hidden)

        # ── Разбиваем на страницы ─────────────────────────────────────────────
        # Размер страницы зависит от того включён ли баннер
        try:
            show_banner_early = bool(self.config["show_banner"])
        except Exception:
            show_banner_early = True
        mods_per_page = self.MODS_PER_PAGE_BANNER if show_banner_early else self.MODS_PER_PAGE_TEXT

        pages: list[list[tuple[bool, str]]] = []
        page: list[tuple[bool, str]] = []
        for entry in entries:
            page.append(entry)
            if len(page) >= mods_per_page:
                pages.append(page)
                page = []
        if page:
            pages.append(page)

        if not pages:
            await event.message.edit(self.strings("no_modules"), parse_mode="html")
            return

        desc_icon = self.config["desc_icon"]

        def make_page_text(idx: int) -> str:
            hdr = (
                f"{desc_icon} <b>{self.strings('header').format(count=total, hidden=hidden_count)}</b>"
                f"   <i>стр. {idx + 1}/{len(pages)}</i>\n"
            )
            core_l  = [ln for ic, ln in pages[idx] if ic]
            plain_l = [ln for ic, ln in pages[idx] if not ic]
            body = hdr
            if core_l:
                body += "\n<blockquote expandable>\n" + "\n".join(core_l) + "\n</blockquote>"
            if plain_l:
                body += "\n<blockquote expandable>\n" + "\n".join(plain_l) + "\n</blockquote>"
            return body

        inline     = self._inline()
        total_pages = len(pages)

        # ── Inline-пагинация (через бота) ─────────────────────────────────────
        _bot = getattr(inline, "_bot", None) if inline else None

        if inline and _bot:
            # Гарантируем что _bot_username инициализирован ДО вызова form()
            # Без этого _invoke_unit зависает на 30 с если get_me() медленный
            if not getattr(inline, "_bot_username", None):
                try:
                    _me = await _bot.get_me()
                    inline._bot_username = _me.username
                    logger.debug("help: pre-fetched bot username: %s", inline._bot_username)
                except Exception as _e:
                    logger.warning("help: не удалось получить bot username: %s — fallback", _e)
                    _bot = None  # Помечаем как недоступный

        if inline and _bot:
            state = {"page": 0}

            def make_buttons(idx: int) -> list:
                row = []
                if idx > 0:
                    row.append({"text": "◀️", "callback": _prev})
                row.append({"text": f"📋 {idx + 1} / {total_pages}", "callback": _noop})
                if idx < total_pages - 1:
                    row.append({"text": "▶️", "callback": _next})
                return [row]

            async def _noop(call) -> None:
                await call.answer()

            async def _prev(call) -> None:
                if state["page"] > 0:
                    state["page"] -= 1
                await inline.edit(call, make_page_text(state["page"]), make_buttons(state["page"]))
                await call.answer()

            async def _next(call) -> None:
                if state["page"] < total_pages - 1:
                    state["page"] += 1
                await inline.edit(call, make_page_text(state["page"]), make_buttons(state["page"]))
                await call.answer()

            try:
                await inline.form(
                    text=make_page_text(0),
                    message=event.message,
                    reply_markup=make_buttons(0),
                )
                return
            except Exception as _ie:
                logger.warning("help: inline.form упал: %s — fallback к тексту", _ie)

        # ── Fallback: текст без кнопок ─────────────────────────────────────────
        body = make_page_text(0)
        if total_pages > 1:
            body += f"\n\n<i>📖 Показана стр. 1 из {total_pages}. Установи бота для навигации.</i>"

        await self._edit_collapsed(event.message, body)

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
