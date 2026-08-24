from __future__ import annotations
import asyncio
import contextlib
import datetime
import logging
import time
from ..core.loader import KitsuneModule, command
from ..core.security import OWNER, SUDO, SecurityGroup
from ..pointers import PointerDict, NamedTupleMiddlewareDict
from .. import utils

logger = logging.getLogger(__name__)

_DB_KEY  = "kitsune.security"

_TTL     = 60

class SecurityModule(KitsuneModule):
    name        = "security"
    description = "Access rights management"
    author      = "Yushi"
    version     = "1.3.0"
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
        "no_args":      "❌ Укажи аргументы.",
        "no_target":    "❌ Не удалось определить цель. Укажи пользователя/чат или ответь на сообщение.",
        "no_rule":      "❌ Не найдено ни одной подходящей команды, модуля или inline-обработчика.",
        "no_rules":     "❌ Правил не найдено.",
        "what":         "❓ Первый аргумент должен быть <code>user</code>, <code>chat</code> или <code>sgroup</code>.",
        "owner_target": "❌ Нельзя выдавать targeted-права владельцу.",
        "chat_inline":  "❌ Inline-права нельзя выдавать чату.",
        "command":      "команду",
        "module":       "модуль",
        "inline":       "inline-команду",
        "user":         "пользователю",
        "chat":         "чату",
        "sgroup":       "группе",
        "for":          "на",
        "until":        "до",
        "forever":      "навсегда",
        "day":          "день",
        "days":         "дн.",
        "hour":         "час",
        "hours":        "ч.",
        "minute":       "минуту",
        "minutes":      "мин.",
        "second":       "секунду",
        "seconds":      "сек.",
        "confirm_rule": (
            "⚠️ <b>Выдать право?</b>\n\n"
            "🎯 <b>{}</b> <a href='{}'>{}</a>\n"
            "🛡 На <b>{}</b> <code>{}</code>\n"
            "⏳ {}\n\nПодтвердить?"
        ),
        "confirm_btn":  "✅ Подтвердить",
        "cancel_btn":   "❌ Отмена",
        "rule_added": (
            "✅ <b>Право выдано</b>\n\n"
            "🎯 <b>{}</b> <a href='{}'>{}</a>\n"
            "🛡 На <b>{}</b> <code>{}</code>\n"
            "⏳ {}"
        ),
        "rule_removed": "✅ Правило <code>{}</code> для <a href='{}'>{}</a> удалено.",
        "rules_removed": "✅ Все правила для <a href='{}'>{}</a> удалены.",
        "multiple_rules": "🛡 <b>Найдено несколько правил, выбери нужное:</b>\n\n{}",
        "rules":        "🛡 <b>Targeted-права:</b>\n\n{}",
        "no_tsec":      "🛡 Targeted-права не выданы никому.",
        "sgroups_list": "🔒 <b>Группы прав:</b>\n\n{}",
        "no_sgroups":   "🔒 Группы прав ещё не созданы.",
        "sgroup_li":    "▫️ <code>{}</code> — 👤 {} · 🛡 {}",
        "sgroup_info":  "🔒 <b>Группа</b> <code>{}</code>\n\n👤 <b>Пользователи:</b>\n{}\n\n🛡 <b>Права:</b>\n{}",
        "sgroup_not_found": "❌ Группа <code>{}</code> не найдена.",
        "sgroup_already_exists": "❌ Группа <code>{}</code> уже существует.",
        "invalid_name": "❌ Имя группы должно состоять только из букв и цифр.",
        "created_sgroup": "✅ Группа <code>{}</code> создана.",
        "deleted_sgroup": "✅ Группа <code>{}</code> удалена.",
        "no_users":     "  <i>нет</i>",
        "no_permissions": "  <i>нет</i>",
        "li":           "▫️ <a href='{}'>{}</a> (<code>{}</code>)",
        "user_added_to_sgroup": "✅ <b>{}</b> добавлен в группу <code>{}</code>.",
        "user_removed_from_sgroup": "✅ <b>{}</b> удалён из группы <code>{}</code>.",
        "user_already_in_sgroup": "ℹ️ <b>{}</b> уже в группе <code>{}</code>.",
        "user_not_in_sgroup": "❌ <b>{}</b> нет в группе <code>{}</code>.",
        "self":         "❌ Нельзя выдать право самому себе.",
    }
    def _sec(self):
        return getattr(self.client, "_kitsune_security", None)
    def _inline(self):
        return getattr(self.client, "_kitsune_inline", None)
    async def on_load(self) -> None:
        pointer = PointerDict(self.db, _DB_KEY, "sgroups", {})
        self._sgroups = NamedTupleMiddlewareDict(pointer, SecurityGroup)
        self._reload_sgroups()
    def _reload_sgroups(self) -> None:
        sec = self._sec()
        if sec is not None:
            with contextlib.suppress(Exception):
                sec.apply_sgroups(self._sgroups.todict())
    def _loader(self):
        return getattr(self.client, "_kitsune_loader", None)
    def _commands_map(self) -> dict:
        sec = self._sec()
        if sec is not None:
            return sec._commands_map()
        return {}
    def _lookup(self, needle: str) -> list[str]:
        prefix = "."
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        if dispatcher is not None:
            prefix = getattr(dispatcher, "_prefix", ".")
        needle = needle.strip()
        commands = self._commands_map()
        result: list[str] = []
        cmd = needle.lower().lstrip(prefix)
        if cmd in commands:
            result.append(f"command/{cmd}")
            module = commands[cmd]
            result.append(f"module/{type(module).__name__}")
        inline = self._inline()
        handlers = getattr(inline, "inline_handlers", {}) if inline else {}
        icmd = needle.lower().lstrip("@")
        if icmd in handlers:
            result.append(f"inline/{icmd}")
        return result
    @staticmethod
    def _extract_time(args: list) -> int:
        for suffix, quantifier in [
            ("d", 24 * 60 * 60),
            ("h", 60 * 60),
            ("m", 60),
            ("s", 1),
        ]:
            duration = next(
                (
                    int(arg.rsplit(suffix, maxsplit=1)[0])
                    for arg in args
                    if arg.endswith(suffix)
                    and arg.rsplit(suffix, maxsplit=1)[0].isdigit()
                ),
                None,
            )
            if duration is not None:
                return duration * quantifier
        return 0
    def _convert_time_abs(self, timestamp: int) -> str:
        return (
            self.strings("forever")
            if not timestamp
            else datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        )
    def _convert_time(self, duration: int) -> str:
        if not duration or duration < 0:
            return self.strings("forever")
        if duration >= 24 * 60 * 60:
            n = duration // (24 * 60 * 60)
            return f"{n} " + self.strings("days" if n > 1 else "day")
        if duration >= 60 * 60:
            n = duration // (60 * 60)
            return f"{n} " + self.strings("hours" if n > 1 else "hour")
        if duration >= 60:
            n = duration // 60
            return f"{n} " + self.strings("minutes" if n > 1 else "minute")
        return f"{duration} " + self.strings("seconds" if duration > 1 else "second")
    async def _resolve_target_entity(self, event, args: list):
        message = event.message
        is_private = getattr(message, "is_private", None)
        if is_private is None:
            is_private = (getattr(message, "chat_id", None) == getattr(message, "sender_id", None))
        if len(args) >= 2:
            token = args[1]
            with contextlib.suppress(ValueError, TypeError):
                if token.isdigit() or token.startswith("@"):
                    return await self.client.get_entity(
                        int(token) if token.isdigit() else token
                    )
        return None
    async def _tsec_user(self, event, args: list):
        message = event.message
        is_private = getattr(message, "is_private", False)
        is_reply = bool(getattr(message, "reply_to_msg_id", None))
        target = await self._resolve_target_entity(event, args)
        if target is None:
            if is_private:
                target = await self.client.get_entity(message.peer_id)
            elif is_reply:
                reply = await message.get_reply_message()
                target = await self.client.get_entity(reply.sender_id)
            else:
                await utils.answer(message, self.strings("no_target"))
                return
        sec = self._sec()
        if sec is not None and target.id in sec._owner_ids():
            await utils.answer(message, self.strings("owner_target"))
            return
        duration = self._extract_time(args)
        possible = utils.array_sum([self._lookup(arg) for arg in args[1:]])
        if not possible:
            await utils.answer(message, self.strings("no_rule"))
            return
        await self._offer_rules(event, "user", target, possible, duration)
    async def _tsec_chat(self, event, args: list):
        message = event.message
        is_private = getattr(message, "is_private", False)
        target = await self._resolve_target_entity(event, args)
        if target is None:
            if not is_private:
                target = await self.client.get_entity(message.peer_id)
            else:
                await utils.answer(message, self.strings("no_target"))
                return
        duration = self._extract_time(args)
        possible = utils.array_sum([self._lookup(arg) for arg in args[1:]])
        if not possible:
            await utils.answer(message, self.strings("no_rule"))
            return
        await self._offer_rules(event, "chat", target, possible, duration)
    async def _tsec_sgroup(self, event, args: list):
        message = event.message
        if len(args) <= 1:
            await utils.answer(message, self.strings("no_target"))
            return
        target = args[1]
        if target not in self._sgroups:
            await utils.answer(message, self.strings("sgroup_not_found").format(target))
            return
        duration = self._extract_time(args)
        possible = utils.array_sum([self._lookup(arg) for arg in args[2:]])
        if not possible:
            await utils.answer(message, self.strings("no_rule"))
            return
        await self._offer_rules(event, "sgroup", target, possible, duration)
    async def _offer_rules(self, event, target_type, target, possible, duration):
        message = event.message
        if len(possible) > 1:
            inline = self._inline()
            if inline is not None:
                markup = utils.chunks(
                    [
                        {
                            "text": "🛡 {} {}".format(
                                self.strings(rule.split("/")[0]).capitalize(),
                                rule.split("/", maxsplit=1)[1],
                            ),
                            "callback": self._cb_add_rule,
                            "args": (target_type, target, rule, duration),
                        }
                        for rule in possible
                    ],
                    3,
                )
                text = self.strings("multiple_rules").format(
                    "\n".join(
                        "🛡 <b>{}</b> <code>{}</code>".format(
                            self.strings(rule.split("/")[0]).capitalize(),
                            rule.split("/", maxsplit=1)[1],
                        )
                        for rule in possible
                    )
                )
                await inline.form(text, message, markup)
                return
        await self._confirm_rule(event, target_type, target, possible[0], duration)
    def _rule_display(self, target_type, target, rule, duration):
        is_str = isinstance(target, str)
        rt = rule.split("/", maxsplit=1)[0]
        rv = rule.split("/", maxsplit=1)[1]
        return (
            self.strings(target_type),
            utils.get_entity_url(target) if not is_str else "",
            utils.escape_html(utils.get_display_name(target) if not is_str else target),
            self.strings(rt),
            rv,
            (self.strings("for") + " " + self._convert_time(duration)) if duration else self.strings("forever"),
        )
    async def _confirm_rule(self, event, target_type, target, rule, duration):
        message = event.message
        inline = self._inline()
        disp = self._rule_display(target_type, target, rule, duration)
        text = self.strings("confirm_rule").format(disp[0], disp[1], disp[2], disp[3], disp[4], disp[5])
        if inline is not None:
            markup = [
                [
                    {"text": self.strings("confirm_btn"), "callback": self._cb_add_rule,
                     "args": (target_type, target, rule, duration)},
                    {"text": self.strings("cancel_btn"), "action": "close"},
                ]
            ]
            await inline.form(text, message, markup)
        else:
            await self._apply_rule(target_type, target, rule, duration)
            await utils.answer(message, self.strings("rule_added").format(disp[0], disp[1], disp[2], disp[3], disp[4], disp[5]))
    async def _cb_add_rule(self, call, target_type, target, rule, duration):
        if rule.startswith("inline") and target_type == "chat":
            await self._inline_edit(call, self.strings("chat_inline"))
            return
        await self._apply_rule(target_type, target, rule, duration)
        disp = self._rule_display(target_type, target, rule, duration)
        await self._inline_edit(
            call,
            self.strings("rule_added").format(disp[0], disp[1], disp[2], disp[3], disp[4], disp[5]),
        )
        with contextlib.suppress(Exception):
            await call.answer("✅")
    async def _inline_edit(self, call, text):
        inline = self._inline()
        if inline is not None:
            with contextlib.suppress(Exception):
                await inline.edit(call, text)
    async def _apply_rule(self, target_type, target, rule, duration):
        sec = self._sec()
        if target_type == "sgroup":
            group = self._sgroups[target]
            group.permissions.append(
                {
                    "target": target,
                    "rule_type": rule.split("/")[0],
                    "rule": rule.split("/", maxsplit=1)[1],
                    "expires": int(time.time() + duration) if duration else 0,
                    "entity_name": group.name,
                    "entity_url": "",
                }
            )
            self._sgroups[target] = group
            self._reload_sgroups()
        elif sec is not None:
            sec.add_rule(target_type, target, rule, duration)
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
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        if dispatcher is not None and hasattr(dispatcher, "set_co_owners"):
            await dispatcher.set_co_owners(owners)
        else:
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
    @command("tsec", required=OWNER)
    async def tsec_cmd(self, event) -> None:
        message = event.message
        args = utils.get_args(message)
        sec = self._sec()
        if not args:
            await self._show_tsec(message, sec)
            return
        if args[0] not in {"user", "chat", "sgroup"}:
            await utils.answer(message, self.strings("what"))
            return
        handler = {
            "user": self._tsec_user,
            "chat": self._tsec_chat,
            "sgroup": self._tsec_sgroup,
        }[args[0]]
        await handler(event, args)
    async def _show_tsec(self, message, sec) -> None:
        rules_list: list[str] = []
        if sec is not None:
            sec._reload_rights()
            for rule in list(sec.tsec_chat):
                rules_list.append(
                    "👥 <b><a href='{}'>{}</a> {} {} {}</b> <code>{}</code>".format(
                        rule["entity_url"],
                        utils.escape_html(rule["entity_name"]),
                        self._convert_time(int(rule["expires"] - time.time())) if rule["expires"] else self.strings("forever"),
                        self.strings("for"),
                        self.strings(rule["rule_type"]),
                        rule["rule"],
                    )
                )
            for rule in list(sec.tsec_user):
                rules_list.append(
                    "👤 <b><a href='{}'>{}</a> {} {} {}</b> <code>{}</code>".format(
                        rule["entity_url"],
                        utils.escape_html(rule["entity_name"]),
                        self._convert_time(int(rule["expires"] - time.time())) if rule["expires"] else self.strings("forever"),
                        self.strings("for"),
                        self.strings(rule["rule_type"]),
                        rule["rule"],
                    )
                )
        for _name, group in self._sgroups:
            for rule in group.permissions:
                rules_list.append(
                    "🔒 <code>{}</code> <b>{} {} {}</b> <code>{}</code>".format(
                        utils.escape_html(group.name),
                        self._convert_time(int(rule["expires"] - time.time())) if rule["expires"] else self.strings("forever"),
                        self.strings("for"),
                        self.strings(rule["rule_type"]),
                        rule["rule"],
                    )
                )
        rules_list = list(filter(None, rules_list))
        await utils.answer(
            message,
            self.strings("rules").format("\n".join(rules_list)) if rules_list else self.strings("no_tsec"),
        )
    @command("tsecrm", required=OWNER)
    async def tsecrm_cmd(self, event) -> None:
        message = event.message
        args = utils.get_args(message)
        if not args or args[0] not in {"user", "chat", "sgroup"}:
            await utils.answer(message, self.strings("no_target"))
            return
        sec = self._sec()
        if args[0] == "user":
            target = await self._target_from_reply_or_pm(message)
            if target is None or len(args) < 2:
                await utils.answer(message, self.strings("no_target"))
                return
            if sec is None or not sec.remove_rule("user", target.id, args[1]):
                await utils.answer(message, self.strings("no_rules"))
                return
            await utils.answer(
                message,
                self.strings("rule_removed").format(utils.escape_html(args[1]), utils.get_entity_url(target), utils.escape_html(utils.get_display_name(target))),
            )
            return
        if args[0] == "sgroup":
            if len(args) < 3 or args[1] not in self._sgroups:
                await utils.answer(message, self.strings("no_target"))
                return
            group = self._sgroups[args[1]]
            any_ = False
            for rule in list(group.permissions):
                if rule["rule"] == args[2]:
                    group.permissions.remove(rule)
                    any_ = True
            if not any_:
                await utils.answer(message, self.strings("no_rules"))
                return
            self._sgroups[args[1]] = group
            self._reload_sgroups()
            await utils.answer(
                message,
                self.strings("rule_removed").format(utils.escape_html(args[2]), "", utils.escape_html(group.name)),
            )
            return
        if getattr(message, "is_private", False) or len(args) < 2:
            await utils.answer(message, self.strings("no_target"))
            return
        target = await self.client.get_entity(message.peer_id)
        if sec is None or not sec.remove_rule("chat", target.id, args[1]):
            await utils.answer(message, self.strings("no_rules"))
            return
        await utils.answer(
            message,
            self.strings("rule_removed").format(utils.escape_html(args[1]), utils.get_entity_url(target), utils.escape_html(utils.get_display_name(target))),
        )
    @command("tsecclr", required=OWNER)
    async def tsecclr_cmd(self, event) -> None:
        message = event.message
        args = utils.get_args(message)
        if not args or args[0] not in {"user", "chat", "sgroup"}:
            await utils.answer(message, self.strings("no_target"))
            return
        sec = self._sec()
        if args[0] == "user":
            target = await self._target_from_reply_or_pm(message)
            if target is None:
                await utils.answer(message, self.strings("no_target"))
                return
            if sec is None or not sec.remove_rules("user", target.id):
                await utils.answer(message, self.strings("no_rules"))
                return
            await utils.answer(
                message,
                self.strings("rules_removed").format(utils.get_entity_url(target), utils.escape_html(utils.get_display_name(target))),
            )
            return
        if args[0] == "sgroup":
            if len(args) < 2 or args[1] not in self._sgroups:
                await utils.answer(message, self.strings("no_target"))
                return
            group = self._sgroups[args[1]]
            group.permissions.clear()
            self._sgroups[args[1]] = group
            self._reload_sgroups()
            await utils.answer(
                message,
                self.strings("rules_removed").format("", utils.escape_html(group.name)),
            )
            return
        if getattr(message, "is_private", False):
            await utils.answer(message, self.strings("no_target"))
            return
        target = await self.client.get_entity(message.peer_id)
        if sec is None or not sec.remove_rules("chat", target.id):
            await utils.answer(message, self.strings("no_rules"))
            return
        await utils.answer(
            message,
            self.strings("rules_removed").format(utils.get_entity_url(target), utils.escape_html(utils.get_display_name(target))),
        )
    async def _target_from_reply_or_pm(self, message):
        if getattr(message, "is_private", False):
            return await self.client.get_entity(message.peer_id)
        if getattr(message, "reply_to_msg_id", None):
            reply = await message.get_reply_message()
            if reply and reply.sender_id:
                return await self.client.get_entity(reply.sender_id)
        return None
    @command("sgroups", required=OWNER)
    async def sgroups_cmd(self, event) -> None:
        message = event.message
        groups = list(self._sgroups)
        if not groups:
            await utils.answer(message, self.strings("no_sgroups"))
            return
        lines = [
            self.strings("sgroup_li").format(g.name, len(g.users), len(g.permissions))
            for _, g in self._sgroups
        ]
        await utils.answer(message, self.strings("sgroups_list").format("\n".join(lines)))
    @command("newsgroup", required=OWNER)
    async def newsgroup_cmd(self, event) -> None:
        message = event.message
        args = utils.get_args_raw(message)
        if not args:
            await utils.answer(message, self.strings("no_args"))
            return
        if not args.isalnum():
            await utils.answer(message, self.strings("invalid_name"))
            return
        if args in self._sgroups:
            await utils.answer(message, self.strings("sgroup_already_exists").format(args))
            return
        self._sgroups[args] = SecurityGroup(args, [], [])
        self._reload_sgroups()
        await utils.answer(message, self.strings("created_sgroup").format(args))
    @command("delsgroup", required=OWNER)
    async def delsgroup_cmd(self, event) -> None:
        message = event.message
        args = utils.get_args_raw(message)
        if not args:
            await utils.answer(message, self.strings("no_args"))
            return
        if args not in self._sgroups:
            await utils.answer(message, self.strings("sgroup_not_found").format(args))
            return
        del self._sgroups[args]
        self._reload_sgroups()
        await utils.answer(message, self.strings("deleted_sgroup").format(args))
    @command("sgroup", required=OWNER)
    async def sgroup_cmd(self, event) -> None:
        message = event.message
        args = utils.get_args_raw(message)
        if not args:
            await utils.answer(message, self.strings("no_args"))
            return
        if args not in self._sgroups:
            await utils.answer(message, self.strings("sgroup_not_found").format(args))
            return
        group = self._sgroups[args]
        users_block = self.strings("no_users")
        if group.users:
            user_lines = []
            for uid in group.users:
                try:
                    ent = await self.client.get_entity(uid)
                    user_lines.append(
                        self.strings("li").format(
                            utils.get_entity_url(ent),
                            utils.escape_html(utils.get_display_name(ent)),
                            uid,
                        )
                    )
                except Exception:
                    user_lines.append(self.strings("li").format("", str(uid), uid))
            users_block = "\n".join(user_lines)
        perms_block = self.strings("no_permissions")
        if group.permissions:
            perm_lines = []
            for rule in group.permissions:
                perm_lines.append(
                    "▫️ <b>{}</b> <code>{}</code> <b>{}</b>".format(
                        self.strings(rule["rule_type"]),
                        rule["rule"],
                        (self.strings("until") + " " + self._convert_time_abs(rule["expires"])) if rule["expires"] else self.strings("forever"),
                    )
                )
            perms_block = "\n".join(perm_lines)
        await utils.answer(
            message,
            self.strings("sgroup_info").format(group.name, users_block, perms_block),
        )
    @command("sgroupadd", required=OWNER)
    async def sgroupadd_cmd(self, event) -> None:
        await self._sgroup_membership(event, add=True)
    @command("sgroupdel", required=OWNER)
    async def sgroupdel_cmd(self, event) -> None:
        await self._sgroup_membership(event, add=False)
    async def _sgroup_membership(self, event, *, add: bool) -> None:
        message = event.message
        args = utils.get_args_raw(message)
        if not args:
            await utils.answer(message, self.strings("no_args"))
            return
        parts = args.split()
        if len(parts) >= 2:
            group_name, user_token = parts[0], parts[1]
            try:
                user = await self.client.get_entity(
                    int(user_token) if user_token.isdigit() else user_token
                )
            except (ValueError, TypeError):
                await utils.answer(message, self.strings("no_args"))
                return
        else:
            if not getattr(message, "reply_to_msg_id", None):
                await utils.answer(message, self.strings("no_args"))
                return
            group_name = parts[0]
            reply = await message.get_reply_message()
            user = await reply.get_sender()
        if group_name not in self._sgroups:
            await utils.answer(message, self.strings("sgroup_not_found").format(group_name))
            return
        group = self._sgroups[group_name]
        name = utils.escape_html(utils.get_display_name(user))
        if add:
            if user.id in group.users:
                await utils.answer(message, self.strings("user_already_in_sgroup").format(name, group.name))
                return
            group.users.append(user.id)
            self._sgroups[group_name] = group
            self._reload_sgroups()
            await utils.answer(message, self.strings("user_added_to_sgroup").format(name, group.name))
        else:
            if user.id not in group.users:
                await utils.answer(message, self.strings("user_not_in_sgroup").format(name, group.name))
                return
            group.users.remove(user.id)
            self._sgroups[group_name] = group
            self._reload_sgroups()
            await utils.answer(message, self.strings("user_removed_from_sgroup").format(name, group.name))
    @command("inlinesec", required=OWNER)
    async def inlinesec_cmd(self, event) -> None:
        message = event.message
        args = utils.get_args_raw(message).lower().strip()
        inline = self._inline()
        handlers = getattr(inline, "inline_handlers", {}) if inline else {}
        if not args:
            everyone = bool(self.db.get(_DB_KEY, "bounding_mask", OWNER) & (1 << 13))
            await utils.answer(
                message,
                "🛡 <b>Inline-безопасность</b>\n\n"
                f"<code>everyone</code>: {'✅' if everyone else '🚫'}\n\n"
                "Используй <code>.tsec user inline &lt;команда&gt;</code>, "
                "чтобы выдать конкретному пользователю право на inline-команду.",
            )
            return
        if args not in handlers:
            await utils.answer(message, self.strings("no_rule"))
            return
        await utils.answer(
            message,
            f"🛡 Inline-команда <code>{utils.escape_html(args)}</code> найдена. "
            "Выдай права через <code>.tsec user inline " + utils.escape_html(args) + "</code>.",
        )
