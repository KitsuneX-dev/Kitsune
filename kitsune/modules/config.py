from __future__ import annotations

import logging

from ..core.loader import KitsuneModule, command, ModuleConfig
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_PREFIX = "kitsune.config"


class ConfigModule(KitsuneModule):
    name        = "config"
    description = "Настройка параметров модулей"
    author      = "Yushi"

    strings_ru = {
        "no_mods":    "⚙️ Нет модулей с настройками.",
        "choose_mod": "⚙️ <b>Настройки</b>\n\nВыбери модуль для настройки:",
        "mod_cfg":    "⚙️ <b>Настройки — {mod}</b>\n\n{rows}",
        "param_cfg":  (
            "⚙️ <b>{mod}</b> → <code>{key}</code>\n\n"
            "📄 {doc}\n\n"
            "🔹 По умолчанию: <code>{default}</code>\n"
            "🔸 Текущее: <code>{current}</code>\n\n"
            "<i>Отправь новое значение следующим сообщением\n"
            "или нажми кнопку для сброса</i>"
        ),
        "set_done":   "✅ <code>{key}</code> = <code>{val}</code>",
        "reset_done": "✅ <code>{key}</code> сброшен до <code>{val}</code>",
        "row":        "▪ <code>{key}</code>: <b>{val}</b>\n",
    }

    def _get_inline(self):
        return getattr(self.client, "_kitsune_inline", None)

    def _configurable_mods(self):
        loader = getattr(self.client, "_kitsune_loader", None)
        if not loader:
            return {}
        return {
            name: mod for name, mod in loader.modules.items()
            if isinstance(getattr(mod, "config", None), ModuleConfig)
        }

    @command("config", required=OWNER)
    async def config_cmd(self, event) -> None:
        inline = self._get_inline()
        if not inline or not inline._bot:
            await event.reply("❌ Inline-менеджер недоступен.", parse_mode="html")
            return

        mods = self._configurable_mods()
        if not mods:
            await event.reply(self.strings("no_mods"), parse_mode="html")
            return

        await self._show_mod_list_new(inline, event.chat_id, mods)


    async def _show_mod_list_new(self, inline, chat_id: int, mods=None) -> None:
        if mods is None:
            mods = self._configurable_mods()

        buttons = []
        row = []
        for name, mod in sorted(mods.items()):
            display = (mod.name or name).capitalize()
            row.append({
                "text": f"⚙️ {display}",
                "callback": self._cb_show_mod,
                "args": (name,),
            })
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([{"text": "✖️ Закрыть", "callback": self._cb_close}])

        markup = inline.generate_markup(buttons)
        owner_id = self.db.get("kitsune.notifier", "owner_id", None) or chat_id
        try:
            await inline._bot.send_message(
                chat_id=int(owner_id),
                text=self.strings("choose_mod"),
                reply_markup=markup,
                parse_mode="HTML",
            )
        except Exception as e:
            logger.exception("config: failed to send menu")

    async def _show_mod_list(self, inline, msg, mods=None) -> None:
        if mods is None:
            mods = self._configurable_mods()

        buttons = []
        row = []
        for name, mod in sorted(mods.items()):
            display = (mod.name or name).capitalize()
            row.append({
                "text": f"⚙️ {display}",
                "callback": self._cb_show_mod,
                "args": (name,),
            })
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        buttons.append([{"text": "✖️ Закрыть", "callback": self._cb_close}])

        await inline.edit(msg, self.strings("choose_mod"), buttons)

    async def _cb_show_mod(self, call, mod_name: str) -> None:
        inline = self._get_inline()
        mods = self._configurable_mods()
        mod = mods.get(mod_name)
        if not mod:
            await call.answer("❌ Модуль не найден.", show_alert=True)
            return

        rows = ""
        for k in mod.config.keys():
            rows += self.strings("row").format(key=k, val=mod.config[k])

        buttons = []
        for k in mod.config.keys():
            buttons.append([{
                "text": f"✏️ {k}",
                "callback": self._cb_show_param,
                "args": (mod_name, k),
            }])

        buttons.append([
            {"text": "◀️ Назад", "callback": self._cb_back_to_list},
            {"text": "✖️ Закрыть", "callback": self._cb_close},
        ])

        await inline.edit(
            call,
            self.strings("mod_cfg").format(
                mod=(mod.name or mod_name).capitalize(),
                rows=rows or "—",
            ),
            buttons,
        )

    async def _cb_show_param(self, call, mod_name: str, key: str) -> None:
        inline = self._get_inline()
        mods = self._configurable_mods()
        mod = mods.get(mod_name)
        if not mod or key not in mod.config:
            await call.answer("❌ Параметр не найден.", show_alert=True)
            return

        text = self.strings("param_cfg").format(
            mod=(mod.name or mod_name).capitalize(),
            key=key,
            doc=mod.config.get_doc(key) or "Нет описания",
            default=mod.config.get_default(key),
            current=mod.config[key],
        )

        self.db.set_sync(_DB_PREFIX + ".awaiting", "state", {
            "mod": mod_name,
            "key": key,
            "chat_id": call.chat_id,
            "msg_id": call.message_id,
        })

        buttons = [
            [{
                "text": "🔄 Сбросить до дефолта",
                "callback": self._cb_reset_param,
                "args": (mod_name, key),
            }],
            [
                {"text": "◀️ Назад", "callback": self._cb_show_mod, "args": (mod_name,)},
                {"text": "✖️ Закрыть", "callback": self._cb_close},
            ],
        ]

        await inline.edit(call, text, buttons)

    async def _cb_reset_param(self, call, mod_name: str, key: str) -> None:
        inline = self._get_inline()
        mods = self._configurable_mods()
        mod = mods.get(mod_name)
        if not mod or key not in mod.config:
            await call.answer("❌ Параметр не найден.", show_alert=True)
            return

        mod.config[key] = mod.config.get_default(key)
        await self._save_config(mod_name, mod)

        await call.answer(
            self.strings("reset_done").format(key=key, val=mod.config[key]),
            show_alert=True,
        )
        await self._cb_show_mod(call, mod_name)

    async def _cb_back_to_list(self, call) -> None:
        inline = self._get_inline()
        await self._show_mod_list(inline, call)

    async def _cb_close(self, call) -> None:
        try:
            await call._edit("✖️ Закрыто.")
        except Exception:
            pass

    async def _save_config(self, mod_name: str, mod: KitsuneModule) -> None:
        values = {k: mod.config[k] for k in mod.config.keys()}
        await self.db.set(f"{_DB_PREFIX}.{mod_name}", "values", values)
