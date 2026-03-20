"""
Kitsune built-in: Notifier
Авто-создание бота, уведомления, авто-бэкап по расписанию.
Команды: .resetbot
"""

# © Yushi (@Mikasu32), 2024-2026
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import asyncio
import logging
import re
import os

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_OWNER       = "kitsune.notifier"
_CHECK_INTERVAL = 30  # секунд между проверками обновлений


def _extract_buttons(message) -> list[str]:
    """
    Вытащить текст всех inline-кнопок из сообщения BotFather.
    BotFather на /mybots присылает кнопки вида "@kitsune_123_bot".
    Telethon хранит их в message.reply_markup.rows[].buttons[].text
    """
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
            "🆕 Доступно обновление!\n"
            "Текущая версия: <code>{current}</code>\n"
            "Новая версия: <code>{new}</code>\n\n"
            "<b>Изменения:</b>\n{changes}"
        ),
        "updating":    "⏳ Обновляю Kitsune...",
        "update_done": "✅ Обновление завершено! Перезапускаю...",
        "update_err":  "❌ Ошибка:\n<code>{err}</code>",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._bot:          object | None = None
        self._dp:           object | None = None
        self._polling_task: asyncio.Task | None = None
        self._check_task:   asyncio.Task | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def on_load(self) -> None:
        # 1. Токен из config.toml имеет приоритет (восстановление замороженного бота)
        config_token = self._load_token_from_config()
        if config_token:
            await self.db.set(_DB_OWNER, "bot_token", config_token)
            logger.info("Notifier: token loaded from config.toml")

        token = self.db.get(_DB_OWNER, "bot_token", None)

        if token:
            # Бот уже есть — подключаемся.
            # Проверяем отдельно — спрашивали ли уже про интервал бэкапа.
            # Это нужно для тех кто обновился со старой версии без авто-бэкапа.
            backup_asked = self.db.get(_DB_OWNER, "backup_interval_asked", False)
            asyncio.ensure_future(self._start_polling(
                str(token), first_run=not backup_asked
            ))
            self._check_task = asyncio.ensure_future(self._update_check_loop())
        else:
            # Первый запуск — ищем существующего бота или создаём нового
            asyncio.ensure_future(self._auto_setup())

    async def on_unload(self) -> None:
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
        await self._stop_polling()

    # ── Commands ──────────────────────────────────────────────────────────────

    @command("resetbot", required=OWNER)
    async def resetbot_cmd(self, event) -> None:
        """.resetbot — сбросить бота (будет найден/создан заново при перезапуске)"""
        await self.db.delete(_DB_OWNER, "bot_token")
        await self.db.delete(_DB_OWNER, "bot_name")
        await self.db.delete(_DB_OWNER, "bot_username")
        await self._stop_polling()
        await event.reply(self.strings("reset_done"), parse_mode="html")

    @command("mybots", required=OWNER)
    async def mybots_cmd(self, event) -> None:
        """.mybots — показать список ботов Kitsune на этом аккаунте"""
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
        """.setbot @username — выбрать какого бота использовать"""
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

            # Останавливаем текущий polling
            await self._stop_polling()

            # Сохраняем новый токен
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

    # ── Auto setup ────────────────────────────────────────────────────────────

    async def _auto_setup(self) -> None:
        """
        Логика первого запуска:
        1. Проверяем — есть ли уже бот созданный под этот tg_id в БД другого устройства
           (токен мог прийти через sync БД или config.toml).
        2. Если нет — создаём нового через BotFather.
        3. Помечаем этот tg_id как «уже настроенный».
        """
        try:
            me = await self.client.get_me()
            logger.info("Notifier: first run for tg_id=%d", me.id)

            # Сохраняем tg_id — по нему потом определяем «свой» аккаунт
            await self.db.set(_DB_OWNER, "owner_tg_id", me.id)

            bot_name = f"Kitsune {me.first_name}"
            token    = None
            reused   = False

            # Пробуем найти существующего бота через BotFather (список My Bots)
            token, bot_username = await self._find_existing_bot(me.id)
            if token:
                reused = True
                logger.info("Notifier: found existing bot @%s", bot_username)
            else:
                # Создаём нового
                token, bot_username = await self._create_bot(me, bot_name)

            if not token:
                logger.error("Notifier: failed to get token")
                return

            await self.db.set(_DB_OWNER, "bot_token",    token)
            await self.db.set(_DB_OWNER, "bot_name",     bot_name)
            await self.db.set(_DB_OWNER, "bot_username", bot_username or "")
            await self.db.set(_DB_OWNER, "owner_id",     me.id)
            self._save_token_to_config(token)

            # Уведомляем пользователя в Saved Messages
            key = "reused" if reused else "done"
            await self.client.send_message(
                "me",
                self.strings(key).format(name=bot_name),
                parse_mode="html",
            )

            # Запускаем polling — first_run=True чтобы показать выбор интервала бэкапа
            asyncio.ensure_future(self._start_polling(token, first_run=not reused))
            self._check_task = asyncio.ensure_future(self._update_check_loop())

        except asyncio.TimeoutError:
            logger.warning("Notifier: BotFather timed out, retry on next restart")
        except Exception:
            logger.exception("Notifier: auto setup failed")

    async def _list_kitsune_bots(self) -> list[tuple[str, str | None]]:
        """
        Получить список всех ботов через /mybots у BotFather.
        BotFather отвечает inline-кнопками — читаем их, а не text.
        Возвращает [(username, token_or_None), ...]
        """
        import re as _re
        results = []
        try:
            async with self.client.conversation("@BotFather", timeout=40) as conv:
                await conv.send_message("/mybots")
                resp = await conv.get_response()

                # BotFather присылает кнопки вида "@kitsune_123_bot"
                # Читаем из reply_markup
                usernames = _extract_buttons(resp)
                if not usernames:
                    # fallback: попробуем из текста (старые версии BotFather)
                    usernames = _re.findall(r"@([a-zA-Z0-9_]+bot)", resp.text or "", _re.IGNORECASE)

                for uname in usernames:
                    uname = uname.lstrip("@")
                    try:
                        # BotFather после @username сразу присылает меню с токеном
                        await conv.send_message(f"@{uname}")
                        menu_resp = await conv.get_response()
                        token_text = menu_resp.text or ""
                        m = _re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", token_text)
                        if m:
                            results.append((uname, m.group(1)))
                        else:
                            # Токена в меню нет — запрашиваем явно
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
        """Получить токен конкретного бота через BotFather."""
        import re as _re
        username = username.lstrip("@")
        try:
            async with self.client.conversation("@BotFather", timeout=20) as conv:
                await conv.send_message(f"@{username}")
                menu_resp = await conv.get_response()
                # BotFather иногда сразу присылает токен в меню бота
                token_text = menu_resp.text or ""
                m = _re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", token_text)
                if m:
                    return m.group(1)
                # Токена в меню нет — запрашиваем явно через /token
                await conv.send_message("/token")
                token_resp = await conv.get_response()
                token_text2 = token_resp.text or ""
                m2 = _re.search(r"(\d{8,}:[A-Za-z0-9_-]{35,})", token_text2)
                return m2.group(1) if m2 else None
        except Exception as exc:
            logger.debug("Notifier: _get_token_for_bot failed — %s", exc)
            return None

    async def _find_existing_bot(self, tg_id: int) -> tuple[str | None, str | None]:
        """
        Спрашиваем BotFather /mybots — ищем бота с именем kitsune_{tg_id}.
        Если находим — берём его токен через /token.
        """
        try:
            async with self.client.conversation("@BotFather", timeout=20) as conv:
                await conv.send_message("/mybots")
                resp = await conv.get_response()
                text = resp.text or ""

                # Ищем username вида kitsune_<tg_id>..._bot
                pattern = rf"kitsune_{tg_id}[a-z0-9_]*_bot"
                match   = re.search(pattern, text, re.IGNORECASE)
                if not match:
                    return None, None

                username = match.group(0)

                # Нажимаем кнопку с ботом или отправляем его username
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
        """Создать нового бота через BotFather."""
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

    # ── Config helpers ────────────────────────────────────────────────────────

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

    # ── Polling ───────────────────────────────────────────────────────────────

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
                        # Первый запуск — сразу показываем выбор интервала
                        await backup.show_interval_setup(ref._bot, msg.from_user.id)
                        await ref.db.set(_DB_OWNER, "backup_interval_asked", True)
                    else:
                        # Повторный /start — показываем статус
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

            # ── Callback: обновление (из .update) ────────────────────────────
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

                pending = ref.db.get("kitsune.updater", "pending_update", None)
                if not pending:
                    await call.message.edit_text("❌ Данные устарели. Запусти .update снова.")
                    return
                await ref.db.delete("kitsune.updater", "pending_update")
                await call.message.edit_text("⬇️ Скачиваю обновление...")
                try:
                    await ref._do_update()
                except Exception as exc:
                    await call.message.edit_text(f"❌ Ошибка:\n<code>{exc}</code>")

            # ── Callback: интервал авто-бэкапа ───────────────────────────────
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

            self._polling_task = asyncio.ensure_future(
                self._dp.start_polling(self._bot, handle_signals=False)
            )
            logger.info("Notifier: polling started (first_run=%s)", first_run)

            # Если первый запуск — показываем выбор интервала бэкапа
            if first_run:
                owner_id = self.db.get(_DB_OWNER, "owner_id", None)
                if owner_id:
                    await asyncio.sleep(2)  # дать время polling'у стартовать
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

    # ── Update check loop ─────────────────────────────────────────────────────

    async def _update_check_loop(self) -> None:
        # Первая проверка через 5 минут после старта
        await asyncio.sleep(300)
        while True:
            try:
                await self._check_for_updates()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Notifier: update check failed")
            await asyncio.sleep(600)  # раз в 10 минут

    async def _check_for_updates(self) -> None:
        """
        Проверка обновлений через GitPython напрямую — как делает Hikka.

        Алгоритм Hikka (update_notifier.py):
          1. repo.remotes → remote.fetch()   — подтягиваем refs без checkout
          2. repo.git.log("HEAD..origin/branch", "--oneline") — список новых коммитов
          3. next(repo.iter_commits("origin/branch", max_count=1)).hexsha — latest SHA

        Никакого GitHub API, никакого aiohttp, никакого прокси.
        GitPython использует системный git, который уже настроен на работу
        через тот же канал что и Telethon (MTProto не нужен для git over HTTPS).
        """
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

        # Подтягиваем refs со всех remote (как у Hikka: for remote in repo.remotes)
        try:
            for remote in repo.remotes:
                remote.fetch()
        except Exception as exc:
            logger.debug("Notifier: git fetch failed — %s", exc)
            return

        # Проверяем есть ли новые коммиты (как у Hikka: repo.git.log([...]))
        try:
            diff = repo.git.log([f"HEAD..origin/{branch}", "--oneline"])
        except Exception as exc:
            logger.debug("Notifier: git log failed — %s", exc)
            return

        if not diff:
            return  # всё актуально

        # Получаем SHA последнего коммита на remote (как у Hikka: iter_commits)
        try:
            remote_sha = next(
                repo.iter_commits(f"origin/{branch}", max_count=1)
            ).hexsha
        except Exception:
            return

        # Уже уведомляли об этом коммите?
        if remote_sha == self.db.get(_DB_OWNER, "last_notified_commit", None):
            return

        await self.db.set(_DB_OWNER, "last_notified_commit", remote_sha)

        # Формируем список изменений (как у Hikka: diff.splitlines()[:10])
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
        await self.notify_update(
            current=__version_str__,
            new=f"{__version_str__}+{count}",
            changes=changes,
        )

    def _make_bot(self, token: str) -> "Bot":
        """Создать Bot с базовой сессией — без прокси, как у Hikka."""
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from aiogram.client.session.aiohttp import AiohttpSession

        return Bot(
            token=str(token),
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            session=AiohttpSession(timeout=30),
        )

    # ── Public API ────────────────────────────────────────────────────────────

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

    async def notify_update(self, current: str, new: str, changes: str = "") -> None:
        token    = self.db.get(_DB_OWNER, "bot_token", None)
        owner_id = self.db.get(_DB_OWNER, "owner_id",  None)
        if not token or not owner_id:
            return
        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            bot = self._make_bot(str(token))
            kb  = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⬆️ Обновить", callback_data="do_update"),
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

    # ── Update logic ──────────────────────────────────────────────────────────

    async def _do_update(self) -> None:
        import sys
        repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        try:
            import git
            repo   = git.Repo(repo_path)
            origin = repo.remote("origin")
            origin.fetch()
            try:
                branch = repo.active_branch.name
            except TypeError:
                branch = "main"
            repo.git.reset("--hard", f"origin/{branch}")
        except Exception as exc:
            raise RuntimeError(f"Git update failed: {exc}") from exc

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
            "--quiet", cwd=repo_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode()[:300])

        await asyncio.sleep(1)
        os.execl(sys.executable, sys.executable, "-m", "kitsune")
