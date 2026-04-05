from __future__ import annotations

import logging

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_MAIN = "kitsune.main"
_DB_OWN  = "kitsune.settings_ext"


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class KitsuneSettingsModule(KitsuneModule):
    """Дополнительные настройки Kitsune (watchers, nonick, aliases, toggles)."""

    name        = "KitsuneSettings"
    description = "Расширенные настройки UserBot"
    author      = "@Mikasu32"
    version     = "1.0"
    _builtin    = True

    strings_ru = {
        # nonick
        "nonick_on":        "✅ NoNick включён — имя скрыто в командах.",
        "nonick_off":       "❌ NoNick выключен.",
        "nonick_user_on":   "✅ NoNick для <a href=\"tg://user?id={uid}\">{name}</a> включён.",
        "nonick_user_off":  "❌ NoNick для <a href=\"tg://user?id={uid}\">{name}</a> выключен.",
        "nonick_chat_on":   "✅ NoNick в этом чате включён.",
        "nonick_chat_off":  "❌ NoNick в этом чате выключен.",
        "nonick_cmd_on":    "✅ NoNick для команды <code>{cmd}</code> включён.",
        "nonick_cmd_off":   "❌ NoNick для команды <code>{cmd}</code> выключен.",
        "nonick_list":      "📋 <b>NoNick списки:</b>\n\n👤 Пользователи:\n{users}\n\n💬 Чаты:\n{chats}\n\n⌨️ Команды:\n{cmds}",
        "nothing":          "ℹ️ Список пуст.",
        "no_reply":         "❌ Ответь на сообщение пользователя.",
        # watchers
        "watchers_list":    "👁 <b>Watchers:</b>\n{list}",
        "watcher_off":      "⏸ Watcher <b>{name}</b> выключен.",
        "watcher_on":       "▶️ Watcher <b>{name}</b> включён.",
        "watcher_404":      "❌ Watcher <b>{name}</b> не найден.",
        # core protection
        "core_protect_on":  "🛡 Защита ядра <b>включена</b>.",
        "core_protect_off": "⚠️ Защита ядра <b>выключена</b>.",
        # settings overview
        "settings_info":    (
            "⚙️ <b>Настройки Kitsune</b>\n\n"
            "NoNick: <b>{nonick}</b>\n"
            "Защита ядра: <b>{core_protect}</b>\n"
            "Авто-удаление: <b>{autodel}</b>\n\n"
            "Команды:\n"
            "<code>.nonick</code> — вкл/выкл NoNick\n"
            "<code>.nonickuser</code> — NoNick для пользователя (ответ)\n"
            "<code>.nonickchat</code> — NoNick в текущем чате\n"
            "<code>.nonickcmd &lt;cmd&gt;</code> — NoNick для команды\n"
            "<code>.nonickusers</code> / <code>.nonickchats</code> / <code>.nonickcmds</code> — списки\n"
            "<code>.watchers</code> — список watcher'ов\n"
            "<code>.watcher &lt;name&gt;</code> — вкл/выкл watcher"
        ),
    }

    # ─── NoNick ───────────────────────────────────────────────────────────

    @command("nonick", required=OWNER)
    async def nonick_cmd(self, event) -> None:
        """.nonick — включить/выключить глобальный NoNick."""
        cur = self.db.get(_DB_MAIN, "no_nickname", False)
        await self.db.set(_DB_MAIN, "no_nickname", not cur)
        key = "nonick_on" if not cur else "nonick_off"
        await event.message.edit(self.strings(key), parse_mode="html")

    @command("nonickuser", required=OWNER)
    async def nonickuser_cmd(self, event) -> None:
        """.nonickuser — NoNick для пользователя (ответ на сообщение)."""
        reply = await event.message.get_reply_message()
        if not reply or not reply.sender_id:
            await event.message.edit(self.strings("no_reply"), parse_mode="html")
            return

        uid = reply.sender_id
        users = self.db.get(_DB_MAIN, "nonick_users", [])
        if uid in users:
            users.remove(uid)
            key = "nonick_user_off"
        else:
            users.append(uid)
            key = "nonick_user_on"

        await self.db.set(_DB_MAIN, "nonick_users", users)
        try:
            u = await self.client.get_entity(uid)
            from telethon.utils import get_display_name
            name = _esc(get_display_name(u))
        except Exception:
            name = str(uid)

        await event.message.edit(
            self.strings(key).format(uid=uid, name=name), parse_mode="html"
        )

    @command("nonickchat", required=OWNER)
    async def nonickchat_cmd(self, event) -> None:
        """.nonickchat — NoNick в текущем чате."""
        cid = event.message.chat_id
        chats = self.db.get(_DB_MAIN, "nonick_chats", [])
        if cid in chats:
            chats.remove(cid)
            key = "nonick_chat_off"
        else:
            chats.append(cid)
            key = "nonick_chat_on"
        await self.db.set(_DB_MAIN, "nonick_chats", chats)
        await event.message.edit(self.strings(key), parse_mode="html")

    @command("nonickcmd", required=OWNER)
    async def nonickcmd_cmd(self, event) -> None:
        """.nonickcmd <команда> — NoNick для конкретной команды."""
        cmd = self.get_args(event).strip().lower()
        if not cmd:
            await event.message.edit(
                "Использование: <code>.nonickcmd &lt;команда&gt;</code>",
                parse_mode="html",
            )
            return
        cmds = self.db.get(_DB_MAIN, "nonick_cmds", [])
        if cmd in cmds:
            cmds.remove(cmd)
            key = "nonick_cmd_off"
        else:
            cmds.append(cmd)
            key = "nonick_cmd_on"
        await self.db.set(_DB_MAIN, "nonick_cmds", cmds)
        await event.message.edit(self.strings(key).format(cmd=cmd), parse_mode="html")

    @command("nonickusers", required=OWNER)
    async def nonickusers_cmd(self, event) -> None:
        """.nonickusers — список пользователей с NoNick."""
        users = self.db.get(_DB_MAIN, "nonick_users", [])
        if not users:
            await event.message.edit(self.strings("nothing"), parse_mode="html")
            return
        lines = []
        for uid in users:
            try:
                u = await self.client.get_entity(uid)
                from telethon.utils import get_display_name
                lines.append(f'▫️ <a href="tg://user?id={uid}">{_esc(get_display_name(u))}</a>')
            except Exception:
                lines.append(f"▫️ <code>{uid}</code>")
        await event.message.edit("\n".join(lines), parse_mode="html")

    @command("nonickchats", required=OWNER)
    async def nonickchats_cmd(self, event) -> None:
        """.nonickchats — список чатов с NoNick."""
        chats = self.db.get(_DB_MAIN, "nonick_chats", [])
        if not chats:
            await event.message.edit(self.strings("nothing"), parse_mode="html")
            return
        lines = []
        for cid in chats:
            try:
                c = await self.client.get_entity(int(cid))
                from telethon.utils import get_display_name
                lines.append(f"▫️ <b>{_esc(get_display_name(c))}</b> <code>{cid}</code>")
            except Exception:
                lines.append(f"▫️ <code>{cid}</code>")
        await event.message.edit("\n".join(lines), parse_mode="html")

    @command("nonickcmds", required=OWNER)
    async def nonickcmds_cmd(self, event) -> None:
        """.nonickcmds — список команд с NoNick."""
        cmds = self.db.get(_DB_MAIN, "nonick_cmds", [])
        if not cmds:
            await event.message.edit(self.strings("nothing"), parse_mode="html")
            return
        disp = getattr(self.client, "_kitsune_dispatcher", None)
        prefix = disp._prefix if disp else "."
        lines = [f"▫️ <code>{prefix}{c}</code>" for c in cmds]
        await event.message.edit("\n".join(lines), parse_mode="html")

    # ─── watchers ─────────────────────────────────────────────────────────

    @command("watchers", required=OWNER)
    async def watchers_cmd(self, event) -> None:
        """.watchers — список всех watcher'ов."""
        disp = getattr(self.client, "_kitsune_dispatcher", None)
        if not disp:
            await event.message.edit("❌ Dispatcher недоступен.", parse_mode="html")
            return
        disabled = self.db.get(_DB_MAIN, "disabled_watchers", [])
        lines = []
        for _f, handler in disp._watchers:
            name = getattr(handler.__self__, "name", "?") + "." + handler.__name__
            icon = "⏸" if name in disabled else "▶️"
            lines.append(f"{icon} <code>{name}</code>")
        if not lines:
            await event.message.edit("ℹ️ Watcher'ов нет.", parse_mode="html")
            return
        await event.message.edit(
            self.strings("watchers_list").format(list="\n".join(lines)),
            parse_mode="html",
        )

    @command("watcher", required=OWNER)
    async def watcher_cmd(self, event) -> None:
        """.watcher <name> — включить/выключить watcher."""
        name = self.get_args(event).strip()
        if not name:
            await event.message.edit(
                "Использование: <code>.watcher &lt;name&gt;</code>", parse_mode="html"
            )
            return
        disabled = self.db.get(_DB_MAIN, "disabled_watchers", [])
        if name in disabled:
            disabled.remove(name)
            await self.db.set(_DB_MAIN, "disabled_watchers", disabled)
            await event.message.edit(self.strings("watcher_on").format(name=name), parse_mode="html")
        else:
            disabled.append(name)
            await self.db.set(_DB_MAIN, "disabled_watchers", disabled)
            await event.message.edit(self.strings("watcher_off").format(name=name), parse_mode="html")

    # ─── core protection ───────────────────────────────────────────────────

    @command("enable_core_protection", required=OWNER)
    async def enable_core_protection_cmd(self, event) -> None:
        """.enable_core_protection — включить защиту встроенных модулей."""
        await self.db.set(_DB_MAIN, "remove_core_protection", False)
        await event.message.edit(self.strings("core_protect_on"), parse_mode="html")

    @command("remove_core_protection", required=OWNER)
    async def remove_core_protection_cmd(self, event) -> None:
        """.remove_core_protection — выключить защиту встроенных модулей."""
        await self.db.set(_DB_MAIN, "remove_core_protection", True)
        await event.message.edit(self.strings("core_protect_off"), parse_mode="html")

    # ─── settings overview ─────────────────────────────────────────────────

    @command("settings", required=OWNER)
    async def settings_cmd(self, event) -> None:
        """.settings — обзор настроек Kitsune."""
        nonick  = "✅" if self.db.get(_DB_MAIN, "no_nickname", False) else "❌"
        core    = "❌" if self.db.get(_DB_MAIN, "remove_core_protection", False) else "✅"
        autodel = self.db.get("kitsune.core", "auto_delete_delay", 0)
        autodel_str = f"{autodel} с" if autodel else "❌"
        await event.message.edit(
            self.strings("settings_info").format(
                nonick=nonick, core_protect=core, autodel=autodel_str
            ),
            parse_mode="html",
        )

    # ─── togglecmd / togglemod / clearmodule (from Heroku Settings) ────────

    @command("togglecmd", required=OWNER)
    async def togglecmd_cmd(self, event) -> None:
        """.togglecmd <модуль> <команда> — включить/выключить команду модуля."""
        args = self.get_args(event).split()
        if len(args) < 2:
            await event.message.edit(
                "Использование: <code>.togglecmd &lt;модуль&gt; &lt;команда&gt;</code>",
                parse_mode="html",
            )
            return

        mod_name, cmd_name = args[0], args[1].lower()
        loader = getattr(self.client, "_kitsune_loader", None)
        mod = loader.get_module(mod_name) if loader else None
        if not mod:
            await event.message.edit(f"❌ Модуль <code>{mod_name}</code> не найден.", parse_mode="html")
            return

        disp = getattr(self.client, "_kitsune_dispatcher", None)
        disabled = self.db.get(_DB_OWN, "disabled_commands", {})
        key = mod_name.lower()
        cmds = disabled.get(key, [])

        if cmd_name in cmds:
            cmds.remove(cmd_name)
            # re-register
            for _, method in __import__("inspect").getmembers(mod, predicate=__import__("inspect").ismethod):
                if getattr(method, "_is_command", False) and method._command_name == cmd_name:
                    disp.register_command(cmd_name, method, method._required)
                    break
            msg = f"✅ Команда <code>{cmd_name}</code> снова включена."
        else:
            cmds.append(cmd_name)
            if disp:
                disp.unregister_command(cmd_name)
            msg = f"⏸ Команда <code>{cmd_name}</code> выключена."

        if cmds:
            disabled[key] = cmds
        else:
            disabled.pop(key, None)
        await self.db.set(_DB_OWN, "disabled_commands", disabled)
        await event.message.edit(msg, parse_mode="html")

    @command("togglemod", required=OWNER)
    async def togglemod_cmd(self, event) -> None:
        """.togglemod <модуль> — включить/выключить все команды модуля."""
        mod_name = self.get_args(event).strip()
        if not mod_name:
            await event.message.edit(
                "Использование: <code>.togglemod &lt;модуль&gt;</code>", parse_mode="html"
            )
            return

        loader = getattr(self.client, "_kitsune_loader", None)
        mod = loader.get_module(mod_name) if loader else None
        if not mod:
            await event.message.edit(f"❌ Модуль <code>{mod_name}</code> не найден.", parse_mode="html")
            return

        disp = getattr(self.client, "_kitsune_dispatcher", None)
        disabled = self.db.get(_DB_OWN, "disabled_modules", [])

        if mod_name.lower() in disabled:
            disabled.remove(mod_name.lower())
            # re-register all commands
            if disp:
                import inspect as _insp
                for _, method in _insp.getmembers(mod, predicate=_insp.ismethod):
                    if getattr(method, "_is_command", False):
                        disp.register_command(method._command_name, method, method._required)
            msg = f"✅ Модуль <code>{mod_name}</code> включён."
        else:
            disabled.append(mod_name.lower())
            # unregister all commands
            if disp:
                import inspect as _insp
                for _, method in _insp.getmembers(mod, predicate=_insp.ismethod):
                    if getattr(method, "_is_command", False):
                        disp.unregister_command(method._command_name)
            msg = f"⏸ Модуль <code>{mod_name}</code> выключен."

        await self.db.set(_DB_OWN, "disabled_modules", disabled)
        await event.message.edit(msg, parse_mode="html")

    @command("clearmodule", required=OWNER)
    async def clearmodule_cmd(self, event) -> None:
        """.clearmodule <модуль> — очистить данные модуля из базы."""
        mod_name = self.get_args(event).strip()
        if not mod_name:
            await event.message.edit(
                "Использование: <code>.clearmodule &lt;модуль&gt;</code>", parse_mode="html"
            )
            return

        # Try to find the db key used by the module (kitsune.<modname>)
        possible_keys = [
            f"kitsune.{mod_name.lower()}",
            f"kitsune.config.{mod_name.lower()}",
        ]
        cleared = []
        for k in possible_keys:
            data = self.db._data.get(k)
            if data is not None:
                del self.db._data[k]
                cleared.append(k)

        if cleared:
            await self.db.force_save()
            await event.message.edit(
                f"✅ Очищены данные: {', '.join(f'<code>{k}</code>' for k in cleared)}",
                parse_mode="html",
            )
        else:
            await event.message.edit(
                f"ℹ️ Данных для модуля <code>{mod_name}</code> не найдено.",
                parse_mode="html",
            )
