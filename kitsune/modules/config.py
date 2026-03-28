# meta developer: @Mikasu32
# Kitsune — конфигуратор модулей (портирован с Hikka)

from __future__ import annotations

import ast
import logging
import typing

from ..core.loader import KitsuneModule, command, ModuleConfig

logger = logging.getLogger(__name__)

ROW_SIZE = 3
NUM_ROWS = 5

_DB_PREFIX = "kitsune.config"


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_value(value) -> str:
    """Форматирует значение для HTML."""
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


class ConfigModule(KitsuneModule):
    """Интерактивный конфигуратор модулей Kitsune."""

    name        = "Config"
    description = "Интерактивная настройка параметров модулей"
    author      = "@Mikasu32"
    version     = "3.0-kitsune"

    strings_ru = {
        # Категория
        "choose_core":    "⚙️ <b>Выбери категорию</b>",
        "builtin":        "🛰 Встроенные",
        "external":       "🛸 Внешние",
        # Список модулей
        "configure":      "⚙️ <b>Выбери модуль для настройки</b>",
        # Параметры модуля
        "configuring_mod": (
            "⚙️ <b>Выбери параметр для модуля</b> <code>{}</code>\n\n"
            "<b>Текущие настройки:</b>\n\n{}"
        ),
        # Управление параметром
        "configuring_option": (
            "⚙️ <b>Управление параметром</b> <code>{}</code> <b>модуля</b> <code>{}</code>\n"
            "<i>ℹ️ {}</i>\n\n"
            "<b>Стандартное:</b> {}\n\n"
            "<b>Текущее:</b> {}\n\n"
            "{}"
        ),
        "typehint":       "🕵️ <b>Должно быть {}</b>",
        # Кнопки
        "enter_value_btn":   "✍️ Ввести значение",
        "enter_value_desc":  "✍️ Введи новое значение этого параметра",
        "set_default_btn":   "♻️ Значение по умолчанию",
        "back_btn":          "👈 Назад",
        "close_btn":         "🔻 Закрыть",
        # Результат
        "option_saved": (
            "⚙️ <b>Параметр</b> <code>{}</code> <b>модуля</b> <code>{}</code>"
            "<b> сохранён!</b>\n<b>Текущее: {}</b>"
        ),
        "option_reset": (
            "⚙️ <b>Параметр</b> <code>{}</code> <b>модуля</b> <code>{}</code>"
            "<b> сброшен!</b>\n<b>Текущее: {}</b>"
        ),
        # Ошибки
        "no_inline": "❌ <b>Inline-менеджер недоступен.</b>\nНастрой бота через <code>.setbot</code>",
        "no_mods":   "⚙️ <b>Нет модулей с настройками.</b>",
        "no_mod":    "❌ Модуль не найден.",
        "no_option": "❌ Параметр не найден.",
        "fconfig_args": "❌ Использование: <code>.fconfig &lt;модуль&gt; &lt;параметр&gt; &lt;значение&gt;</code>",
        "fconfig_ok":   "✅ <code>{key}</code> = {val}",
    }

    # ─── Helpers ──────────────────────────────────────────────────────────

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
            is_builtin = getattr(mod, "_builtin", False)
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
        values = {k: mod.config[k] for k in mod.config.keys()}
        await self.db.set(f"{_DB_PREFIX}.{mod_name}", "values", values)

    # ─── Экраны ───────────────────────────────────────────────────────────

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

        # Пагинация
        total_pages = -(-len(names) // (NUM_ROWS * ROW_SIZE))  # ceil
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

        # Подсказка типа для списков
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
                # inline_message_id передаём явно, чтобы handler мог отредактировать
                # именно исходную форму, а не временное сообщение-посредник
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

    # ─── Inline-обработчики ввода ──────────────────────────────────────────

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

        # Автоконвертация типа
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
                # Разбиваем по запятой если не питон-литерал
                new_val = [x.strip() for x in query.split(",") if x.strip()]
                if not new_val:
                    new_val = [query]

        mod.config[key] = new_val
        await self._save_config(mod_name, mod)

        # Приоритет: явный inline_message_id из args → тот, что на call-объекте
        iid = inline_message_id or getattr(call, "inline_message_id", "")

        inline = self._inline()
        await inline.edit(
            call,
            self.strings("option_saved").format(
                _esc(key), _esc(mod_name), _fmt_value(new_val)
            ),
            [
                [
                    {"text": self.strings("back_btn"),  "callback": self._cb_configure, "args": (mod_name, builtin)},
                    {"text": self.strings("close_btn"), "callback": self._cb_close},
                ]
            ],
            inline_message_id=iid or None,
        )

    # ─── Callbacks ────────────────────────────────────────────────────────

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

    # ─── Команды ──────────────────────────────────────────────────────────

    @command("config")
    async def config_cmd(self, event) -> None:
        """.config — интерактивная настройка модулей."""
        inline = self._inline()
        if not inline or not inline._bot:
            await event.message.edit(self.strings("no_inline"), parse_mode="html")
            return

        args   = self.get_args(event).strip()

        # Редактируем сообщение-команду сразу, чтобы не удалялось
        await event.message.edit("⚙️ <b>Загрузка...</b>", parse_mode="html")
        await self._screen_choose_category(event.message)

    @command("fconfig")
    async def fconfig_cmd(self, event) -> None:
        """.fconfig <модуль> <параметр> <значение> — быстрая установка без UI."""
        args = self.get_args(event).split(maxsplit=2)
        if len(args) < 3:
            await event.message.edit(self.strings("fconfig_args"), parse_mode="html")
            return

        mod_name, key, raw_val = args
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

        mod.config[key] = new_val
        await self._save_config(mod_name, mod)
        await event.message.edit(
            self.strings("fconfig_ok").format(key=_esc(key), val=_fmt_value(new_val)),
            parse_mode="html",
        )
