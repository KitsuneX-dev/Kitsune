from __future__ import annotations

import asyncio
import contextlib
import logging

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER, SUDO

logger = logging.getLogger(__name__)

_DB_KEY  = "kitsune.security"
_TTL     = 60  

class SecurityModule(KitsuneModule):
    name        = "security"
    description = "Access rights management"
    author      = "Yushi"
    version     = "2.1"
    icon        = "🛡"
    category    = "system"

    strings_ru = {
        "sudo_added":       "✅ <code>{name}</code> (<code>{uid}</code>) добавлен в sudo.\n\nТеперь он может выполнять команды с уровнем доступа <b>sudo</b>.",
        "sudo_removed":     "✅ <code>{name}</code> (<code>{uid}</code>) удалён из sudo.",
        "sudo_list":        "🛡 <b>Sudo-пользователи:</b>\n\n{users}",
        "sudo_list_empty":  "🛡 <b>Sudo-пользователи:</b>\n\n<i>Список пуст</i>",
        "owner_added":      "✅ <code>{name}</code> (<code>{uid}</code>) добавлен в совладельцы.\n\n⚠️ Он получит <b>полный доступ</b> ко всем командам бота.",
        "owner_removed":    "✅ <code>{name}</code> (<code>{uid}</code>) удалён из совладельцев.",
        "owner_list":       "👑 <b>Совладельцы:</b>\n\n{users}",
        "owner_list_empty": "👑 <b>Совладельцы:</b>\n\n<i>Список пуст</i>",
        "no_user":          "❌ Укажи ID или ответь на сообщение пользователя.",
        "no_self":          "❌ Нельзя изменить права самого себя.",
        "not_in_list":      "❌ Пользователь не найден в списке.",
        "host_protected":   "❌ Нельзя удалить основного владельца.",
        "confirm_owner": (
            "⚠️ <b>Добавление совладельца</b>\n\n"
            "👤 Пользователь: {name}\n"
            "🆔 ID: <code>{uid}</code>\n\n"
            "Он получит <b>полный доступ</b> ко всем командам бота.\n"
            "Подтвердить?"
        ),
        "confirm_ownerrm": (
            "❗ <b>Удаление совладельца</b>\n\n"
            "👤 Пользователь: {name}\n"
            "🆔 ID: <code>{uid}</code>\n\n"
            "Он потеряет доступ ко всем командам бота.\n"
            "Подтвердить?"
        ),
        "cancelled":    "❌ Отменено.",
        "timeout":      "⏱ Время вышло. Действие отменено.",
        "perms_header": "🛡 <b>Права пользователя</b> <code>{uid}</code>:\n\n",
        "perm_owner":   "👑 Владелец",
        "perm_sudo":    "🛡 Sudo",
        "perm_none":    "👤 Обычный пользователь",
    }

    def _sec(self):
        return getattr(self.client, "_kitsune_security", None)

    def _inline(self):
        return getattr(self.client, "_kitsune_inline", None)

    async def _resolve_user(self, event) -> tuple[int | None, str]:
        args = self.get_args(event)
        if args:
            try:
                uid = int(args.strip())
                try:
                    user = await self.client.get_entity(uid)
                    name = getattr(user, "first_name", str(uid)) or str(uid)
                except Exception:
                    name = str(uid)
                return uid, name
            except ValueError:
                try:
                    user = await self.client.get_entity(args.strip())
                    name = getattr(user, "first_name", args) or args
                    return user.id, name
                except Exception:
                    pass

        if event.message.reply_to_msg_id:
            msg = await event.message.get_reply_message()
            if msg and msg.sender_id:
                try:
                    user = await self.client.get_entity(msg.sender_id)
                    name = getattr(user, "first_name", str(msg.sender_id)) or str(msg.sender_id)
                except Exception:
                    name = str(msg.sender_id)
                return msg.sender_id, name

        return None, ""

    def _get_co_owners(self) -> list[int]:
        return list(self.db.get(_DB_KEY, "co_owners", []))

    async def _set_co_owners(self, owners: list[int]) -> None:
        await self.db.set(_DB_KEY, "co_owners", owners)

    @command("addsudo", required=OWNER)
    async def addsudo_cmd(self, event) -> None:
        uid, name = await self._resolve_user(event)
        if uid is None:
            await event.edit(self.strings("no_user"), parse_mode="html")
            return
        if uid == self.client.tg_id:
            await event.edit(self.strings("no_self"), parse_mode="html")
            return

        sec = self._sec()
        if sec:
            await sec.add_sudo(uid)

        await event.edit(
            self.strings("sudo_added").format(name=name, uid=uid),
            parse_mode="html",
        )

    @command("delsudo", required=OWNER)
    async def delsudo_cmd(self, event) -> None:
        uid, name = await self._resolve_user(event)
        if uid is None:
            await event.edit(self.strings("no_user"), parse_mode="html")
            return
        if uid == self.client.tg_id:
            await event.edit(self.strings("no_self"), parse_mode="html")
            return

        sec = self._sec()
        if sec:
            users = sec.get_sudo_users()
            if uid not in users:
                await event.edit(self.strings("not_in_list"), parse_mode="html")
                return
            await sec.remove_sudo(uid)

        await event.edit(
            self.strings("sudo_removed").format(name=name, uid=uid),
            parse_mode="html",
        )

    @command("sudolist", required=OWNER)
    async def sudolist_cmd(self, event) -> None:
        sec = self._sec()
        uids = sec.get_sudo_users() if sec else []

        if not uids:
            await event.edit(self.strings("sudo_list_empty"), parse_mode="html")
            return

        lines = []
        for uid in uids:
            try:
                user = await self.client.get_entity(uid)
                name = getattr(user, "first_name", str(uid)) or str(uid)
                username = f" @{user.username}" if getattr(user, "username", None) else ""
                lines.append(f"  • {name}{username} — <code>{uid}</code>")
            except Exception:
                lines.append(f"  • <code>{uid}</code>")

        await event.edit(
            self.strings("sudo_list").format(users="\n".join(lines)),
            parse_mode="html",
        )

    @command("owneradd", required=OWNER)
    async def owneradd_cmd(self, event) -> None:
        if event.sender_id != self.client.tg_id:
            return

        uid, name = await self._resolve_user(event)
        if uid is None:
            await event.edit(self.strings("no_user"), parse_mode="html")
            return
        if uid == self.client.tg_id:
            await event.edit(self.strings("no_self"), parse_mode="html")
            return

        owners = self._get_co_owners()
        if uid in owners:
            await event.edit("ℹ️ Уже является совладельцем.", parse_mode="html")
            return

        text   = self.strings("confirm_owner").format(name=name, uid=uid)
        inline = self._inline()

        if inline:
            markup = [
                [
                    {"text": "✅ Подтвердить", "callback": self._cb_owneradd_yes, "args": (uid, name)},
                    {"text": "❌ Отмена",      "callback": self._cb_owneradd_no},
                ]
            ]
            msg = await inline.form(text, event.message, markup)
            asyncio.ensure_future(self._owneradd_timeout(msg, uid))
        else:

            owners.append(uid)
            await self._set_co_owners(owners)
            await event.edit(
                self.strings("owner_added").format(name=name, uid=uid),
                parse_mode="html",
            )

    async def _cb_owneradd_yes(self, call, uid: int, name: str) -> None:
        owners = self._get_co_owners()
        if uid not in owners:
            owners.append(uid)
            await self._set_co_owners(owners)
        inline = self._inline()
        if inline:
            await inline.edit(call, self.strings("owner_added").format(name=name, uid=uid))
        await call.answer("✅ Выдано")

    async def _cb_owneradd_no(self, call) -> None:
        inline = self._inline()
        if inline:
            await inline.edit(call, self.strings("cancelled"))
        await call.answer("❌ Отменено")

    async def _owneradd_timeout(self, msg, uid: int) -> None:
        await asyncio.sleep(_TTL)
        owners = self._get_co_owners()
        if uid not in owners:
            inline = self._inline()
            if inline and msg:
                with contextlib.suppress(Exception):
                    await inline.edit(msg, self.strings("timeout"))

    @command("ownerrm", required=OWNER)
    async def ownerrm_cmd(self, event) -> None:
        if event.sender_id != self.client.tg_id:
            return

        uid, name = await self._resolve_user(event)
        if uid is None:
            await event.edit(self.strings("no_user"), parse_mode="html")
            return
        if uid == self.client.tg_id:
            await event.edit(self.strings("host_protected"), parse_mode="html")
            return

        owners = self._get_co_owners()
        if uid not in owners:
            await event.edit(self.strings("not_in_list"), parse_mode="html")
            return

        text   = self.strings("confirm_ownerrm").format(name=name, uid=uid)
        inline = self._inline()

        if inline:
            markup = [
                [
                    {"text": "✅ Подтвердить", "callback": self._cb_ownerrm_yes, "args": (uid, name)},
                    {"text": "❌ Отмена",      "callback": self._cb_ownerrm_no},
                ]
            ]
            msg = await inline.form(text, event.message, markup)
            asyncio.ensure_future(self._ownerrm_timeout(msg, uid))
        else:

            owners.remove(uid)
            await self._set_co_owners(owners)
            await event.edit(
                self.strings("owner_removed").format(name=name, uid=uid),
                parse_mode="html",
            )

    async def _cb_ownerrm_yes(self, call, uid: int, name: str) -> None:
        owners = self._get_co_owners()
        if uid in owners:
            owners.remove(uid)
            await self._set_co_owners(owners)
        inline = self._inline()
        if inline:
            await inline.edit(call, self.strings("owner_removed").format(name=name, uid=uid))
        await call.answer("✅ Удалено")

    async def _cb_ownerrm_no(self, call) -> None:
        inline = self._inline()
        if inline:
            await inline.edit(call, self.strings("cancelled"))
        await call.answer("❌ Отменено")

    async def _ownerrm_timeout(self, msg, uid: int) -> None:
        await asyncio.sleep(_TTL)
        owners = self._get_co_owners()
        if uid in owners:
            inline = self._inline()
            if inline and msg:
                with contextlib.suppress(Exception):
                    await inline.edit(msg, self.strings("timeout"))

    @command("ownerlist", required=OWNER)
    async def ownerlist_cmd(self, event) -> None:
        owners = self._get_co_owners()
        if not owners:
            await event.edit(self.strings("owner_list_empty"), parse_mode="html")
            return

        lines = []
        for uid in owners:
            try:
                user = await self.client.get_entity(uid)
                name = getattr(user, "first_name", str(uid)) or str(uid)
                username = f" @{user.username}" if getattr(user, "username", None) else ""
                lines.append(f"  • {name}{username} — <code>{uid}</code>")
            except Exception:
                lines.append(f"  • <code>{uid}</code>")

        await event.edit(
            self.strings("owner_list").format(users="\n".join(lines)),
            parse_mode="html",
        )

    @command("checkperms", required=OWNER)
    async def checkperms_cmd(self, event) -> None:
        uid, name = await self._resolve_user(event)
        if uid is None:
            await event.edit(self.strings("no_user"), parse_mode="html")
            return

        sec        = self._sec()
        sudo_users = sec.get_sudo_users() if sec else []
        co_owners  = self._get_co_owners()

        if uid == self.client.tg_id or uid in co_owners:
            role = self.strings("perm_owner")
        elif uid in sudo_users:
            role = self.strings("perm_sudo")
        else:
            role = self.strings("perm_none")

        await event.edit(
            self.strings("perms_header").format(uid=uid) + role,
            parse_mode="html",
        )
