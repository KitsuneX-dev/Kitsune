# meta developer: @Mikasu32
# Kitsune — конфигуратор модулей (вдохновлён Hikka)

from __future__ import annotations

import logging

from ..core.loader import KitsuneModule, command, watcher, ModuleConfig

logger = logging.getLogger(__name__)

_DB_PREFIX  = "kitsune.config"
_AWAIT_KEY  = "awaiting_input"
ROW_SIZE    = 2


def _fmt_value(value) -> str:
    """Красиво форматирует значение для HTML-вывода."""
    if value is None or value == "":
        return "<code>—</code>"
    if isinstance(value, bool):
        return "✅ <code>True</code>" if value else "❌ <code>False</code>"
    if isinstance(value, list):
        if not value:
            return "<code>[]</code>"
        items = "\n    ".join(f"<code>{_esc(str(i))}</code>" for i in value)
        return f"<code>[</code>\n    {items}\n<code>]</code>"
    return f"<code>{_esc(str(value))}</code>"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ConfigModule(KitsuneModule):
    """Интерактивный конфигуратор модулей Kitsune."""

    name        = "Config"
    description = "Интерактивная настройка параметров модулей"
    author      = "@Mikasu32"
    version     = "2.0-kitsune"

    strings_ru = {
        "no_inline":   "❌ <b>Inline-менеджер недоступен.</b>\nНастрой бота через <code>.setbot</code>",
        "no_mods":     "⚙️ <b>Нет модулей с настройками.</b>",
        "choose_mod":  "⚙️ <b>Конфигуратор</b>\n\nВыбери модуль для настройки:",
        "mod_cfg": (
            "⚙️ <b>{mod}</b>\n\n"
            "{rows}\n"
            "Выбери параметр для изменения:"
        ),
        "param_cfg": (
            "⚙️ <b>{mod}</b> › <code>{key}</code>\n\n"
            "📄 <i>{doc}</i>\n\n"
            "🔹 По умолчанию: {default}\n"
            "🔸 Текущее:      {current}\n\n"
            "<i>Отправь новое значение следующим сообщением или выбери действие ниже.</i>"
        ),
        "set_done":    "✅ <b>{mod}</b> › <code>{key}</code> = {val}",
        "reset_done":  "🔄 <b>{mod}</b> › <code>{key}</code> сброшен до {val}",
        "cancelled":   "✖️ Ввод отменён.",
        "no_mod":      "❌ Модуль не найден.",
        "no_option":   "❌ Параметр не найден.",
        "fconfig_ok":  "✅ <code>{key}</code> = {val}",
        "fconfig_args":"❌ Использование: <code>.fconfig &lt;модуль&gt; &lt;параметр&gt; &lt;значение&gt;</code>",
        "row":         "▫️ <code>{key}</code>: {val}\n",
    }

    # ─── Вспомогательные методы ────────────────────────────────────────────

    def _inline(self):
        return getattr(self.client, "_kitsune_inline", None)

    def _mods(self) -> dict:
        loader = getattr(self.client, "_kitsune_loader", None)
        if not loader:
            return {}
        return {
            name: mod for name, mod in loader.modules.items()
            if isinstance(getattr(mod, "config", None), ModuleConfig)
        }

    def _mod_display(self, mod) -> str:
        return _esc(mod.name or "")

    def _rows_text(self, mod) -> str:
        lines = ""
        for k in mod.config.keys():
            lines += self.strings("row").format(
                key=_esc(k),
                val=_fmt_value(mod.config[k]),
            )
        return lines or "—"

    def _get_awaiting(self):
        return self.db.get(_DB_PREFIX, _AWAIT_KEY)

    def _set_awaiting(self, state: dict | None):
        self.db.set_sync(_DB_PREFIX, _AWAIT_KEY, state)

    async def _save_config(self, mod_name: str, mod: KitsuneModule) -> None:
        values = {k: mod.config[k] for k in mod.config.keys()}
        await self.db.set(f"{_DB_PREFIX}.{mod_name}", "values", values)

    # ─── Экраны ────────────────────────────────────────────────────────────

    async def _screen_mod_list(self, inline, target, mods=None):
        mods = mods or self._mods()
        if not mods:
            if hasattr(target, "answer"):
                await target.answer(self.strings("no_mods"), show_alert=True)
            else:
                await inline.form(self.strings("no_mods"), target, [
                    [{"text": "✖️ Закрыть", "callback": self._cb_close}]
                ])
            return

        buttons = []
        row = []
        for name, mod in sorted(mods.items()):
            row.append({
                "text": f"⚙️ {self._mod_display(mod) or name}",
                "callback": self._cb_mod,
                "args": (name,),
            })
            if len(row) == ROW_SIZE:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([{"text": "✖️ Закрыть", "callback": self._cb_close}])

        if hasattr(target, "inline_message_id") or hasattr(target, "_edit"):
            await inline.edit(target, self.strings("choose_mod"), buttons)
        else:
            await inline.form(self.strings("choose_mod"), target, buttons)

    async def _screen_mod(self, call, mod_name: str):
        inline = self._inline()
        mods   = self._mods()
        mod    = mods.get(mod_name)
        if not mod:
            await call.answer(self.strings("no_mod"), show_alert=True)
            return

        text = self.strings("mod_cfg").format(
            mod=self._mod_display(mod),
            rows=self._rows_text(mod),
        )

        buttons = []
        row = []
        for k in mod.config.keys():
            row.append({
                "text": f"✏️ {_esc(k)}",
                "callback": self._cb_param,
                "args": (mod_name, k),
            })
            if len(row) == ROW_SIZE:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        buttons.append([
            {"text": "◀️ Назад",    "callback": self._cb_back_list},
            {"text": "✖️ Закрыть", "callback": self._cb_close},
        ])

        await inline.edit(call, text, buttons)

    async def _screen_param(self, call, mod_name: str, key: str, *, cancel_row=False):
        inline = self._inline()
        mods   = self._mods()
        mod    = mods.get(mod_name)
        if not mod or key not in mod.config:
            await call.answer(self.strings("no_option"), show_alert=True)
            return

        text = self.strings("param_cfg").format(
            mod     = self._mod_display(mod),
            key     = _esc(key),
            doc     = _esc(mod.config.get_doc(key) or "Нет описания"),
            default = _fmt_value(mod.config.get_default(key)),
            current = _fmt_value(mod.config[key]),
        )

        # Запоминаем ожидание ввода
        self._set_awaiting({
            "mod":    mod_name,
            "key":    key,
            "chat_id": getattr(call, "chat_id", None),
            "msg_id":  getattr(call, "message_id", None),
        })

        buttons = [
            [{
                "text":     "🔄 Сбросить до дефолта",
                "callback": self._cb_reset,
                "args":     (mod_name, key),
            }],
            [
                {"text": "◀️ Назад",    "callback": self._cb_mod,   "args": (mod_name,)},
                {"text": "✖️ Закрыть", "callback": self._cb_close},
            ],
        ]

        await inline.edit(call, text, buttons)

    # ─── Callbacks ─────────────────────────────────────────────────────────

    async def _cb_mod(self, call, mod_name: str):
        self._set_awaiting(None)
        await self._screen_mod(call, mod_name)

    async def _cb_param(self, call, mod_name: str, key: str):
        await self._screen_param(call, mod_name, key)

    async def _cb_reset(self, call, mod_name: str, key: str):
        inline = self._inline()
        mods   = self._mods()
        mod    = mods.get(mod_name)
        if not mod or key not in mod.config:
            await call.answer(self.strings("no_option"), show_alert=True)
            return

        mod.config[key] = mod.config.get_default(key)
        await self._save_config(mod_name, mod)
        self._set_awaiting(None)

        await call.answer(
            self.strings("reset_done").format(
                mod=self._mod_display(mod),
                key=key,
                val=str(mod.config[key]),
            ),
            show_alert=True,
        )
        await self._screen_mod(call, mod_name)

    async def _cb_back_list(self, call):
        self._set_awaiting(None)
        await self._screen_mod_list(self._inline(), call)

    async def _cb_close(self, call):
        self._set_awaiting(None)
        try:
            await inline_safe_close(call)
        except Exception:
            pass

    # ─── Watcher — перехватывает ввод нового значения ──────────────────────

    @watcher()
    async def config_watcher(self, event) -> None:
        """Обрабатывает ввод нового значения конфига после нажатия кнопки параметра."""
        try:
            state = self._get_awaiting()
            if not state:
                return

            message = event.message
            if not message or not message.text:
                return

            # Только от владельца, в нужном чате
            me = await self.client.get_me()
            if message.sender_id != me.id:
                return

            # Пропускаем команды с префиксом
            dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
            prefix = dispatcher._prefix if dispatcher else "."
            if message.text.startswith(prefix):
                return

            mod_name = state.get("mod")
            key      = state.get("key")

            mods = self._mods()
            mod  = mods.get(mod_name)
            if not mod or key not in mod.config:
                self._set_awaiting(None)
                return

            # Устанавливаем значение
            new_val = message.text.strip()

            # Попытка автоконвертации типа
            old_val = mod.config.get_default(key)
            if isinstance(old_val, bool):
                new_val = new_val.lower() in ("1", "true", "yes", "да")
            elif isinstance(old_val, int):
                try:
                    new_val = int(new_val)
                except ValueError:
                    pass
            elif isinstance(old_val, float):
                try:
                    new_val = float(new_val)
                except ValueError:
                    pass
            elif isinstance(old_val, list):
                import ast
                try:
                    parsed = ast.literal_eval(new_val)
                    if isinstance(parsed, (list, tuple, set)):
                        new_val = list(parsed)
                    else:
                        new_val = [parsed]
                except Exception:
                    new_val = [new_val]

            mod.config[key] = new_val
            await self._save_config(mod_name, mod)
            self._set_awaiting(None)

            await message.delete()
            await message.respond(
                self.strings("set_done").format(
                    mod=self._mod_display(mod),
                    key=_esc(key),
                    val=_fmt_value(new_val),
                ),
                parse_mode="html",
            )

        except Exception:
            logger.exception("config_watcher error")

    # ─── Команды ───────────────────────────────────────────────────────────

    @command("config")
    async def config_cmd(self, event) -> None:
        """.config [модуль] — интерактивная настройка модулей."""
        inline = self._inline()
        if not inline or not inline._bot:
            await event.message.edit(self.strings("no_inline"), parse_mode="html")
            return

        args  = self.get_args(event).strip()
        mods  = self._mods()

        if args:
            # Прямой переход к модулю
            mod = mods.get(args) or mods.get(args.lower())
            if not mod:
                # Ищем по отображаемому имени
                for n, m in mods.items():
                    if (m.name or n).lower() == args.lower():
                        mod = m
                        args = n
                        break

            if mod:
                await inline.form("⚙️", event.message, [])
                # Эмулируем call для _screen_mod
                class _FakeCall:
                    def __init__(self, msg):
                        self.inline_message_id = None
                        self._msg = msg
                    async def answer(self, text="", show_alert=False):
                        pass
                    async def _edit(self, text, **kw):
                        pass
                # Открываем список с прямым переходом
                await self._screen_mod_list(inline, event.message, {args: mod})
                return

        if not mods:
            await event.message.edit(self.strings("no_mods"), parse_mode="html")
            return

        await self._screen_mod_list(inline, event.message, mods)

    @command("fconfig")
    async def fconfig_cmd(self, event) -> None:
        """.fconfig <модуль> <параметр> <значение> — быстрая установка значения без UI."""
        args = self.get_args(event).split(maxsplit=2)
        if len(args) < 3:
            await event.message.edit(self.strings("fconfig_args"), parse_mode="html")
            return

        mod_name, key, raw_val = args
        mods = self._mods()
        mod  = mods.get(mod_name)
        if not mod:
            await event.message.edit(self.strings("no_mod"), parse_mode="html")
            return
        if key not in mod.config:
            await event.message.edit(self.strings("no_option"), parse_mode="html")
            return

        # Автоконвертация
        old_val = mod.config.get_default(key)
        new_val = raw_val
        if isinstance(old_val, bool):
            new_val = raw_val.lower() in ("1", "true", "yes", "да")
        elif isinstance(old_val, int):
            try:
                new_val = int(raw_val)
            except ValueError:
                pass
        elif isinstance(old_val, float):
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


async def inline_safe_close(call):
    try:
        await call._edit("✖️")
    except Exception:
        pass
