from __future__ import annotations
import asyncio
import logging
import typing

logger = logging.getLogger(__name__)

_DB_KEY = "kitsune.notifier"

# Длина caption у фото в Telegram ограничена 1024 символами.
# Если caption длиннее — Telegram возвращает MEDIA_CAPTION_TOO_LONG,
# а нашему пользователю это видно как «бот молчит».
# Поэтому если текст приветствия длиннее лимита — отправляем
# фото без caption + текст отдельным сообщением.
_TG_CAPTION_LIMIT = 1024


def _load_socks_proxy_url() -> str | None:

    try:

        from kitsune.rkn_bypass import get_socks_proxy_url

        return get_socks_proxy_url()

    except Exception:

        return None

def _make_bot(token: str) -> typing.Any:

    from kitsune.rkn_bypass import make_aiogram_bot

    return make_aiogram_bot(str(token), parse_mode="HTML", timeout=60)

def _get_platform() -> str:

    import sys, os

    if os.path.exists("/data/data/tech.ula") or "com.termux" in os.environ.get("PREFIX", ""):

        return "📱 Android (UserLand)"

    if "ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ:

        return "📱 Android (Termux)"

    if sys.platform == "darwin" and os.path.exists("/var/mobile"):

        return "🍎 iOS (iSH)"

    try:

        release = open("/etc/os-release").read()

        if "ubuntu" in release.lower(): return "🐧 Ubuntu"

        if "debian" in release.lower(): return "🐧 Debian"

        if "alpine" in release.lower(): return "🏔 Alpine Linux"

        if "arch"   in release.lower(): return "🎯 Arch Linux"

    except Exception:

        pass

    if sys.platform.startswith("linux"):

        return "🐧 Linux"

    if sys.platform == "win32":

        return "🪟 Windows"

    if sys.platform == "darwin":

        return "🍎 macOS"

    return f"❓ {sys.platform}"

def _build_welcome_text(db) -> str:

    prefix       = db.get("kitsune.core", "prefix", ".")

    interval_set = db.get("kitsune.backup", "interval_h", None)

    backup_str   = f"каждые <b>{interval_set} ч</b>" if interval_set else "не настроен"

    platform     = _get_platform()

    return (

        "🦊 <b>Добро пожаловать в Kitsune Userbot!</b>\n"

        "Kitsune успешно запущен и готов к работе.\n\n"

        "⚡ <b>Быстрый старт:</b>\n"

        "<blockquote>"

        f"<code>{prefix}help</code> — список всех команд\n"

        f"<code>{prefix}ping</code> — проверить работу\n"

        f"<code>{prefix}cfg</code> — настройка модулей\n"

        f"<code>{prefix}dlm &lt;url&gt;</code> — установить модуль по ссылке\n"

        f"<code>{prefix}lm</code> — установить модуль файлом (ответом на файл)"

        "</blockquote>\n"

        "🔒 <b>Безопасность:</b>\n"

        "<blockquote>"

        f"<code>{prefix}security</code> — управление доступом\n"

        f"<code>{prefix}backupall</code> — полный бэкап (БД + модули)\n"

        f"<code>{prefix}setbackupinterval</code> — изменить время авто-бэкапа"

        "</blockquote>\n"

        "🗂 <b>Авто-бэкап:</b> " + backup_str + "\n\n"

        "🔗 <b>Полезные ссылки:</b>\n"

        "<blockquote>"

        "Репозиторий: github.com/KitsuneX-dev/Kitsune\n"
        "Группа Kitsune Community - https://t.me/UserBot_Kitsune\n"

        "Разработчик: @Mikasu32"

        "</blockquote>\n"

        "🎉 <i>Приятного использования!</i>\n"

        f"🖥 <b>Платформа:</b> {platform}"

    )

_LANG_OPTIONS: dict[str, str] = {
    "ru":   "🇷🇺 Русский",
    "en":   "🇬🇧 English",
    "de":   "🇩🇪 Deutsch",
    "ua":   "🇺🇦 Українська",
    "jp":   "🇯🇵 日本語",
    "uwu":  "🐾 UwU",
    "leet": "👾 1337",
}


async def _ensure_chat_with_bot(client, db) -> None:
    """Гарантирует, что у пользователя открыт диалог с ботом.

    Пока пользователь сам не написал боту /start, Telegram возвращает
    «Bad Request: chat not found», и бот не может писать первым.

    Решение — отправить /start в чат с ботом от лица user-аккаунта (через
    telethon). Это создаёт диалог, и после этого бот спокойно пишет.
    """
    try:
        bot_username = db.get(_DB_KEY, "bot_username", None)
        if not bot_username:
            return
        bot_username = str(bot_username).lstrip("@")

        # Если уже отмечали, что чат «прогрет», — не повторяем.
        if db.get(_DB_KEY, "chat_warmed_up", False):
            return

        try:
            entity = await client.get_entity(f"@{bot_username}")
            await client.send_message(entity, "/start")
            try:
                await db.set(_DB_KEY, "chat_warmed_up", True)
            except Exception:
                pass
            logger.info(
                "BotRunner: открыт диалог с @%s от лица user-аккаунта", bot_username,
            )
            # даём Telegram время «увидеть» новый чат
            await asyncio.sleep(2.0)
        except Exception as exc:
            logger.debug(
                "BotRunner: не смог открыть диалог с @%s — %s", bot_username, exc,
            )
    except Exception as exc:
        logger.debug("BotRunner: _ensure_chat_with_bot failed — %s", exc)


async def _send_welcome_with_retry(
    bot,
    client,
    db,
    owner_id: int,
    *,
    attempts: int = 4,
) -> bool:
    """Шлёт welcome владельцу с автоматическими повторами.

    Если ловим «chat not found» — пытаемся «прогреть» чат через user-аккаунт
    и повторяем. Текст всегда отправляется отдельным сообщением, потому что
    welcome легко может быть длиннее 1024 символов (caption-лимит Telegram).
    """
    from pathlib import Path as _Path
    _info = _Path(__file__).parent.parent.parent / "assets" / "kitsune_info.png"

    welcome = _build_welcome_text(db)

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            # 1) Сначала фото без caption (если файл существует),
            #    чтобы caption-limit гарантированно не выстрелил.
            if _info.exists():
                try:
                    from aiogram.types import FSInputFile
                    await bot.send_photo(
                        chat_id=int(owner_id),
                        photo=FSInputFile(str(_info)),
                    )
                except Exception as ph_exc:
                    # фото не критично — продолжаем хотя бы с текстом
                    logger.debug(
                        "BotRunner: не удалось отправить фото welcome (%s) — "
                        "шлю только текст", ph_exc,
                    )

            # 2) Затем сам текст приветствия отдельным сообщением.
            await bot.send_message(
                chat_id=int(owner_id),
                text=welcome,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        except Exception as exc:
            last_exc = exc
            err = str(exc).lower()
            if "chat not found" in err and attempt < attempts:
                logger.info(
                    "BotRunner: welcome — chat not found (попытка %d/%d), "
                    "прогреваю диалог через user-аккаунт", attempt, attempts,
                )
                await _ensure_chat_with_bot(client, db)
                await asyncio.sleep(2.0 * attempt)
                continue
            # любая другая ошибка — небольшая пауза и повтор
            if attempt < attempts:
                await asyncio.sleep(1.5)
                continue

    logger.warning(
        "BotRunner: не удалось отправить welcome: %s",
        last_exc if last_exc else "unknown error",
    )
    return False


async def _show_lang_setup(bot, owner_id: int, *, client=None, db=None) -> bool:
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    buttons, row = [], []
    for code, label in _LANG_OPTIONS.items():
        row.append(InlineKeyboardButton(text=label, callback_data=f"lang_select:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    text = (
        "🌐 <b>Выберите язык интерфейса</b>\n\n"
        "Выберите язык, который будет использоваться в командах "
        "и уведомлениях Kitsune.\n\n"
        "<i>Изменить позже:</i> <code>.setlang</code>"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)

    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            await bot.send_message(
                chat_id=int(owner_id),
                text=text,
                reply_markup=markup,
                parse_mode="HTML",
            )
            return True
        except Exception as exc:
            last_exc = exc
            err = str(exc).lower()
            if "chat not found" in err and client is not None and db is not None and attempt < 3:
                logger.info(
                    "BotRunner: lang setup — chat not found (попытка %d), "
                    "прогреваю диалог", attempt,
                )
                await _ensure_chat_with_bot(client, db)
                await asyncio.sleep(2.0)
                continue
            if attempt < 3:
                await asyncio.sleep(1.0)
                continue

    logger.warning(
        "BotRunner: не удалось отправить выбор языка: %s",
        last_exc if last_exc else "unknown error",
    )
    return False


async def _show_backup_setup(bot, client, db, owner_id: int) -> bool:
    """Шлёт сообщение с inline-кнопками выбора интервала авто-бэкапа.

    Если модуль backup загружен — используем его собственный
    `show_interval_setup` (там корректные кнопки). Если нет — шлём
    fallback-сообщение со стандартным набором интервалов.
    """
    loader = getattr(client, "_kitsune_loader", None)
    backup = loader.modules.get("backup") if loader else None

    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            if backup is not None:
                await backup.show_interval_setup(bot, int(owner_id))
            else:
                # Fallback: на случай, если модуль backup ещё не загрузился.
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                _OPTS = [2, 4, 6, 8, 12, 24, 48]
                buttons, row = [], []
                for h in _OPTS:
                    row.append(InlineKeyboardButton(
                        text=f"{h}ч",
                        callback_data=f"backup_interval:{h}",
                    ))
                    if len(row) == 4:
                        buttons.append(row)
                        row = []
                if row:
                    buttons.append(row)
                buttons.append([InlineKeyboardButton(
                    text="❌ Отключить",
                    callback_data="backup_interval:0",
                )])
                await bot.send_message(
                    chat_id=int(owner_id),
                    text=(
                        "🗂 <b>Авто-бэкап Kitsune</b>\n\n"
                        "Выбери интервал резервного копирования.\n"
                        "Бэкапы будут отправляться сюда."
                    ),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                    parse_mode="HTML",
                )
            try:
                await db.set(_DB_KEY, "backup_interval_asked", True)
            except Exception:
                pass
            return True
        except Exception as exc:
            last_exc = exc
            err = str(exc).lower()
            if "chat not found" in err and attempt < 3:
                logger.info(
                    "BotRunner: backup setup — chat not found (попытка %d), "
                    "прогреваю диалог", attempt,
                )
                await _ensure_chat_with_bot(client, db)
                await asyncio.sleep(2.0)
                continue
            if attempt < 3:
                await asyncio.sleep(1.0)
                continue

    logger.warning(
        "BotRunner: не удалось отправить настройку бэкапа: %s",
        last_exc if last_exc else "unknown error",
    )
    return False


async def _run_asset_setup(client, db) -> None:

    import asyncio as _asyncio

    if db.get("kitsune.assets", "setup_done", False):

        return

    await _asyncio.sleep(5)

    try:

        from ...assets import setup_all_avatars

        logger.debug("BotRunner: auto asset setup starting...")

        await setup_all_avatars(client, db)

        logger.debug("BotRunner: auto asset setup done")

    except Exception as _e:

        logger.debug("BotRunner: asset setup error: %s", _e, exc_info=True)

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

            from kitsune.rkn_bypass import (

                ensure_aiohttp_socks,

                get_socks_proxy_url,

                test_socks_proxy,

            )

            if get_socks_proxy_url():

                ensure_aiohttp_socks()

                ok, msg = await test_socks_proxy(timeout=15.0)

                if ok:

                    logger.info("BotRunner: SOCKS5 pre-check OK — %s", msg)

                else:

                    _soft = ("timeout", "reset", "refused", "unreachable",

                             "closed", "eof")

                    _level = (logger.info if any(k in msg.lower() for k in _soft)

                              else logger.warning)

                    _level(

                        "BotRunner: SOCKS5 pre-check soft-fail — %s. "

                        "polling всё равно будет запущен.",

                        msg,

                    )

        except Exception as _pre_exc:

            logger.debug("BotRunner: SOCKS5 pre-check skipped — %s", _pre_exc)

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

            asyncio.ensure_future(_run_asset_setup(self._client, self._db))

            if first_run:

                owner_id = self._db.get(_DB_KEY, "owner_id", None)

                if owner_id:

                    # Гарантируем, что чат с ботом открыт (иначе chat not found).
                    await _ensure_chat_with_bot(self._client, self._db)

                    # 1) Welcome (фото отдельно + текст отдельно из-за caption-лимита).
                    await _send_welcome_with_retry(
                        self.bot, self._client, self._db, int(owner_id),
                    )

                    # 2) Выбор языка (inline-кнопки).
                    await _show_lang_setup(
                        self.bot, int(owner_id),
                        client=self._client, db=self._db,
                    )

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

        @router.callback_query(lambda c: c.data and c.data.startswith("lang_select:"))

        async def on_lang_select(call: CallbackQuery) -> None:

            await ref._on_lang_select(call)

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

        # Раз пользователь сам нажал /start, чат с ботом 100% открыт.
        try:
            await self._db.set(_DB_KEY, "chat_warmed_up", True)
        except Exception:
            pass

        # При /start всегда отправляем приветствие. Делается это «по-человечески»:
        # если есть баннер kitsune_info.png — фото отдельным сообщением, а сам
        # текст — следом (caption Telegram ограничен 1024 симв., welcome длиннее).
        welcome = _build_welcome_text(self._db)

        try:
            from pathlib import Path as _Path
            _info = _Path(__file__).parent.parent.parent / "assets" / "kitsune_info.png"

            if _info.exists():
                try:
                    from aiogram.types import FSInputFile
                    await msg.answer_photo(photo=FSInputFile(str(_info)))
                except Exception as _ph_exc:
                    logger.debug("BotRunner: /start фото — %s", _ph_exc)

            await msg.answer(
                welcome,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning("BotRunner: on_start failed — %s", e)
            return

        # Если ещё не настраивали интервал авто-бэкапа — предложим прямо сейчас.
        try:
            backup_asked = self._db.get(_DB_KEY, "backup_interval_asked", False)
            interval_set = self._db.get("kitsune.backup", "interval_h", None)
            if not backup_asked and not interval_set:
                await _show_backup_setup(
                    self.bot, self._client, self._db, int(owner_id),
                )
        except Exception as e:
            logger.debug("BotRunner: on_start backup-setup follow-up — %s", e)

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

    async def _on_lang_select(self, call) -> None:

        owner_id = self._db.get(_DB_KEY, "owner_id", None)

        try:

            if owner_id is None or call.from_user.id != int(owner_id):

                await call.answer("🔒 Нет доступа.", show_alert=True)

                return

        except Exception:

            return

        lang_code = call.data.split(":", 1)[1]

        label = _LANG_OPTIONS.get(lang_code, lang_code)

        try:

            await self._db.set("kitsune.core", "lang", lang_code)

            await call.message.edit_text(

                f"✅ Язык установлен: <b>{label}</b>\n\n"

                "<i>Изменить в любой момент:</i> <code>.setlang</code>",

                parse_mode="HTML",

            )

            await call.answer()

        except Exception as _exc:

            logger.warning("BotRunner: _on_lang_select edit failed — %s", _exc)

        # Сразу после выбора языка предлагаем настроить кд авто-бэкапа.
        await _show_backup_setup(
            self.bot, self._client, self._db, int(owner_id),
        )

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
