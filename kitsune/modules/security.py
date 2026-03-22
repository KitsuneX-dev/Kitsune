from __future__ import annotations

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

class SecurityModule(KitsuneModule):
    name        = "security"
    description = "Управление правами доступа"
    author      = "Yushi"

    _DB_KEY = "kitsune.security"

    strings_ru = {
        "sudo_added":    "✅ <code>{uid}</code> добавлен в sudo.",
        "sudo_removed":  "✅ <code>{uid}</code> удалён из sudo.",
        "owner_added":   "✅ <code>{uid}</code> добавлен в совладельцы.\n⚠️ Он сможет выполнять команды бота от твоего лица.",
        "owner_removed": "✅ <code>{uid}</code> удалён из совладельцев.",
        "owner_list":    "👥 <b>Совладельцы:</b>\n{users}",
        "no_user":       "❌ Укажи ID или ответь на сообщение пользователя.",
        "no_self":       "❌ Нельзя добавить самого себя.",
        "not_in_list":   "❌ Пользователь не найден в списке.",
        "host_protected":"❌ Нельзя удалить основного владельца.",
        "empty":         "Список пуст.",
    }

    def _get_security(self):
        return getattr(self.client, "_kitsune_security", None)

    async def _resolve_user(self, event) -> int | None:
        parts = event.message.text.split(maxsplit=1)
        if len(parts) > 1:
            try:
                return int(parts[1].strip())
            except ValueError:
                pass
        if event.message.reply_to_msg_id:
            msg = await event.message.get_reply_message()
            if msg:
                return msg.sender_id
        return None

    def _get_co_owners(self) -> list[int]:
        return list(self.db.get(self._DB_KEY, "co_owners", []))

    async def _set_co_owners(self, owners: list[int]) -> None:
        await self.db.set(self._DB_KEY, "co_owners", owners)

    @command("owneradd", required=OWNER)
    async def owneradd_cmd(self, event) -> None:
        if event.sender_id != self.client.tg_id:
            return
        uid = await self._resolve_user(event)
        if uid is None:
            await event.reply(self.strings("no_user"), parse_mode="html")
            return
        if uid == self.client.tg_id:
            await event.reply(self.strings("no_self"), parse_mode="html")
            return
        owners = self._get_co_owners()
        if uid not in owners:
            owners.append(uid)
            await self._set_co_owners(owners)
        await event.reply(self.strings("owner_added").format(uid=uid), parse_mode="html")

    @command("ownerrm", required=OWNER)
    async def ownerrm_cmd(self, event) -> None:
        if event.sender_id != self.client.tg_id:
            return
        uid = await self._resolve_user(event)
        if uid is None:
            await event.reply(self.strings("no_user"), parse_mode="html")
            return
        if uid == self.client.tg_id:
            await event.reply(self.strings("host_protected"), parse_mode="html")
            return
        owners = self._get_co_owners()
        if uid not in owners:
            await event.reply(self.strings("not_in_list"), parse_mode="html")
            return
        owners.remove(uid)
        await self._set_co_owners(owners)
        await event.reply(self.strings("owner_removed").format(uid=uid), parse_mode="html")

    @command("ownerlist", required=OWNER)
    async def ownerlist_cmd(self, event) -> None:
        owners = self._get_co_owners()
        if owners:
            users = "\n".join(f"  • <code>{u}</code>" for u in owners)
        else:
            users = self.strings("empty")
        await event.reply(self.strings("owner_list").format(users=users), parse_mode="html")

    @command("addsudo", required=OWNER)
    async def addsudo_cmd(self, event) -> None:
        uid = await self._resolve_user(event)
        if uid is None:
            await event.reply(self.strings("no_user"), parse_mode="html")
            return
        sec = self._get_security()
        if sec:
            await sec.add_sudo(uid)
        await event.reply(self.strings("sudo_added").format(uid=uid), parse_mode="html")

    @command("delsudo", required=OWNER)
    async def delsudo_cmd(self, event) -> None:
        uid = await self._resolve_user(event)
        if uid is None:
            await event.reply(self.strings("no_user"), parse_mode="html")
            return
        sec = self._get_security()
        if sec:
            await sec.remove_sudo(uid)
        await event.reply(self.strings("sudo_added").format(uid=uid), parse_mode="html")

    @command("sudolist", required=OWNER)
    async def sudolist_cmd(self, event) -> None:
        sec = self._get_security()
        users = sec.get_sudo_users() if sec else []
        if users:
            text = "👥 <b>Sudo-пользователи:</b>\n" + "\n".join(f"  • <code>{u}</code>" for u in users)
        else:
            text = "👥 <b>Sudo-пользователи:</b>\n" + self.strings("empty")
        await event.reply(text, parse_mode="html")
