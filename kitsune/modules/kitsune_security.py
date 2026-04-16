from __future__ import annotations

import asyncio
import contextlib
import datetime
import time
import typing

from telethon.utils import get_display_name

from ..core.loader import KitsuneModule, command
from ..core.security import (
    OWNER, SUDO, EVERYONE, GROUP_ADMIN, GROUP_ADMIN_ADD_ADMINS,
    GROUP_ADMIN_BAN_USERS, GROUP_ADMIN_CHANGE_INFO, GROUP_ADMIN_DELETE_MSGS,
    GROUP_ADMIN_INVITE_USERS, GROUP_ADMIN_PIN_MESSAGES, GROUP_MEMBER,
    GROUP_OWNER, PM,
)

_DB_OWNER = "kitsune.security"
_CONFIRM_TTL = 60

def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _fmt_abs(ts: float) -> str:
    if not ts:
        return "навсегда"
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

def _fmt_dur(secs: int) -> str:
    if not secs or secs < 0:
        return "навсегда"
    if secs >= 86400:
        return f"{secs // 86400} д"
    if secs >= 3600:
        return f"{secs // 3600} ч"
    if secs >= 60:
        return f"{secs // 60} мин"
    return f"{secs} с"

def _parse_time(args: list[str]) -> int:
    for suffix, mult in [("d", 86400), ("h", 3600), ("m", 60), ("s", 1)]:
        for arg in args:
            if arg.endswith(suffix) and arg[:-1].isdigit():
                return int(arg[:-1]) * mult
    return 0

class SecurityModule(KitsuneModule):

    name        = "KitsuneSecurity"
    description = "Безопасность и права доступа"
    author      = "@Mikasu32"
    version     = "1.0"
    _builtin    = True

    strings_ru = {
        "no_user":         "❌ Укажи пользователя (аргумент или ответ на сообщение).",
        "not_a_user":      "❌ Это не пользователь.",
        "self":            "❌ Нельзя применить к себе.",
        "user_not_found":  "❌ Пользователь не найден.",
        "no_args":         "❌ Нет аргументов.",
        "no_inline":       "❌ Inline-менеджер недоступен. Настрой бота через <code>.setbot</code>",
        "sudo_added":      "✅ <a href=\"tg://user?id={uid}\">{name}</a> добавлен в судо.",
        "sudo_removed":    "✅ <a href=\"tg://user?id={uid}\">{name}</a> удалён из судо.",
        "sudo_already":    "ℹ️ Уже в судо.",
        "sudo_not_in":     "ℹ️ Не в судо.",
        "sudo_list":       "👥 <b>Список судо:</b>\n{list}",
        "sudo_empty":      "ℹ️ Список судо пуст.",
        "coowner_added":   "✅ <a href=\"tg://user?id={uid}\">{name}</a> добавлен как co-owner.",
        "coowner_removed": "✅ <a href=\"tg://user?id={uid}\">{name}</a> удалён из co-owner.",
        "coowner_already": "ℹ️ Уже co-owner.",
        "coowner_not_in":  "ℹ️ Не является co-owner.",
        "coowner_list":    "👑 <b>Co-owner'ы:</b>\n{list}",
        "coowner_empty":   "ℹ️ Список co-owner'ов пуст.",
        "rule_added":      "✅ Правило добавлено:\n{text}",
        "no_rules":        "ℹ️ Правил нет.",
        "rules_list":      "🛡 <b>Временные правила:</b>\n{list}",
        "security_info":   (
            "🛡 <b>Безопасность Kitsune</b>\n\n"
            "Судо-пользователи: <b>{sudo_count}</b>\n"
            "Co-owner'ы: <b>{coowner_count}</b>\n\n"
            "Команды:\n"
            "<code>.owneradd</code> / <code>.ownerrm</code> / <code>.ownerlist</code> — управление co-owner\n"
            "<code>.sudoadd</code> / <code>.sudorm</code> / <code>.sudolist</code> — управление sudo\n"
            "<code>.security</code> — эта справка"
        ),
    }

    def _inline(self):
        return getattr(self.client, "_kitsune_inline", None)

    async def _resolve_user(self, event):
        args = self.get_args(event).strip()
        if args:
            ent = args.lstrip("@")
            try:
                ent = int(ent)
            except ValueError:
                pass
            try:
                return await self.client.get_entity(ent)
            except Exception:
                pass
        reply = await event.message.get_reply_message()
        if reply and reply.sender_id:
            try:
                return await self.client.get_entity(reply.sender_id)
            except Exception:
                pass
        return None

    @command("owneradd", required=OWNER)
    async def owneradd_cmd(self, event) -> None:
        inline = self._inline()
        if not inline or not inline._bot:
            await event.message.edit(self.strings("no_inline"), parse_mode="html")
            return

        user = await self._resolve_user(event)
        if not user:
            await event.message.edit(self.strings("no_user"), parse_mode="html")
            return
        if user.id == self.tg_id:
            await event.message.edit(self.strings("self"), parse_mode="html")
            return

        owners = self.db.get(_DB_OWNER, "co_owners", [])
        if user.id in owners:
            await event.message.edit(self.strings("coowner_already"), parse_mode="html")
            return

        uid  = user.id
        name = _esc(get_display_name(user))

        text = (
            "⚠️ <b>Выдача прав владельца</b>\n\n"
            f"👤 Пользователь: <b>{name}</b>\n"
            f"🆔 ID: <code>{uid}</code>\n\n"
            f"Он получит <b>полный доступ</b> ко всем командам бота.\n"
            f"Подтвердить?"
        )

        markup = [
            [
                {"text": "✅ Выдать доступ", "callback": self._cb_owneradd_yes, "args": (uid, name)},
                {"text": "❌ Отмена",        "callback": self._cb_owneradd_no},
            ]
        ]

        await event.message.edit("⏳", parse_mode="html")
        await inline.form(text, event.message, markup)

    async def _cb_owneradd_yes(self, call, uid: int, name: str) -> None:
        owners = self.db.get(_DB_OWNER, "co_owners", [])
        if uid not in owners:
            owners.append(uid)
            await self.db.set(_DB_OWNER, "co_owners", owners)
        inline = self._inline()
        if inline:
            await inline.edit(
                call,
                f"✅ <a href=\"tg://user?id={uid}\">{name}</a> теперь co-owner. Полный доступ выдан.",
            )
        await call.answer("✅ Доступ выдан")

    async def _cb_owneradd_no(self, call) -> None:
        inline = self._inline()
        if inline:
            await inline.edit(call, "❌ Действие отменено. Права не выданы.")
        await call.answer("❌ Отменено")

    @command("ownerrm", required=OWNER)
    async def ownerrm_cmd(self, event) -> None:
        inline = self._inline()
        if not inline or not inline._bot:
            await event.message.edit(self.strings("no_inline"), parse_mode="html")
            return

        user = await self._resolve_user(event)
        if not user:
            await event.message.edit(self.strings("no_user"), parse_mode="html")
            return

        owners = self.db.get(_DB_OWNER, "co_owners", [])
        if user.id not in owners:
            await event.message.edit(self.strings("coowner_not_in"), parse_mode="html")
            return

        uid  = user.id
        name = _esc(get_display_name(user))

        text = (
            "❗ <b>Удаление владельца</b>\n\n"
            f"👤 Пользователь: <b>{name}</b>\n"
            f"🆔 ID: <code>{uid}</code>\n\n"
            f"После удаления он потеряет доступ ко всем командам и модулям.\n"
            f"Продолжить?"
        )

        markup = [
            [
                {"text": "✅ Подтвердить", "callback": self._cb_ownerrm_yes, "args": (uid, name)},
                {"text": "❌ Отмена",      "callback": self._cb_ownerrm_no},
            ]
        ]

        await event.message.edit("⏳", parse_mode="html")
        await inline.form(text, event.message, markup)

    async def _cb_ownerrm_yes(self, call, uid: int, name: str) -> None:
        owners = self.db.get(_DB_OWNER, "co_owners", [])
        if uid in owners:
            owners.remove(uid)
            await self.db.set(_DB_OWNER, "co_owners", owners)
        inline = self._inline()
        if inline:
            await inline.edit(
                call,
                f"✅ <a href=\"tg://user?id={uid}\">{name}</a> удалён из co-owner.",
            )
        await call.answer("✅ Удалено")

    async def _cb_ownerrm_no(self, call) -> None:
        inline = self._inline()
        if inline:
            await inline.edit(call, "❌ Действие отменено. Пользователь остался в списке.")
        await call.answer("❌ Отменено")

    @command("ownerlist", required=OWNER)
    async def ownerlist_cmd(self, event) -> None:
        owners = self.db.get(_DB_OWNER, "co_owners", [])
        if not owners:
            await event.message.edit(self.strings("coowner_empty"), parse_mode="html")
            return
        lines = []
        for uid in owners:
            with contextlib.suppress(Exception):
                u = await self.client.get_entity(uid)
                lines.append(f'▫️ <a href="tg://user?id={uid}">{_esc(get_display_name(u))}</a>')
        await event.message.edit(
            self.strings("coowner_list").format(list="\n".join(lines) or "—"),
            parse_mode="html",
        )

    @command("sudoadd", required=OWNER)
    async def sudoadd_cmd(self, event) -> None:
        user = await self._resolve_user(event)
        if not user:
            await event.message.edit(self.strings("no_user"), parse_mode="html")
            return
        if user.id == self.tg_id:
            await event.message.edit(self.strings("self"), parse_mode="html")
            return
        sudo = self.db.get(_DB_OWNER, "sudo", [])
        if user.id in sudo:
            await event.message.edit(self.strings("sudo_already"), parse_mode="html")
            return
        sudo.append(user.id)
        await self.db.set(_DB_OWNER, "sudo", sudo)
        await event.message.edit(
            self.strings("sudo_added").format(uid=user.id, name=_esc(get_display_name(user))),
            parse_mode="html",
        )

    @command("sudorm", required=OWNER)
    async def sudorm_cmd(self, event) -> None:
        user = await self._resolve_user(event)
        if not user:
            await event.message.edit(self.strings("no_user"), parse_mode="html")
            return
        sudo = self.db.get(_DB_OWNER, "sudo", [])
        if user.id not in sudo:
            await event.message.edit(self.strings("sudo_not_in"), parse_mode="html")
            return
        sudo.remove(user.id)
        await self.db.set(_DB_OWNER, "sudo", sudo)
        await event.message.edit(
            self.strings("sudo_removed").format(uid=user.id, name=_esc(get_display_name(user))),
            parse_mode="html",
        )

    @command("sudolist", required=OWNER)
    async def sudolist_cmd(self, event) -> None:
        sudo = self.db.get(_DB_OWNER, "sudo", [])
        if not sudo:
            await event.message.edit(self.strings("sudo_empty"), parse_mode="html")
            return
        lines = []
        for uid in sudo:
            with contextlib.suppress(Exception):
                u = await self.client.get_entity(uid)
                lines.append(f'▫️ <a href="tg://user?id={uid}">{_esc(get_display_name(u))}</a>')
        await event.message.edit(
            self.strings("sudo_list").format(list="\n".join(lines) or "—"),
            parse_mode="html",
        )

    @command("blacklist", required=OWNER)
    async def blacklist_cmd(self, event) -> None:
        chat_id = event.message.chat_id
        bl = self.db.get(_DB_OWNER, "blacklist_chats", [])
        if chat_id not in bl:
            bl.append(chat_id)
            await self.db.set(_DB_OWNER, "blacklist_chats", bl)
        await event.message.edit(f"🚫 Чат <code>{chat_id}</code> в чёрном списке.", parse_mode="html")

    @command("unblacklist", required=OWNER)
    async def unblacklist_cmd(self, event) -> None:
        chat_id = event.message.chat_id
        bl = self.db.get(_DB_OWNER, "blacklist_chats", [])
        if chat_id in bl:
            bl.remove(chat_id)
            await self.db.set(_DB_OWNER, "blacklist_chats", bl)
        await event.message.edit(f"✅ Чат <code>{chat_id}</code> убран из чёрного списка.", parse_mode="html")

    @command("blacklistuser", required=OWNER)
    async def blacklistuser_cmd(self, event) -> None:
        user = await self._resolve_user(event)
        if not user:
            await event.message.edit(self.strings("no_user"), parse_mode="html")
            return
        bl = self.db.get(_DB_OWNER, "blacklist_users", [])
        if user.id not in bl:
            bl.append(user.id)
            await self.db.set(_DB_OWNER, "blacklist_users", bl)
        await event.message.edit(
            f"🚫 <a href=\"tg://user?id={user.id}\">{_esc(get_display_name(user))}</a> в чёрном списке.",
            parse_mode="html",
        )

    @command("unblacklistuser", required=OWNER)
    async def unblacklistuser_cmd(self, event) -> None:
        user = await self._resolve_user(event)
        if not user:
            await event.message.edit(self.strings("no_user"), parse_mode="html")
            return
        bl = self.db.get(_DB_OWNER, "blacklist_users", [])
        if user.id in bl:
            bl.remove(user.id)
            await self.db.set(_DB_OWNER, "blacklist_users", bl)
        await event.message.edit(
            f"✅ <a href=\"tg://user?id={user.id}\">{_esc(get_display_name(user))}</a> убран из чёрного списка.",
            parse_mode="html",
        )

    @command("tsec", required=OWNER)
    async def tsec_cmd(self, event) -> None:
        args = self.get_args(event).split()
        if not args:
            rules = self.db.get(_DB_OWNER, "tsec_rules", [])
            now = time.time()
            active = [r for r in rules if r["expires"] > now]
            await self.db.set(_DB_OWNER, "tsec_rules", active)
            if not active:
                await event.message.edit(self.strings("no_rules"), parse_mode="html")
                return
            lines = []
            for r in active:
                left = _fmt_dur(int(r["expires"] - now))
                lines.append(
                    f"▫️ <a href=\"tg://user?id={r['uid']}\">{_esc(r['name'])}</a>"
                    f" → <code>{r['cmd']}</code> (осталось {left})"
                )
            await event.message.edit(
                self.strings("rules_list").format(list="\n".join(lines)),
                parse_mode="html",
            )
            return
        if len(args) < 2:
            await event.message.edit(
                "Использование: <code>.tsec @user команда [1h/30m/...]</code>",
                parse_mode="html",
            )
            return
        target_raw = args[0].lstrip("@")
        try:
            target_raw = int(target_raw)
        except ValueError:
            pass
        try:
            user = await self.client.get_entity(target_raw)
        except Exception:
            await event.message.edit(self.strings("user_not_found"), parse_mode="html")
            return
        cmd = args[1].lower()
        duration = _parse_time(args[2:]) if len(args) > 2 else 3600
        expires = time.time() + duration
        rules = self.db.get(_DB_OWNER, "tsec_rules", [])
        rules.append({"uid": user.id, "name": get_display_name(user), "cmd": cmd, "expires": expires})
        await self.db.set(_DB_OWNER, "tsec_rules", rules)
        await event.message.edit(
            self.strings("rule_added").format(
                text=f'<a href="tg://user?id={user.id}">{_esc(get_display_name(user))}</a>'
                     f' → <code>{cmd}</code> на <b>{_fmt_dur(duration)}</b>'
            ),
            parse_mode="html",
        )

    @command("tsecrm", required=OWNER)
    async def tsecrm_cmd(self, event) -> None:
        args = self.get_args(event).split()
        if len(args) < 2:
            await event.message.edit("Использование: <code>.tsecrm @user команда</code>", parse_mode="html")
            return
        target_raw = args[0].lstrip("@")
        try:
            target_raw = int(target_raw)
        except ValueError:
            pass
        try:
            user = await self.client.get_entity(target_raw)
        except Exception:
            await event.message.edit(self.strings("user_not_found"), parse_mode="html")
            return
        cmd = args[1].lower()
        rules = self.db.get(_DB_OWNER, "tsec_rules", [])
        before = len(rules)
        rules = [r for r in rules if not (r["uid"] == user.id and r["cmd"] == cmd)]
        await self.db.set(_DB_OWNER, "tsec_rules", rules)
        await event.message.edit(
            "✅ Правило удалено." if len(rules) < before else "ℹ️ Правило не найдено.",
            parse_mode="html",
        )

    @command("tsecclr", required=OWNER)
    async def tsecclr_cmd(self, event) -> None:
        await self.db.set(_DB_OWNER, "tsec_rules", [])
        await event.message.edit("✅ Все временные правила удалены.", parse_mode="html")

    @command("security", required=OWNER)
    async def security_cmd(self, event) -> None:
        sudo = self.db.get(_DB_OWNER, "sudo", [])
        owners = self.db.get(_DB_OWNER, "co_owners", [])
        await event.message.edit(
            self.strings("security_info").format(sudo_count=len(sudo), coowner_count=len(owners)),
            parse_mode="html",
        )

    @command("inlinesec", required=OWNER)
    async def inlinesec_cmd(self, event) -> None:
        await event.message.edit(
            "ℹ️ В Kitsune inline-хендлеры не используются, команда недоступна.",
            parse_mode="html",
        )

    @command("querysec", required=OWNER)
    async def querysec_cmd(self, event) -> None:
        await event.message.edit(
            "ℹ️ В Kitsune inline-хендлеры не используются, команда недоступна.",
            parse_mode="html",
        )
