from __future__ import annotations

import asyncio
import logging
import ssl
import typing

logger = logging.getLogger(__name__)

_DB_KEY = "kitsune.notifier"

def _make_bot(token: str) -> typing.Any:
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    import aiohttp
    from aiogram.client.session.aiohttp import AiohttpSession

    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    class _NoSSLSession(AiohttpSession):
        async def create_connector(self, _bot=None):
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            self._should_reset_connector = False
            return connector

    # aiogram 3.x требует aiohttp.ClientTimeout, а не голый int
    _timeout = aiohttp.ClientTimeout(total=60, connect=15, sock_read=30)

    return Bot(
        token=str(token),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=_NoSSLSession(timeout=_timeout),
    )

class BotRunner:

    def __init__(self, client, db) -> None:
        self._client = client
        self._db = db
        self.bot: typing.Any = None
        self.dp: typing.Any = None
        self._polling_task: asyncio.Task | None = None

    async def start(self, token: str, *, first_run: bool = False) -> None:
        try:
            from aiogram import Dispatcher, Router
        except ImportError:
            logger.warning("BotRunner: aiogram not installed, polling disabled")
            return

        await self.stop()

        try:
            self.bot = _make_bot(token)
            self.dp = Dispatcher()
            router = Router()
            self.dp.include_router(router)

            self._register_handlers(router)

            self._polling_task = asyncio.ensure_future(
                self.dp.start_polling(self.bot, handle_signals=False)
            )
            logger.info("BotRunner: polling started (first_run=%s)", first_run)

            if first_run:
                owner_id = self._db.get(_DB_KEY, "owner_id", None)
                if owner_id:
                    await asyncio.sleep(2)
                    loader = getattr(self._client, "_kitsune_loader", None)
                    backup = loader.modules.get("backup") if loader else None
                    if backup:
                        await backup.show_interval_setup(self.bot, int(owner_id))
                        await self._db.set(_DB_KEY, "backup_interval_asked", True)

        except Exception as exc:
            err = str(exc).lower()
            _net = ("network", "connection", "ssl", "timeout", "certificate",
                    "connect", "resolve", "reset", "eof", "broken pipe")
            if any(kw in err for kw in _net):
                logger.warning("BotRunner: network error — retry in 60s: %s", exc)
                await asyncio.sleep(60)
                token2 = self._db.get(_DB_KEY, "bot_token", None)
                if token2:
                    asyncio.ensure_future(self.start(str(token2), first_run=False))
            else:
                logger.exception("BotRunner: polling failed — bot may be frozen")
                await self._client.send_message(
                    "me",
                    "⚠️ <b>Бот заморожен Telegram.</b>\n\n"
                    "Создай нового бота у @BotFather и замени токен в config.toml:\n\n"
                    "<code>bot_token = \"новый_токен\"</code>\n\nЗатем перезапусти Kitsune.",
                    parse_mode="html",
                )

    async def stop(self) -> None:
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()
        if self.dp:
            try:
                await self.dp.stop_polling()
            except Exception:
                pass
        if self.bot:
            try:
                await self.bot.session.close()
            except Exception:
                pass
        self.bot = None
        self.dp = None
        self._polling_task = None

    async def send_message(self, chat_id: int, text: str, **kwargs) -> None:
        if self.bot:
            await self.bot.send_message(chat_id=chat_id, text=text, **kwargs)

    def _register_handlers(self, router) -> None:
        from aiogram.filters import Command
        from aiogram.types import Message, CallbackQuery

        ref = self

        @router.message(Command("start"))
        async def on_start(msg: Message) -> None:
            await ref._on_start(msg)

        @router.callback_query(lambda c: c.data in ("update_yes", "update_no", "do_update"))
        async def on_update_cb(call: CallbackQuery) -> None:
            await ref._on_update_cb(call)

        @router.callback_query(lambda c: c.data and c.data.startswith("backup_interval:"))
        async def on_backup_interval(call: CallbackQuery) -> None:
            await ref._on_backup_interval(call)

        @router.callback_query(lambda c: c.data and c.data.startswith("cfg_"))
        async def on_config_cb(call: CallbackQuery) -> None:
            await ref._on_config_cb(call)

        @router.message(lambda m: True)
        async def on_text_input(msg: Message) -> None:
            await ref._on_text_input(msg)

    async def _on_start(self, msg) -> None:
        owner_id = self._db.get(_DB_KEY, "owner_id", None)
        if owner_id is None or msg.from_user.id != int(owner_id):
            try:
                await msg.answer("🔒 Нет доступа.")
            except Exception:
                pass
            return
        try:
            backup_asked = self._db.get(_DB_KEY, "backup_interval_asked", False)
            interval_set = self._db.get("kitsune.backup", "interval_h", None)
            loader = getattr(self._client, "_kitsune_loader", None)
            backup = loader.modules.get("backup") if loader else None

            if (not backup_asked or not interval_set) and backup:
                await backup.show_interval_setup(self.bot, msg.from_user.id)
                await self._db.set(_DB_KEY, "backup_interval_asked", True)
            else:
                backup_status = f"каждые <b>{interval_set} ч</b>" if interval_set else "не настроен"
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
            logger.warning("BotRunner: on_start failed — %s", e)

    async def _on_update_cb(self, call) -> None:
        owner_id = self._db.get(_DB_KEY, "owner_id", None)
                                                                              
        try:
            if call.from_user.id != owner_id:
                await call.answer("🔒 Нет доступа.", show_alert=True)
                return
            await call.answer()
        except Exception:
            return                                        
        if call.data == "update_no":
            await self._db.delete("kitsune.updater", "pending_update")
            try:
                await call.message.edit_text("❌ Обновление отменено.")
            except Exception:
                pass
            return
        try:
            await call.message.edit_text("⬇️ <b>Скачиваю обновление...</b>", parse_mode="HTML")
        except Exception:
            pass
        asyncio.ensure_future(self._safe_update_run(call.message))

    async def _safe_update_run(self, msg) -> None:
        async def edit(text: str) -> None:
            try:
                await msg.edit_text(text, parse_mode="HTML")
            except Exception:
                pass

        loader = getattr(self._client, "_kitsune_loader", None)
        notifier = loader.modules.get("notifier") if loader else None
        if not notifier:
            return
        for attempt in range(1, 4):
            try:
                await notifier._updater.do_update(msg)
                return
            except Exception as exc:
                err = str(exc)
                if any(w in err for w in ("unable to access", "Couldn't connect", "timed out")):
                    if attempt < 3:
                        await edit(f"⚠️ Нет соединения, повтор {attempt}/3...")
                        await asyncio.sleep(15)
                        continue
                await edit(f"❌ Ошибка / Error:\n<code>{err}</code>")
                return

    async def _on_backup_interval(self, call) -> None:
        owner_id = self._db.get(_DB_KEY, "owner_id", None)
        try:
            if call.from_user.id != owner_id:
                await call.answer("🔒 Нет доступа.", show_alert=True)
                return
        except Exception:
            return
        loader = getattr(self._client, "_kitsune_loader", None)
        backup = loader.modules.get("backup") if loader else None
        if backup:
            await backup.handle_interval_callback(call)
        else:
            await call.answer("Модуль backup не загружен.", show_alert=True)

    async def _on_config_cb(self, call) -> None:
        owner_id = self._db.get(_DB_KEY, "owner_id", None)
        try:
            if call.from_user.id != owner_id:
                await call.answer("🔒 Нет доступа.", show_alert=True)
                return
            await call.answer()
        except Exception:
            return

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        from ..config import _get_configurable, _mod_text, _list_text

        data = call.data

        if data == "cfg_close":
            await call.message.delete()
            return

        if data == "cfg_back":
            configurable = _get_configurable(self._client)
            buttons, row = [], []
            for name in sorted(configurable.keys()):
                row.append(InlineKeyboardButton(text=configurable[name].name, callback_data=f"cfg_mod:{name}"))
                if len(row) == 3:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            buttons.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="cfg_close")])
            await call.message.edit_text(
                _list_text(configurable),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode="HTML",
            )
            return

        if data.startswith("cfg_mod:"):
            mod_name = data.split(":", 1)[1]
            configurable = _get_configurable(self._client)
            mod = configurable.get(mod_name)
            if not mod:
                await call.message.edit_text("❌ Модуль не найден.")
                return
            buttons = [[InlineKeyboardButton(text=f"✏️ {k}", callback_data=f"cfg_key:{mod_name}:{k}")] for k in mod.config.keys()]
            buttons.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data="cfg_back"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="cfg_close"),
            ])
            await call.message.edit_text(_mod_text(mod_name, mod), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
            return

        if data.startswith("cfg_key:"):
            _, mod_name, key = data.split(":", 2)
            configurable = _get_configurable(self._client)
            mod = configurable.get(mod_name)
            if not mod or key not in mod.config:
                await call.message.edit_text("❌ Параметр не найден.")
                return
            val, default, doc = mod.config[key], mod.config.get_default(key), mod.config.get_doc(key) or "—"
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
                    InlineKeyboardButton(text="☑️ True (текущее)" if val else "✅ True", callback_data=f"cfg_set:{mod_name}:{key}:true"),
                    InlineKeyboardButton(text="☑️ False (текущее)" if not val else "❌ False", callback_data=f"cfg_set:{mod_name}:{key}:false"),
                ])
            if val != default:
                buttons.append([InlineKeyboardButton(text="🔄 Сбросить до дефолта", callback_data=f"cfg_reset:{mod_name}:{key}")])
            buttons.append([
                InlineKeyboardButton(text="◀️ Назад", callback_data=f"cfg_mod:{mod_name}"),
                InlineKeyboardButton(text="❌ Закрыть", callback_data="cfg_close"),
            ])
            await self._db.set("kitsune.config", "pending_input", {"mod": mod_name, "key": key, "msg_id": call.message.message_id, "chat_id": call.message.chat.id})
            await call.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
            return

        if data.startswith("cfg_set:"):
            _, mod_name, key, raw_val = data.split(":", 3)
            configurable = _get_configurable(self._client)
            mod = configurable.get(mod_name)
            if mod and key in mod.config:
                mod.config[key] = raw_val.lower() == "true"
                await self._db.set(f"kitsune.config.{mod_name}", "values", {k: mod.config[k] for k in mod.config.keys()})
                await call.message.edit_text(
                    f"✅ <b>{mod.name}</b> → <code>{key}</code> = <b>{mod.config[key]}</b>",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=f"cfg_mod:{mod_name}")]]),
                    parse_mode="HTML",
                )
            return

        if data.startswith("cfg_reset:"):
            _, mod_name, key = data.split(":", 2)
            configurable = _get_configurable(self._client)
            mod = configurable.get(mod_name)
            if mod and key in mod.config:
                mod.config[key] = mod.config.get_default(key)
                await self._db.set(f"kitsune.config.{mod_name}", "values", {k: mod.config[k] for k in mod.config.keys()})
                await call.message.edit_text(
                    f"✅ <b>{mod.name}</b> → <code>{key}</code> сброшен до <b>{mod.config[key]}</b>",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=f"cfg_mod:{mod_name}")]]),
                    parse_mode="HTML",
                )
            return

    async def _on_text_input(self, msg) -> None:
        owner_id = self._db.get(_DB_KEY, "owner_id", None)
        if msg.from_user.id != owner_id:
            return
        pending = self._db.get("kitsune.config", "pending_input", None)
        if not pending:
            return
        await self._db.delete("kitsune.config", "pending_input")
        mod_name, key, value = pending["mod"], pending["key"], msg.text or ""

        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        from ..config import _get_configurable
        configurable = _get_configurable(self._client)
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
        await self._db.set(f"kitsune.config.{mod_name}", "values", {k: mod.config[k] for k in mod.config.keys()})
        try:
            await self.bot.edit_message_text(
                chat_id=pending["chat_id"], message_id=pending["msg_id"],
                text=f"✅ <b>{mod.name}</b> → <code>{key}</code> = <b>{value}</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data=f"cfg_mod:{mod_name}")]]),
                parse_mode="HTML",
            )
        except Exception:
            pass
        try:
            await msg.delete()
        except Exception:
            pass
