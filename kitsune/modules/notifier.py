
from __future__ import annotations

import asyncio
import logging
import re
import os

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_OWNER       = "kitsune.notifier"
_CHECK_INTERVAL = 30

def _extract_buttons(message) -> list[str]:
    result = []
    try:
        markup = getattr(message, "reply_markup", None)
        if markup is None:
            return result
        rows = getattr(markup, "rows", []) or []
        for row in rows:
            buttons = getattr(row, "buttons", []) or []
            for btn in buttons:
                text = getattr(btn, "text", "") or ""
                if text:
                    result.append(text)
    except Exception:
        pass
    return result

class NotifierModule(KitsuneModule):
    name        = "notifier"
    description = "Авто-создание бота и уведомления"
    author      = "Yushi"
    version     = "1.2"

    strings_ru = {
        "creating":      "🤖 Создаю бота через @BotFather...",
        "done":          "✅ Бот <b>{name}</b> создан и подключён!\nТокен сохранён автоматически.",
        "reused":        "♻️ Бот <b>{name}</b> уже существует — переподключаю.\nПересоздавать не нужно.",
        "reset_done":    "♻️ Бот сброшен. Перезапусти Kitsune — бот создастся заново.",
        "frozen_hint": (
            "⚠️ <b>Бот заморожен Telegram.</b>\n\n"
            "Создай нового бота у @BotFather и замени токен в config.toml:\n\n"
            "<code>bot_token = \"новый_токен\"</code>\n\n"
            "Затем перезапусти Kitsune."
        ),
        "update_notify": (
            "🦊 <b>Kitsune Userbot</b>\n\n"
            "🆕 <b>Доступно обновление!</b>\n"
            "New update available!\n\n"
            "📌 Версия / Version: <code>{current}</code> → <code>{new}</code>\n\n"
            "📋 <b>Изменения / Changes:</b>\n{changes}"
        ),
        "update_step1": "⬇️ <b>Скачиваю обновление...</b>\nDownloading update...",
        "update_step2": "📦 <b>Устанавливаю обновление...</b>\nInstalling update...",
        "update_step3": "🔄 <b>Перезапускаю бота...</b>\nRestarting bot...",
        "update_done":  (
            "✅ <b>Обновление успешно установлено!</b>\n"
            "Update installed successfully!\n\n"
            "⏱ Время перезапуска: <code>{restart_time}</code>\n"
            "📦 Модули загружены: <code>{mod_count}</code>"
        ),
        "update_err":  "❌ Ошибка / Error:\n<code>{err}</code>",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._bot:          object | None = None
        self._dp:           object | None = None
        self._polling_task: asyncio.Task | None = None
        self._check_task:   asyncio.Task | None = None

    async def on_load(self) -> None:
        config_token = self._load_token_from_config()
        if config_token:
            await self.db.set(_DB_OWNER, "bot_token", config_token)
            logger.info("Notifier: token loaded from config.toml")

        token = self.db.get(_DB_OWNER, "bot_token", None)

        if token:
            backup_asked = self.db.get(_DB_OWNER, "backup_interval_asked", False)
            asyncio.ensure_future(self._start_polling(
                str(token), first_run=not backup_asked
            ))
            self._check_task = asyncio.ensure_future(self._update_check_loop())
            asyncio.ensure_future(self._notify_update_done())
            asyncio.ensure_future(self._polling_watchdog(str(token)))
            asyncio.ensure_future(self._start_inline_manager(str(token)))
        else:
            asyncio.ensure_future(self._auto_setup())

    async def on_unload(self) -> None:
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
        await self._stop_polling()

    @command("resetbot", required=OWNER)
    async def resetbot_cmd(self, event) -> None:
        await self.db.delete(_DB_OWNER, "bot_token")
        await self.db.delete(_DB_OWNER, "bot_name")
        await self.db.delete(_DB_OWNER, "bot_username")
        await self._stop_polling()
        await event.reply(self.strings("reset_done"), parse_mode="html")

    @command("mybots", required=OWNER)
    async def mybots_cmd(self, event) -> None:
        m = await event.reply("🔍 Ищу ботов...", parse_mode="html")
        try:
            bots = await self._list_kitsune_bots()
            if not bots:
                await m.edit("❌ Ботов Kitsune не найдено.", parse_mode="html")
                return
            current_token = self.db.get(_DB_OWNER, "bot_token", None)
            lines = ["🤖 <b>Боты Kitsune на этом аккаунте:</b>\n"]
            for i, (uname, token) in enumerate(bots, 1):
                active = " ✅ <i>(активный)</i>" if token and token == current_token else ""
                lines.append(f"  {i}. @{uname}{active}")
            lines.append("\nЧтобы выбрать бота: <code>.setbot @username</code>")
            await m.edit("\n".join(lines), parse_mode="html")
        except Exception as exc:
            await m.edit(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")

    @command("setbot", required=OWNER)
    async def setbot_cmd(self, event) -> None:
        arg = self.get_args(event).strip().lstrip("@")
        if not arg:
            await event.reply(
                "❌ Укажи username: <code>.setbot @kitsune_123456_bot</code>",
                parse_mode="html",
            )
            return

        m = await event.reply("🔍 Получаю токен...", parse_mode="html")
        try:
            token = await self._get_token_for_bot(arg)
            if not token:
                await m.edit(
                    f"❌ Не удалось получить токен для @{arg}.\nУбедись что этот бот принадлежит тебе.",
                    parse_mode="html",
                )
                return

            await self._stop_polling()

            await self.db.set(_DB_OWNER, "bot_token", token)
            await self.db.set(_DB_OWNER, "bot_username", arg)
            self._save_token_to_config(token)

            asyncio.ensure_future(self._start_polling(token, first_run=False))
            await m.edit(
                f"✅ Теперь использую бота <b>@{arg}</b>.",
                parse_mode="html",
            )
        except Exception as exc:
            await m.edit(f"❌ Ошибка: <code>{exc}</code>", parse_mode="html")

    async def _auto_setup(self) -> None:
        try:
            me = await self.client.get_me()
            logger.info("Notifier: first run for tg_id=%d", me.id)

            await self.db.set(_DB_OWNER, "owner_tg_id", me.id)

            bot_name = f"Kitsune {me.first_name}"
            token    = None
            reused   = False

            token, bot_username = await self._find_existing_bot(me.id)
            if token:
                reused = True
                logger.info("Notifier: found existing bot @%s", bot_username)
            else:
                token, bot_username = await self._create_bot(me, bot_name)

            if not token:
                logger.error("Notifier: failed to get token")
                return

            await self.db.set(_DB_OWNER, "bot_token",    token)
            await self.db.set(_DB_OWNER, "bot_name",     bot_name)
            await self.db.set(_DB_OWNER, "bot_username", bot_username or "")
            await self.db.set(_DB_OWNER, "owner_id",     me.id)
            self._save_token_to_config(token)

            key = "reused" if reused else "done"
            await self.client.send_message(
                "me",
                self.strings(key).format(name=bot_name),
                parse_mode="html",
            )

            asyncio.ensure_future(self._start_polling(token, first_run=not reused))
            self._check_task = asyncio.ensure_future(self._update_check_loop())

        except asyncio.TimeoutError:
            logger.warning("Notifier: BotFather timed out, retry on next restart")
        except Exception:
            logger.exception("Notifier: auto setup failed")

    async def _list_kitsune_bots(self) -> list[tuple[str, str | None]]:
        import re as _re
        results = []
        try:
            async with self.client.conversation("@BotFather", timeout=40) as conv:
                await conv.send_message("/mybots")
                resp = await conv.get_response()

                usernames = _extract_buttons(resp)
                if not usernames:
                    usernames = _re.findall(r"@([a-zA-Z0-9_]+bot)", resp.text or "", _re.IGNORECASE)

                for uname in usernames:
                    uname = uname.lstrip("@")
                    try:
                        await conv.send_message(f"@{uname}")
                        menu_resp = await conv.get_response()
                        token_text = menu_resp.text or ""
                        m = _re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", token_text)
                        if m:
                            results.append((uname, m.group(1)))
                        else:
                            await conv.send_message("/token")
                            token_resp = await conv.get_response()
                            token_text2 = token_resp.text or ""
                            m2 = _re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", token_text2)
                            results.append((uname, m2.group(1) if m2 else None))
                    except Exception as e:
                        logger.debug("Notifier: token fetch failed for %s — %s", uname, e)
                        results.append((uname, None))
        except Exception as exc:
            logger.debug("Notifier: _list_kitsune_bots failed — %s", exc)
        return results

    async def _get_token_for_bot(self, username: str) -> str | None:
        import re as _re
        username = username.lstrip("@")
        try:
            async with self.client.conversation("@BotFather", timeout=20) as conv:
                await conv.send_message(f"@{username}")
                menu_resp = await conv.get_response()
                token_text = menu_resp.text or ""
                m = _re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", token_text)
                if m:
                    return m.group(1)
                await conv.send_message("/token")
                token_resp = await conv.get_response()
                token_text2 = token_resp.text or ""
                m2 = _re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", token_text2)
                return m2.group(1) if m2 else None
        except Exception as exc:
            logger.debug("Notifier: _get_token_for_bot failed — %s", exc)
            return None

    async def _find_existing_bot(self, tg_id: int) -> tuple[str | None, str | None]:
        try:
            async with self.client.conversation("@BotFather", timeout=20) as conv:
                await conv.send_message("/mybots")
                resp = await conv.get_response()
                text = resp.text or ""

                pattern = rf"kitsune_{tg_id}[a-z0-9_]*_bot"
                match   = re.search(pattern, text, re.IGNORECASE)
                if not match:
                    return None, None

                username = match.group(0)

                await conv.send_message(f"@{username}")
                await conv.get_response()

                await conv.send_message("/token")
                token_resp = await conv.get_response()
                token_text = token_resp.text or ""

                token_match = re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", token_text)
                if token_match:
                    return token_match.group(1), username

        except Exception as exc:
            logger.debug("Notifier: _find_existing_bot failed — %s", exc)

        return None, None

    async def _create_bot(self, me, bot_name: str) -> tuple[str | None, str | None]:
        try:
            async with self.client.conversation("@BotFather", timeout=30) as conv:
                await conv.send_message("/start")
                await conv.get_response()

                await conv.send_message("/newbot")
                await conv.get_response()

                await conv.send_message(bot_name)
                await conv.get_response()

                token    = None
                username = None
                for suffix in ["", f"_{me.id % 10000}", "_ub", "_kitsune_ub"]:
                    uname = f"kitsune_{me.id}{suffix}_bot"
                    await conv.send_message(uname)
                    resp = await conv.get_response()
                    text = resp.text or ""

                    m = re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", text)
                    if m:
                        token    = m.group(1)
                        username = uname
                        break

                    if any(w in text.lower() for w in ("sorry", "invalid", "try", "занят")):
                        continue
                    break

            return token, username
        except Exception as exc:
            logger.error("Notifier: _create_bot failed — %s", exc)
            return None, None

    def _load_token_from_config(self) -> str | None:
        try:
            import toml
            from pathlib import Path
            cfg_path = Path(__file__).parent.parent.parent / "config.toml"
            if cfg_path.exists():
                cfg = toml.loads(cfg_path.read_text(encoding="utf-8"))
                val = cfg.get("bot_token")
                return str(val) if val else None
        except Exception:
            pass
        return None

    def _save_token_to_config(self, token: str) -> None:
        try:
            import toml
            from pathlib import Path
            cfg_path = Path(__file__).parent.parent.parent / "config.toml"
            if cfg_path.exists():
                cfg = toml.loads(cfg_path.read_text(encoding="utf-8"))
                cfg["bot_token"] = token
                cfg_path.write_text(toml.dumps(cfg), encoding="utf-8")
        except Exception:
            logger.warning("Notifier: could not write token to config.toml")

    async def _start_polling(self, token: str, *, first_run: bool = False) -> None:
        try:
            from aiogram import Bot, Dispatcher, Router
            from aiogram.client.default import DefaultBotProperties
            from aiogram.enums import ParseMode
            from aiogram.filters import Command
            from aiogram.types import Message, CallbackQuery
        except ImportError:
            logger.warning("Notifier: aiogram not installed, polling disabled")
            return

        await self._stop_polling()

        try:
            from aiogram.client.session.aiohttp import AiohttpSession

            session = AiohttpSession(timeout=30)
            self._bot = Bot(
                token=token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
                session=session,
            )
            self._dp  = Dispatcher()
            router    = Router()
            self._dp.include_router(router)
            ref = self

            @router.message(Command("start"))
            async def on_start(msg: Message) -> None:
                owner_id = ref.db.get(_DB_OWNER, "owner_id", None)
                if msg.from_user.id != owner_id:
                    try:
                        await msg.answer("🔒 Нет доступа.")
                    except Exception:
                        pass
                    return
                try:
                    backup_asked = ref.db.get(_DB_OWNER, "backup_interval_asked", False)
                    loader = getattr(ref.client, "_kitsune_loader", None)
                    backup = loader.modules.get("backup") if loader else None

                    if not backup_asked and backup:
                        await backup.show_interval_setup(ref._bot, msg.from_user.id)
                        await ref.db.set(_DB_OWNER, "backup_interval_asked", True)
                    else:
                        interval_h = ref.db.get("kitsune.backup", "interval_h", None)
                        backup_status = (
                            f"каждые <b>{interval_h} ч</b>" if interval_h
                            else "не настроен"
                        )
                        bot_ver = ref.version
                        await msg.answer(
                            "🦊 <b>Kitsune Notifier</b>\n\n"
                            "Я присылаю уведомления об обновлениях и храню бэкапы.\n\n"
                            f"🗂 Авто-бэкап: {backup_status}\n\n"
                            "Команды:\n"
                            "• <code>.backup</code> — создать бэкап вручную\n"
                            "• <code>.restore</code> — восстановить из бэкапа\n"
                            "• <code>.autodel</code> — авто-удаление сервисных сообщений\n"
                            "• <code>.resetbot</code> — пересоздать бота\n"
                            "• <code>.update</code> — проверить обновления"
                        )
                except Exception as e:
                    logger.warning("Notifier: on_start answer failed — %s", e)

            @router.callback_query(lambda c: c.data in ("update_yes", "update_no", "do_update"))
            async def on_update_cb(call: CallbackQuery) -> None:
                owner_id = ref.db.get(_DB_OWNER, "owner_id", None)
                if call.from_user.id != owner_id:
                    await call.answer("🔒 Нет доступа.", show_alert=True)
                    return
                await call.answer()

                if call.data == "update_no":
                    await ref.db.delete("kitsune.updater", "pending_update")
                    await call.message.edit_text("❌ Обновление отменено.")
                    return

                await call.message.edit_text(ref.strings("update_step1"), parse_mode="HTML")
                import asyncio as _asyncio
                _asyncio.ensure_future(ref._safe_update_run(call.message))

            @router.callback_query(lambda c: c.data and c.data.startswith("backup_interval:"))
            async def on_backup_interval(call: CallbackQuery) -> None:
                owner_id = ref.db.get(_DB_OWNER, "owner_id", None)
                if call.from_user.id != owner_id:
                    await call.answer("🔒 Нет доступа.", show_alert=True)
                    return
                loader  = getattr(ref.client, "_kitsune_loader", None)
                backup  = loader.modules.get("backup") if loader else None
                if backup:
                    await backup.handle_interval_callback(call)
                else:
                    await call.answer("Модуль backup не загружен.", show_alert=True)


            @router.callback_query(lambda c: c.data and c.data.startswith("cfg_"))
            async def on_config_cb(call: CallbackQuery) -> None:
                owner_id = ref.db.get(_DB_OWNER, "owner_id", None)
                if call.from_user.id != owner_id:
                    await call.answer("🔒 Нет доступа.", show_alert=True)
                    return
                await call.answer()

                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                from ..modules.config import _get_configurable, _mod_text, _list_text

                data = call.data

                if data == "cfg_close":
                    await call.message.delete()
                    return

                if data == "cfg_back":
                    configurable = _get_configurable(ref.client)
                    buttons = []
                    row = []
                    for name in sorted(configurable.keys()):
                        mod = configurable[name]
                        row.append(InlineKeyboardButton(
                            text=mod.name,
                            callback_data=f"cfg_mod:{name}",
                        ))
                        if len(row) == 3:
                            buttons.append(row)
                            row = []
                    if row:
                        buttons.append(row)
                    buttons.append([
                        InlineKeyboardButton(text="❌ Закрыть", callback_data="cfg_close"),
                    ])
                    await call.message.edit_text(
                        _list_text(configurable),
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                        parse_mode="HTML",
                    )
                    return

                if data.startswith("cfg_mod:"):
                    mod_name = data.split(":", 1)[1]
                    configurable = _get_configurable(ref.client)
                    mod = configurable.get(mod_name)
                    if not mod:
                        await call.message.edit_text("❌ Модуль не найден.")
                        return
                    buttons = []
                    for k in mod.config.keys():
                        buttons.append([InlineKeyboardButton(
                            text=f"✏️ {k}",
                            callback_data=f"cfg_key:{mod_name}:{k}",
                        )])
                    buttons.append([
                        InlineKeyboardButton(text="◀️ Назад", callback_data="cfg_back"),
                        InlineKeyboardButton(text="❌ Закрыть", callback_data="cfg_close"),
                    ])
                    await call.message.edit_text(
                        _mod_text(mod_name, mod),
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                        parse_mode="HTML",
                    )
                    return

                if data.startswith("cfg_key:"):
                    _, mod_name, key = data.split(":", 2)
                    configurable = _get_configurable(ref.client)
                    mod = configurable.get(mod_name)
                    if not mod or key not in mod.config:
                        await call.message.edit_text("❌ Параметр не найден.")
                        return
                    val     = mod.config[key]
                    default = mod.config.get_default(key)
                    doc     = mod.config.get_doc(key) or "—"
                    text = (
                        f"⚙️ <b>{mod.name}</b> → <code>{key}</code>\n\n"
                        f"📄 <i>{doc}</i>\n\n"
                        f"🔹 Текущее: <b>{val}</b>\n"
                        f"🔸 По умолчанию: <b>{default}</b>\n\n"
                        f"Отправь новое значение в ответ на это сообщение."
                    )
                    buttons = []
                    if isinstance(val, bool):
                        buttons.append([
                            InlineKeyboardButton(
                                text="✅ True" if not val else "☑️ True (текущее)",
                                callback_data=f"cfg_set:{mod_name}:{key}:true",
                            ),
                            InlineKeyboardButton(
                                text="❌ False" if val else "☑️ False (текущее)",
                                callback_data=f"cfg_set:{mod_name}:{key}:false",
                            ),
                        ])
                    if val != default:
                        buttons.append([InlineKeyboardButton(
                            text="🔄 Сбросить до дефолта",
                            callback_data=f"cfg_reset:{mod_name}:{key}",
                        )])
                    buttons.append([
                        InlineKeyboardButton(text="◀️ Назад", callback_data=f"cfg_mod:{mod_name}"),
                        InlineKeyboardButton(text="❌ Закрыть", callback_data="cfg_close"),
                    ])
                    await ref.db.set("kitsune.config", "pending_input", {
                        "mod": mod_name, "key": key,
                        "msg_id": call.message.message_id,
                        "chat_id": call.message.chat.id,
                    })
                    await call.message.edit_text(
                        text,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                        parse_mode="HTML",
                    )
                    return

                if data.startswith("cfg_set:"):
                    parts = data.split(":", 3)
                    mod_name, key, raw_val = parts[1], parts[2], parts[3]
                    configurable = _get_configurable(ref.client)
                    mod = configurable.get(mod_name)
                    if mod and key in mod.config:
                        mod.config[key] = raw_val.lower() == "true"
                        await ref.db.set(f"kitsune.config.{mod_name}", "values",
                            {k: mod.config[k] for k in mod.config.keys()})
                        await call.message.edit_text(
                            f"✅ <b>{mod.name}</b> → <code>{key}</code> = <b>{mod.config[key]}</b>",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(text="◀️ Назад", callback_data=f"cfg_mod:{mod_name}"),
                            ]]),
                            parse_mode="HTML",
                        )
                    return

                if data.startswith("cfg_reset:"):
                    _, mod_name, key = data.split(":", 2)
                    configurable = _get_configurable(ref.client)
                    mod = configurable.get(mod_name)
                    if mod and key in mod.config:
                        mod.config[key] = mod.config.get_default(key)
                        await ref.db.set(f"kitsune.config.{mod_name}", "values",
                            {k: mod.config[k] for k in mod.config.keys()})
                        await call.message.edit_text(
                            f"✅ <b>{mod.name}</b> → <code>{key}</code> сброшен до <b>{mod.config[key]}</b>",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(text="◀️ Назад", callback_data=f"cfg_mod:{mod_name}"),
                            ]]),
                            parse_mode="HTML",
                        )
                    return

            @router.message(lambda m: True)
            async def on_text_input(msg: Message) -> None:
                owner_id = ref.db.get(_DB_OWNER, "owner_id", None)
                if msg.from_user.id != owner_id:
                    return
                pending = ref.db.get("kitsune.config", "pending_input", None)
                if not pending:
                    return
                await ref.db.delete("kitsune.config", "pending_input")
                mod_name = pending["mod"]
                key      = pending["key"]
                value    = msg.text or ""
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                from ..modules.config import _get_configurable
                configurable = _get_configurable(ref.client)
                mod = configurable.get(mod_name)
                if not mod or key not in mod.config:
                    return
                orig = mod.config.get_default(key)
                try:
                    if isinstance(orig, int):
                        value = int(value)
                    elif isinstance(orig, float):
                        value = float(value)
                except (ValueError, TypeError):
                    pass
                mod.config[key] = value
                await ref.db.set(f"kitsune.config.{mod_name}", "values",
                    {k: mod.config[k] for k in mod.config.keys()})
                try:
                    await ref._bot.edit_message_text(
                        chat_id=pending["chat_id"],
                        message_id=pending["msg_id"],
                        text=f"✅ <b>{mod.name}</b> → <code>{key}</code> = <b>{value}</b>",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="◀️ Назад", callback_data=f"cfg_mod:{mod_name}"),
                        ]]),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                try:
                    await msg.delete()
                except Exception:
                    pass

            self._polling_task = asyncio.ensure_future(
                self._dp.start_polling(self._bot, handle_signals=False)
            )
            logger.info("Notifier: polling started (first_run=%s)", first_run)

            if first_run:
                owner_id = self.db.get(_DB_OWNER, "owner_id", None)
                if owner_id:
                    await asyncio.sleep(2)
                    loader = getattr(self.client, "_kitsune_loader", None)
                    backup = loader.modules.get("backup") if loader else None
                    if backup:
                        await backup.show_interval_setup(self._bot, int(owner_id))
                        await self.db.set(_DB_OWNER, "backup_interval_asked", True)

        except Exception:
            logger.exception("Notifier: polling failed — bot may be frozen")
            await self.client.send_message("me", self.strings("frozen_hint"), parse_mode="html")

    async def _stop_polling(self) -> None:
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
        if self._dp:
            try:
                await self._dp.stop_polling()
            except Exception:
                pass
        if self._bot:
            try:
                await self._bot.session.close()
            except Exception:
                pass
        self._bot          = None
        self._dp           = None
        self._polling_task = None

    async def _start_inline_manager(self, token: str) -> None:
        import asyncio as _aio
        for _ in range(20):
            if self._bot is not None:
                break
            await _aio.sleep(0.5)
        try:
            from ..inline.core import InlineManager
            inline = InlineManager(self.client, self.db, token)
            inline._bot     = self._bot
            inline._dp      = self._dp
            inline._started = True

            from aiogram import Router as _Router
            inline_router = _Router()
            inline_router.callback_query.register(inline._on_callback)
            self._dp.include_router(inline_router)

            self.client._kitsune_inline = inline
            logger.info("Notifier: InlineManager attached to existing bot")
        except Exception:
            logger.exception("Notifier: failed to attach InlineManager")

    async def _update_check_loop(self) -> None:
        await asyncio.sleep(300)
        while True:
            try:
                await self._check_for_updates()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Notifier: update check failed")
            await asyncio.sleep(600)

    async def _polling_watchdog(self, token: str) -> None:
        import asyncio as _asyncio
        while True:
            await _asyncio.sleep(120)
            if self._polling_task and self._polling_task.done():
                exc = self._polling_task.exception() if not self._polling_task.cancelled() else None
                logger.warning("Notifier: polling died (%s) — restarting", exc)
                await self._start_polling(token, first_run=False)

    async def _check_for_updates(self) -> None:
        try:
            import git as gitpython
            repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            repo      = gitpython.Repo(repo_path)
            try:
                branch = repo.active_branch.name
            except TypeError:
                branch = "main"
        except Exception as exc:
            logger.debug("Notifier: git repo unavailable — %s", exc)
            return

        try:
            for remote in repo.remotes:
                remote.fetch()
        except Exception as exc:
            logger.debug("Notifier: git fetch failed — %s", exc)
            return

        try:
            diff = repo.git.log([f"HEAD..origin/{branch}", "--oneline"])
        except Exception as exc:
            logger.debug("Notifier: git log failed — %s", exc)
            return

        if not diff:
            return

        try:
            remote_sha = next(
                repo.iter_commits(f"origin/{branch}", max_count=1)
            ).hexsha
        except Exception:
            return

        if remote_sha == self.db.get(_DB_OWNER, "last_notified_commit", None):
            return

        await self.db.set(_DB_OWNER, "last_notified_commit", remote_sha)

        log_lines  = diff.splitlines()[:10]
        count      = len(diff.splitlines())
        changes    = "\n".join(
            f"• <b>{line.split()[0]}</b>: {' '.join(line.split()[1:])}"
            for line in log_lines
            if line.strip()
        ) or "—"

        if count > 10:
            changes += f"\n<i>...и ещё {count - 10} коммитов</i>"

        from ..version import __version_str__

        try:
            remote_version = repo.git.show(f"origin/{branch}:kitsune/version.py")
            import re as _re
            m = _re.search(r"__version__\s*=\s*\((\d+),\s*(\d+),\s*(\d+)\)", remote_version)
            new_ver = f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else f"{__version_str__}+{count}"
        except Exception:
            new_ver = f"{__version_str__}+{count}"

        await self.notify_update(
            current=__version_str__,
            new=new_ver,
            changes=changes,
        )

    def _make_bot(self, token: str) -> "Bot":
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from aiogram.client.session.aiohttp import AiohttpSession

        return Bot(
            token=str(token),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            session=AiohttpSession(timeout=30),
        )

    async def send_restart_report(self, restart_time: str, total_time: str, mod_count: int) -> None:
        token    = self.db.get(_DB_OWNER, "bot_token", None)
        owner_id = self.db.get(_DB_OWNER, "owner_id",  None)
        if not token or not owner_id:
            return
        try:
            bot = self._make_bot(str(token))
            await bot.send_message(
                chat_id=int(owner_id),
                text=(
                    "✅ <b>Kitsune перезапущен</b>\n\n"
                    f"⏱ Перезапуск: <code>{restart_time}</code>\n"
                    f"📦 Модули: <code>{mod_count}</code>\n"
                    f"⚡ Полная загрузка: <code>{total_time}</code>"
                ),
            )
            await bot.session.close()
        except Exception:
            logger.exception("Notifier: failed to send restart report")

    async def _safe_update_run(self, msg) -> None:
        import asyncio as _asyncio

        async def edit(text: str) -> None:
            try:
                await msg.edit_text(text, parse_mode="HTML")
            except Exception:
                pass

        for attempt in range(1, 4):
            try:
                await self._do_update(msg)
                return
            except Exception as exc:
                err = str(exc)
                if "unable to access" in err or "Couldn't connect" in err or "timed out" in err.lower():
                    if attempt < 3:
                        await edit(
                            f"⚠️ Нет соединения, повтор {attempt}/3...\n"
                            f"No connection, retry {attempt}/3..."
                        )
                        await _asyncio.sleep(15)
                        continue
                await edit(self.strings("update_err").format(err=err))
                return

    async def notify_update(self, current: str, new: str, changes: str = "") -> None:
        token    = self.db.get(_DB_OWNER, "bot_token", None)
        owner_id = self.db.get(_DB_OWNER, "owner_id",  None)
        if not token or not owner_id:
            return
        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            bot = self._make_bot(str(token))
            kb  = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⬆️ Обновить / Update", callback_data="do_update"),
            ]])
            await bot.send_message(
                chat_id=int(owner_id),
                text=self.strings("update_notify").format(
                    current=current, new=new, changes=changes or "—"
                ),
                reply_markup=kb,
            )
            await bot.session.close()
        except Exception:
            logger.exception("Notifier: failed to send update notification")

    async def _notify_update_done(self) -> None:
        import time
        chat_id     = self.db.get(_DB_OWNER, "update_msg_chat", None)
        msg_id      = self.db.get(_DB_OWNER, "update_msg_id",   None)
        start_time  = self.db.get(_DB_OWNER, "update_start_time", None)
        if not chat_id or not msg_id or not start_time:
            return

        await self.db.delete(_DB_OWNER, "update_msg_chat")
        await self.db.delete(_DB_OWNER, "update_msg_id")
        await self.db.delete(_DB_OWNER, "update_start_time")

        await asyncio.sleep(3)

        elapsed = time.time() - float(start_time)
        if elapsed < 1:
            restart_time = f"{elapsed * 1000:.0f} мс"
        elif elapsed < 60:
            restart_time = f"{elapsed:.1f} с"
        else:
            m, s = divmod(int(elapsed), 60)
            restart_time = f"{m}м {s}с"

        loader    = getattr(self.client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0

        token    = self.db.get(_DB_OWNER, "bot_token", None)
        owner_id = self.db.get(_DB_OWNER, "owner_id",  None)
        if not token or not owner_id:
            return

        try:
            bot = self._make_bot(str(token))
            await bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=int(msg_id),
                text=self.strings("update_done").format(
                    restart_time=restart_time,
                    mod_count=mod_count,
                ),
                parse_mode="HTML",
            )
            await bot.session.close()
        except Exception:
            logger.exception("Notifier: failed to send update_done message")

    async def _do_update(self, msg=None) -> None:
        import sys, time, shutil, tempfile
        repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        async def edit(text: str) -> None:
            if msg:
                try:
                    await msg.edit_text(text, parse_mode="HTML")
                except Exception:
                    pass

        try:
            import git
            repo   = git.Repo(repo_path)
            origin = repo.remote("origin")
            for _attempt in range(3):
                try:
                    origin.fetch()
                    break
                except Exception as _fe:
                    if _attempt == 2:
                        raise
                    import asyncio as _aio
                    await _aio.sleep(10)
            try:
                branch = repo.active_branch.name
            except TypeError:
                branch = "main"

            config_path = os.path.join(repo_path, "config.toml")
            config_backup = None
            if os.path.exists(config_path):
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".toml")
                shutil.copy2(config_path, tmp.name)
                config_backup = tmp.name
                tmp.close()

            repo.git.reset("--hard", f"origin/{branch}")

            if config_backup and os.path.exists(config_backup):
                shutil.copy2(config_backup, config_path)
                os.unlink(config_backup)

        except Exception as exc:
            raise RuntimeError(f"Git update failed: {exc}") from exc

        await edit(self.strings("update_step2"))

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
            "--quiet", cwd=repo_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode()[:300])

        await edit(self.strings("update_step3"))

        loader = getattr(self.client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0
        restart_start = time.time()

        updater = loader.modules.get("updater") if loader else None
        if updater:
            await updater._save_restart_start(
                chat_id=0, msg_id=0,
            )
        await self.db.set(_DB_OWNER, "update_msg_chat", msg.chat.id if msg else 0)
        await self.db.set(_DB_OWNER, "update_msg_id",   msg.message_id if msg else 0)
        await self.db.set(_DB_OWNER, "update_start_time", restart_start)
        await self.db.force_save()

        await asyncio.sleep(1)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")
