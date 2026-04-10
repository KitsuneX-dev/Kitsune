from __future__ import annotations

import contextlib
import logging

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER, SUDO

logger = logging.getLogger(__name__)

_DB_KEY = "kitsune.security"

class SecurityModule(KitsuneModule):
    name        = "security"
    description = "Access rights management"
    author      = "Yushi"
    version     = "2.0"
    icon        = "🛡"
    category    = "system"

    strings_ru = {
        "sudo_added":     "✅ <code>{name}</code> (<code>{uid}</code>) добавлен в sudo.\n\nТеперь он может выполнять команды с уровнем доступа <b>sudo</b>.",
        "sudo_removed":   "✅ <code>{name}</code> (<code>{uid}</code>) удалён из sudo.",
        "sudo_list":      "🛡 <b>Sudo-пользователи:</b>\n\n{users}",
        "sudo_list_empty":"🛡 <b>Sudo-пользователи:</b>\n\n<i>Список пуст</i>",
        "owner_added":    "✅ <code>{name}</code> (<code>{uid}</code>) добавлен в совладельцы.\n\n⚠️ Он получит <b>полный доступ</b> ко всем командам бота.",
        "owner_removed":  "✅ <code>{name}</code> (<code>{uid}</code>) удалён из совладельцев.",
        "owner_list":     "👑 <b>Совладельцы:</b>\n\n{users}",
        "owner_list_empty":"👑 <b>Совладельцы:</b>\n\n<i>Список пуст</i>",
        "no_user":        "❌ Укажи ID или ответь на сообщение пользователя.",
        "no_self":        "❌ Нельзя изменить права самого себя.",
        "not_in_list":    "❌ Пользователь не найден в списке.",
        "host_protected": "❌ Нельзя удалить основного владельца.",
        "confirm_owner":  (
            "⚠️ <b>Добавление совладельца</b>\n\n"
            "👤 Пользователь: {name}\n"
            "🆔 ID: <code>{uid}</code>\n\n"
            "Он получит <b>полный доступ</b> ко всем командам бота.\n"
            "Подтвердить?"
        ),
        "cancelled":      "❌ Отменено.",
        "perms_header":   "🛡 <b>Права пользователя</b> <code>{uid}</code>:\n\n",
        "perm_owner":     "👑 Владелец",
        "perm_sudo":      "🛡 Sudo",
        "perm_none":      "👤 Обычный пользователь",
    }

    async def on_load(self) -> None:
        from telethon import events
        self.client.add_event_handler(
            self._owneradd_callback,
            events.CallbackQuery(pattern=b"kitsunesec_owneradd_")
        )

    async def on_unload(self) -> None:
        from telethon import events
        with contextlib.suppress(Exception):
            self.client.remove_event_handler(
                self._owneradd_callback,
                events.CallbackQuery(pattern=b"kitsunesec_owneradd_")
            )

    def _sec(self):
        return getattr(self.client, "_kitsune_security", None)

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

        from telethon import Button
        await event.edit(
            self.strings("confirm_owner").format(name=name, uid=uid),
            parse_mode="html",
            buttons=[
                [
                    Button.inline("✅ Подтвердить", data=f"kitsunesec_owneradd_yes:{uid}"),
                    Button.inline("❌ Отмена",      data=f"kitsunesec_owneradd_no:{uid}"),
                ]
            ],
        )

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

        owners.remove(uid)
        await self._set_co_owners(owners)
        await event.edit(
            self.strings("owner_removed").format(name=name, uid=uid),
            parse_mode="html",
        )

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

        sec = self._sec()
        sudo_users  = sec.get_sudo_users() if sec else []
        co_owners   = self._get_co_owners()

        if uid == self.client.tg_id or uid in co_owners:
            role = self.strings("perm_owner")
        elif uid in sudo_users:
            role = self.strings("perm_sudo")
        else:
            role = self.strings("perm_none")

        text = self.strings("perms_header").format(uid=uid) + role
        await event.edit(text, parse_mode="html")

    async def _owneradd_callback(self, event) -> None:
        with contextlib.suppress(Exception):
            data = event.data.decode()
        if not data:
            return
        if event.query.user_id != self.client.tg_id:
            await event.answer("🔒 Нет доступа.", alert=True)
            return

        action, uid_str = data.split(":", 1)
        uid = int(uid_str)
        await event.answer()

        if "no" in action:
            await event.edit(self.strings("cancelled"))
            return

        owners = self._get_co_owners()
        if uid not in owners:
            owners.append(uid)
            await self._set_co_owners(owners)

        try:
            user = await self.client.get_entity(uid)
            name = getattr(user, "first_name", str(uid)) or str(uid)
        except Exception:
            name = str(uid)

        await event.edit(
            self.strings("owner_added").format(name=name, uid=uid),
            parse_mode="html",
        )
