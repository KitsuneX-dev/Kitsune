from __future__ import annotations

import ast
import logging
import typing

from ..core.loader import KitsuneModule, command, ModuleConfig
from ..core.security import OWNER

logger = logging.getLogger(__name__)

ROW_SIZE = 3
NUM_ROWS = 5

_DB_PREFIX = "kitsune.config"

def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _fmt_value(value) -> str:
    if value is None or value == "":
        return "<code>None</code>"
    if isinstance(value, bool):
        return "<code>True</code>" if value else "<code>False</code>"
    if isinstance(value, list):
        if not value:
            return "<code>[]</code>"
        items = "\n    ".join(f"<code>{_esc(str(i))}</code>" for i in value)
        return f"<code>[</code>\n    {items}\n<code>]</code>"
    return f"<code>{_esc(str(value))}</code>"

def _chunks(lst: list, n: int) -> list:
    return [lst[i:i + n] for i in range(0, len(lst), n)]

def _get_configurable(client) -> dict:
    from ..core.loader import ModuleConfig
    loader = getattr(client, "_kitsune_loader", None)
    if not loader:
        return {}
    return {
        name: mod
        for name, mod in loader.modules.items()
        if isinstance(getattr(mod, "config", None), ModuleConfig)
    }

def _mod_text(mod_name: str, mod) -> str:
    lines = ""
    for k in mod.config.keys():
        lines += f"▫️ <code>{_esc(k)}</code>: <b>{_fmt_value(mod.config[k])}</b>\n"
    return (
        f"⚙️ <b>{_esc(mod.name)}</b> — <code>{_esc(mod_name)}</code>\n\n"
        f"{lines or '—'}"
    )

def _list_text(configurable: dict) -> str:
    if not configurable:
        return "⚙️ <b>Нет модулей с настройками.</b>"
    names = ", ".join(f"<code>{_esc(n)}</code>" for n in sorted(configurable.keys()))
    return f"⚙️ <b>Выбери модуль для настройки:</b>\n\n{names}"

class ConfigModule(KitsuneModule):

    name        = "Config"
    description = "Интерактивная настройка параметров модулей"
    author      = "@Mikasu32"
    version     = "3.0-kitsune"

    strings_ru = {
        "choose_core":    "⚙️ <b>Выбери категорию</b>",
        "builtin":        "🛰 Встроенные",
        "external":       "🛸 Внешние",
        "configure":      "⚙️ <b>Выбери модуль для настройки</b>",
        "configuring_mod": (
            "⚙️ <b>Выбери параметр для модуля</b> <code>{}</code>\n\n"
            "<b>Текущие настройки:</b>\n\n{}"
        ),
        "configuring_option": (
            "⚙️ <b>Управление параметром</b> <code>{}</code> <b>модуля</b> <code>{}</code>\n"
            "<i>ℹ️ {}</i>\n\n"
            "<b>Стандартное:</b> {}\n\n"
            "<b>Текущее:</b> {}\n\n"
            "{}"
        ),
        "typehint":       "🕵️ <b>Должно быть {}</b>",
        "enter_value_btn":   "✍️ Ввести значение",
        "enter_value_desc":  "✍️ Введи новое значение этого параметра",
        "set_default_btn":   "♻️ Значение по умолчанию",
        "back_btn":          "👈 Назад",
        "close_btn":         "🔻 Закрыть",
        "option_saved": (
            "⚙️ <b>Параметр</b> <code>{}</code> <b>модуля</b> <code>{}</code>"
            "<b> сохранён!</b>\n<b>Текущее: {}</b>"
        ),
        "option_reset": (
            "⚙️ <b>Параметр</b> <code>{}</code> <b>модуля</b> <code>{}</code>"
            "<b> сброшен!</b>\n<b>Текущее: {}</b>"
        ),
        "no_inline": "❌ <b>Inline-менеджер недоступен.</b>\nНастрой бота через <code>.setbot</code>",
        "no_mods":   "⚙️ <b>Нет модулей с настройками.</b>",
        "no_mod":    "❌ Модуль не найден.",
        "no_option": "❌ Параметр не найден.",
        "fconfig_args": "❌ Использование: <code>.fconfig &lt;модуль&gt; &lt;параметр&gt; &lt;значение&gt;</code>",
        "fconfig_ok":   "⚙️ <code>{key}</code> = <b>{val}</b>",
    }

    def _inline(self):
        return getattr(self.client, "_kitsune_inline", None)

    def _mods(self, builtin: bool | None = None) -> dict:
        loader = getattr(self.client, "_kitsune_loader", None)
        if not loader:
            return {}
        result = {}
        for name, mod in loader.modules.items():
            if not isinstance(getattr(mod, "config", None), ModuleConfig):
                continue
            is_builtin = getattr(mod, "_is_builtin", False) or getattr(mod, "_builtin", False)
            if builtin is None:
                result[name] = mod
            elif builtin and is_builtin:
                result[name] = mod
            elif not builtin and not is_builtin:
                result[name] = mod
        return result

    def _get_value(self, mod_name: str, key: str) -> str:
        loader = getattr(self.client, "_kitsune_loader", None)
        if not loader:
            return "<code>—</code>"
        mod = loader.modules.get(mod_name)
        if not mod or key not in mod.config:
            return "<code>—</code>"
        return _fmt_value(mod.config[key])

    def _rows_text(self, mod) -> str:
        lines = ""
        for k in mod.config.keys():
            lines += f"▫️ <code>{_esc(k)}</code>: <b>{_fmt_value(mod.config[k])}</b>\n"
        return lines or "—"

    async def _save_config(self, mod_name: str, mod) -> None:
        for k in mod.config.keys():
            await self.db.set(f"{_DB_PREFIX}.{mod_name.lower()}", k, mod.config[k])

    async def _screen_choose_category(self, target):
        inline = self._inline()
        markup = [
            [
                {"text": self.strings("builtin"),  "callback": self._cb_global_config, "args": (True,)},
                {"text": self.strings("external"), "callback": self._cb_global_config, "args": (False,)},
            ],
            [{"text": self.strings("close_btn"), "callback": self._cb_close}],
        ]
        if hasattr(target, "answer"):
            await inline.edit(target, self.strings("choose_core"), markup)
        else:
            await inline.form(self.strings("choose_core"), target, markup)

    async def _screen_mod_list(self, call, builtin: bool, page: int = 0):
        inline = self._inline()
        mods   = self._mods(builtin)

        if not mods:
            await call.answer(self.strings("no_mods"), show_alert=True)
            return

        names = sorted(mods.keys())
        page_names = names[page * NUM_ROWS * ROW_SIZE: (page + 1) * NUM_ROWS * ROW_SIZE]

        btns = [
            {"text": n, "callback": self._cb_configure, "args": (n, builtin)}
            for n in page_names
        ]
        kb = _chunks(btns, ROW_SIZE)

        total_pages = -(-len(names) // (NUM_ROWS * ROW_SIZE))
        if total_pages > 1:
            nav = []
            if page > 0:
                nav.append({"text": "◀️", "callback": self._cb_global_config, "args": (builtin, page - 1)})
            nav.append({"text": f"{page + 1}/{total_pages}", "callback": self._cb_global_config, "args": (builtin, page)})
            if page < total_pages - 1:
                nav.append({"text": "▶️", "callback": self._cb_global_config, "args": (builtin, page + 1)})
            kb.append(nav)

        kb.append([
            {"text": self.strings("back_btn"),  "callback": self._cb_choose_category},
            {"text": self.strings("close_btn"), "callback": self._cb_close},
        ])

        await inline.edit(call, self.strings("configure"), kb)

    async def _screen_mod(self, call, mod_name: str, builtin: bool):
        inline = self._inline()
        loader = getattr(self.client, "_kitsune_loader", None)
        if not loader:
            return
        mod = loader.modules.get(mod_name)
        if not mod:
            await call.answer(self.strings("no_mod"), show_alert=True)
            return

        text = self.strings("configuring_mod").format(
            _esc(mod_name),
            self._rows_text(mod),
        )

        btns = [
            {"text": k, "callback": self._cb_configure_option, "args": (mod_name, k, builtin)}
            for k in mod.config.keys()
        ]
        kb = _chunks(btns, 2)
        kb.append([
            {"text": self.strings("back_btn"),  "callback": self._cb_global_config, "args": (builtin,)},
            {"text": self.strings("close_btn"), "callback": self._cb_close},
        ])

        await inline.edit(call, text, kb)

    async def _screen_option(self, call, mod_name: str, key: str, builtin: bool):
        inline = self._inline()
        loader = getattr(self.client, "_kitsune_loader", None)
        if not loader:
            return
        mod = loader.modules.get(mod_name)
        if not mod or key not in mod.config:
            await call.answer(self.strings("no_option"), show_alert=True)
            return

        doc     = _esc(mod.config.get_doc(key) or "Нет описания")
        default = _fmt_value(mod.config.get_default(key))
        current = _fmt_value(mod.config[key])

        default_val = mod.config.get_default(key)
        if isinstance(default_val, list):
            typehint = self.strings("typehint").format(
                "списком значений (ровно 2 шт.), разделённых «,»\n- Пустым значением"
            )
        else:
            typehint = ""

        text = self.strings("configuring_option").format(
            _esc(key), _esc(mod_name), doc, default, current, typehint
        )

        kb = [
            [{
                "text":    self.strings("enter_value_btn"),
                "input":   self.strings("enter_value_desc"),
                "handler": self._inline_set_config,
                "args":    (mod_name, key, builtin, getattr(call, "inline_message_id", "")),
            }],
            [{
                "text":     self.strings("set_default_btn"),
                "callback": self._cb_reset_default,
                "args":     (mod_name, key, builtin),
            }],
            [
                {"text": self.strings("back_btn"),  "callback": self._cb_configure, "args": (mod_name, builtin)},
                {"text": self.strings("close_btn"), "callback": self._cb_close},
            ],
        ]

        await inline.edit(call, text, kb)

    async def _inline_set_config(
        self, call, query: str, mod_name: str, key: str, builtin: bool,
        inline_message_id: str = "",
    ):
        loader = getattr(self.client, "_kitsune_loader", None)
        if not loader:
            return
        mod = loader.modules.get(mod_name)
        if not mod or key not in mod.config:
            return

        default_val = mod.config.get_default(key)
        new_val = query
        if isinstance(default_val, bool):
            new_val = query.lower() in ("1", "true", "yes", "да")
        elif isinstance(default_val, int):
            try:
                new_val = int(query)
            except ValueError:
                pass
        elif isinstance(default_val, float):
            try:
                new_val = float(query)
            except ValueError:
                pass
        elif isinstance(default_val, list):
            try:
                parsed = ast.literal_eval(query)
                new_val = list(parsed) if isinstance(parsed, (list, tuple, set)) else [parsed]
            except Exception:
                new_val = [x.strip() for x in query.split(",") if x.strip()]
                if not new_val:
                    new_val = [query]

        mod.config[key] = new_val
        await self._save_config(mod_name, mod)
        try:
            await self.db.force_save()
        except Exception:
            logger.warning("_inline_set_config: force_save failed, value may be lost on restart")

        inline = self._inline()

        iid = inline_message_id or getattr(call, "inline_message_id", "") or ""

        doc      = _esc(mod.config.get_doc(key) or "Нет описания")
        default  = _fmt_value(mod.config.get_default(key))
        current  = _fmt_value(mod.config[key])
        default_val2 = mod.config.get_default(key)
        typehint = (
            self.strings("typehint").format(
                "списком значений (ровно 2 шт.), разделённых «,»\n- Пустым значением"
            )
            if isinstance(default_val2, list)
            else ""
        )
        text = self.strings("configuring_option").format(
            _esc(key), _esc(mod_name), doc, default, current, typehint
        )
        kb = [
            [{
                "text":    self.strings("enter_value_btn"),
                "input":   self.strings("enter_value_desc"),
                "handler": self._inline_set_config,
                "args":    (mod_name, key, builtin, iid),
            }],
            [{
                "text":     self.strings("set_default_btn"),
                "callback": self._cb_reset_default,
                "args":     (mod_name, key, builtin),
            }],
            [
                {"text": self.strings("back_btn"),  "callback": self._cb_configure, "args": (mod_name, builtin)},
                {"text": self.strings("close_btn"), "callback": self._cb_close},
            ],
        ]

        if iid:
            logger.debug("_inline_set_config: editing form iid=%s key=%s val=%r", iid, key, new_val)
            await inline.edit(call, text, kb, inline_message_id=iid)
        else:
            logger.warning(
                "_inline_set_config: iid is empty — data saved, cannot refresh form. "
                "inline_message_id arg=%r call.iid=%r",
                inline_message_id, getattr(call, "inline_message_id", None),
            )
            try:
                await inline.edit(call, text, kb)
            except Exception:
                pass

    async def _cb_choose_category(self, call):
        await self._screen_choose_category(call)

    async def _cb_global_config(self, call, builtin: bool, page: int = 0):
        await self._screen_mod_list(call, builtin, page)

    async def _cb_configure(self, call, mod_name: str, builtin: bool):
        await self._screen_mod(call, mod_name, builtin)

    async def _cb_configure_option(self, call, mod_name: str, key: str, builtin: bool):
        await self._screen_option(call, mod_name, key, builtin)

    async def _cb_reset_default(self, call, mod_name: str, key: str, builtin: bool):
        loader = getattr(self.client, "_kitsune_loader", None)
        if not loader:
            return
        mod = loader.modules.get(mod_name)
        if not mod or key not in mod.config:
            await call.answer(self.strings("no_option"), show_alert=True)
            return

        mod.config[key] = mod.config.get_default(key)
        await self._save_config(mod_name, mod)
        try:
            await self.db.force_save()
        except Exception:
            pass

        inline = self._inline()
        await inline.edit(
            call,
            self.strings("option_reset").format(
                _esc(key), _esc(mod_name), _fmt_value(mod.config[key])
            ),
            [
                [
                    {"text": self.strings("back_btn"),  "callback": self._cb_configure, "args": (mod_name, builtin)},
                    {"text": self.strings("close_btn"), "callback": self._cb_close},
                ]
            ],
        )

    async def _cb_close(self, call):
        try:
            await call._edit("✖️")
        except Exception:
            pass

    @command("config", required=OWNER, aliases=["cfg"])
    async def config_cmd(self, event) -> None:
        inline = self._inline()
        if not inline or not inline._bot:
            await event.message.edit(self.strings("no_inline"), parse_mode="html")
            return

        args   = self.get_args(event).strip()

        await event.message.edit("⚙️ <b>Загрузка...</b>", parse_mode="html")
        await self._screen_choose_category(event.message)

    @command("fconfig", required=OWNER, aliases=["fcfg"])
    async def fconfig_cmd(self, event) -> None:

        full_args = self.get_args(event)
        space1 = full_args.find(" ")
        if space1 == -1:
            await event.message.edit(self.strings("fconfig_args"), parse_mode="html")
            return
        mod_name = full_args[:space1]
        rest = full_args[space1 + 1:]
        space2 = rest.find(" ")
        if space2 == -1:
            await event.message.edit(self.strings("fconfig_args"), parse_mode="html")
            return
        key = rest[:space2]
        raw_val = rest[space2 + 1:]
        if not raw_val:
            await event.message.edit(self.strings("fconfig_args"), parse_mode="html")
            return
        loader = getattr(self.client, "_kitsune_loader", None)
        if not loader:
            return
        mod = loader.modules.get(mod_name)
        if not mod:
            await event.message.edit(self.strings("no_mod"), parse_mode="html")
            return
        if key not in mod.config:
            await event.message.edit(self.strings("no_option"), parse_mode="html")
            return

        default_val = mod.config.get_default(key)
        new_val = raw_val

        if isinstance(default_val, (str, type(None))):
            try:
                from telethon.extensions import html as tl_html
                from telethon.tl.types import MessageEntityCustomEmoji
                import copy
                msg = event.message
                full_raw = msg.raw_text or ""
                entities = list(msg.entities or [])
                val_start_raw = full_raw.find(raw_val)
                if val_start_raw >= 0 and entities:
                    val_end_raw = val_start_raw + len(raw_val)
                    relevant = sorted(
                        [
                            e for e in entities
                            if e.offset >= val_start_raw and (e.offset + e.length) <= val_end_raw
                        ],
                        key=lambda x: x.offset,
                    )
                    if relevant:

                        custom_emojis = [e for e in relevant if isinstance(e, MessageEntityCustomEmoji)]
                        other_entities = [e for e in relevant if not isinstance(e, MessageEntityCustomEmoji)]

                        if not custom_emojis:

                            shifted = []
                            for e in other_entities:
                                ec = copy.copy(e)
                                ec.offset = e.offset - val_start_raw
                                shifted.append(ec)
                            new_val = tl_html.unparse(raw_val, shifted)
                        else:

                            result_html = ""
                            cursor = 0  

                            for ce in sorted(custom_emojis, key=lambda x: x.offset):
                                ce_off = ce.offset - val_start_raw  

                                if ce_off > cursor:
                                    before = raw_val[cursor:ce_off]
                                    before_ents = []
                                    for oe in other_entities:
                                        oe_off = oe.offset - val_start_raw
                                        if oe_off >= cursor and (oe_off + oe.length) <= ce_off:
                                            ec = copy.copy(oe)
                                            ec.offset = oe_off - cursor
                                            before_ents.append(ec)
                                    result_html += tl_html.unparse(before, before_ents)

                                inner = raw_val[ce_off:ce_off + ce.length]
                                result_html += f'<tg-emoji emoji-id="{ce.document_id}">{inner}</tg-emoji>'
                                cursor = ce_off + ce.length

                            if cursor < len(raw_val):
                                tail = raw_val[cursor:]
                                tail_ents = []
                                for oe in other_entities:
                                    oe_off = oe.offset - val_start_raw
                                    if oe_off >= cursor:
                                        ec = copy.copy(oe)
                                        ec.offset = oe_off - cursor
                                        tail_ents.append(ec)
                                result_html += tl_html.unparse(tail, tail_ents)

                            new_val = result_html
            except Exception:
                pass  

        if isinstance(default_val, bool):
            new_val = raw_val.lower() in ("1", "true", "yes", "да")
        elif isinstance(default_val, int):
            try:
                new_val = int(raw_val)
            except ValueError:
                pass
        elif isinstance(default_val, float):
            try:
                new_val = float(raw_val)
            except ValueError:
                pass

        if isinstance(new_val, str):
            import re as _re
            new_val = _re.sub(r'<br\s*/?>', '\n', new_val)

        mod.config[key] = new_val
        await self._save_config(mod_name, mod)
        try:
            await self.db.force_save()
        except Exception:
            pass
        await event.message.edit(
            self.strings("fconfig_ok").format(key=_esc(key), val=_fmt_value(new_val)),
            parse_mode="html",
        )
