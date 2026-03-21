
from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

class SecurityModule(KitsuneModule):
    name        = "security"
    description = "Управление правами доступа"
    author      = "Yushi"

    strings_ru = {
        "added":    "✅ Пользователь <code>{uid}</code> добавлен в sudo.",
        "removed":  "✅ Пользователь <code>{uid}</code> удалён из sudo.",
        "no_user":  "❌ Укажи ID или ответь на сообщение пользователя.",
        "list":     "👥 <b>Sudo-пользователи:</b>\n{users}",
        "empty":    "Список пуст.",
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

    @command("addsudo", required=OWNER)
    async def addsudo_cmd(self, event) -> None:
        uid = await self._resolve_user(event)
        if uid is None:
            await event.reply(self.strings("no_user"), parse_mode="html")
            return
        sec = self._get_security()
        if sec:
            await sec.add_sudo(uid)
        await event.reply(self.strings("added").format(uid=uid), parse_mode="html")

    @command("delsudo", required=OWNER)
    async def delsudo_cmd(self, event) -> None:
        uid = await self._resolve_user(event)
        if uid is None:
            await event.reply(self.strings("no_user"), parse_mode="html")
            return
        sec = self._get_security()
        if sec:
            await sec.remove_sudo(uid)
        await event.reply(self.strings("removed").format(uid=uid), parse_mode="html")

    @command("sudolist", required=OWNER)
    async def sudolist_cmd(self, event) -> None:
        sec = self._get_security()
        users = sec.get_sudo_users() if sec else []
        if users:
            text = self.strings("list").format(
                users="\n".join(f"  • <code>{u}</code>" for u in users)
            )
        else:
            text = self.strings("list").format(users=self.strings("empty"))
        await event.reply(text, parse_mode="html")
