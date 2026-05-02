from __future__ import annotations

import asyncio
import datetime
import io
import json
import logging
import os
import time
import zipfile
from pathlib import Path

from ..core.loader import KitsuneModule, command
from ..core.security import OWNER
from ..hydro_media import send_file as hydro_send_file, download_media as hydro_download
from ..utils import ProgressMessage

logger = logging.getLogger(__name__)

_DB_OWNER         = "kitsune.backup"
_DB_LOADER        = "kitsune.loader_mod"
_INTERVAL_OPTIONS = [2, 4, 6, 8, 12, 24, 48]

# Папка с пользовательскими модулями (dlmod + lm)
_USER_MODULES_DIR = Path.home() / ".kitsune" / "modules"


class BackupModule(KitsuneModule):
    name        = "backup"
    description = "Резервное копирование — без шифрования, совместимо с Hikka/Heroku"
    author      = "Yushi"

    strings_ru = {
        # backupdb
        "creating":       "⏳ Создаю резервную копию базы данных...",
        "done":           "✅ Бэкап базы данных отправлен.",
        # restoredb
        "restoring":      "⏳ Восстанавливаю базу данных...",
        "restored":       "✅ База данных восстановлена. Перезапустите бота.",
        "bad_file":       "❌ Неверный формат. Ожидается .json или .backup",
        # backupmods
        "mods_creating":  "⏳ Собираю файлы модулей...",
        "mods_done":      "✅ Бэкап модулей отправлен ({count} файлов).",
        "mods_no_mods":   "❌ Нет установленных пользовательских модулей.",
        # restoremods
        "mods_restoring": "⏳ Восстанавливаю модули...",
        "mods_restored":  "✅ Модули восстановлены: {count} шт. Перезапустите бота.",
        "mods_bad_file":  "❌ Неверный формат. Ожидается .zip или .backup",
        # backupall / restoreall
        "all_creating":   "⏳ Создаю полный бэкап (БД + все модули)...",
        "all_done":       "✅ Полный бэкап отправлен.",
        "all_restoring":  "⏳ Восстанавливаю всё из бэкапа...",
        "all_restored":   "✅ База данных и модули восстановлены. Перезапустите бота.",
        "all_bad_file":   "❌ Неверный формат .backup",
        # group / interval
        "no_dest":        "⚠️ Нет группы для бэкапа. Создаю...",
        "group_created":  "✅ Группа <b>KitsuneBackup</b> создана.",
        "setup_interval": (
            "🗂 <b>Авто-бэкап Kitsune</b>\n\n"
            "Выбери интервал резервного копирования.\n"
            "Бэкапы будут отправляться сюда."
        ),
        "interval_set":   "✅ Авто-бэкап каждые <b>{h} ч</b>.",
        "interval_off":   "🔕 Авто-бэкап отключён.",
        "interval_usage": (
            "Использование: <code>.setbackupinterval &lt;часы&gt;</code> или <code>.setbackupinterval off</code>\n"
            f"Доступные значения: 2 4 6 8 12 24 48\n"
            "Пример: <code>.setbackupinterval 6</code>"
        ),
        "interval_bad":   "❌ Неверное значение. Доступно: 2 4 6 8 12 24 48 или off",
        # captions (в сообщении Telegram)
        "db_caption": (
            "🦊 <b>Kitsune DB Backup</b>\n"
            "🕐 {ts}\n"
            "📋 Ответь: <code>.restoredb</code>"
        ),
        "mods_caption": (
            "🦊 <b>Kitsune Mods Backup</b>\n"
            "🕐 {ts}\n"
            "📦 Файлов: {count}\n"
            "📋 Ответь: <code>.restoremods</code>"
        ),
        "all_caption": (
            "🦊 <b>Kitsune Full Backup</b>\n"
            "🕐 {ts}\n"
            "📦 Файлов: {count}\n"
            "📋 Ответь: <code>.restoreall</code>"
        ),
    }

    strings = {
        "creating":       "⏳ Creating database backup...",
        "done":           "✅ Database backup sent.",
        "restoring":      "⏳ Restoring database...",
        "restored":       "✅ Database restored. Please restart.",
        "bad_file":       "❌ Invalid format. Expected .json or .backup",
        "mods_creating":  "⏳ Collecting module files...",
        "mods_done":      "✅ Modules backup sent ({count} files).",
        "mods_no_mods":   "❌ No user modules found.",
        "mods_restoring": "⏳ Restoring modules...",
        "mods_restored":  "✅ Modules restored: {count}. Please restart.",
        "mods_bad_file":  "❌ Invalid format. Expected .zip or .backup",
        "all_creating":   "⏳ Creating full backup (DB + modules)...",
        "all_done":       "✅ Full backup sent.",
        "all_restoring":  "⏳ Restoring from backup...",
        "all_restored":   "✅ Database and modules restored. Please restart.",
        "all_bad_file":   "❌ Invalid .backup format.",
        "no_dest":        "⚠️ No backup group. Creating...",
        "group_created":  "✅ Group <b>KitsuneBackup</b> created.",
        "setup_interval": "🗂 <b>Kitsune Auto-Backup</b>\n\nChoose backup interval.",
        "interval_set":   "✅ Auto-backup every <b>{h} h</b>.",
        "interval_off":   "🔕 Auto-backup disabled.",
        "interval_usage": "Usage: <code>.setbackupinterval &lt;hours&gt;</code> or <code>.setbackupinterval off</code>\nAvailable: 2 4 6 8 12 24 48",
        "interval_bad":   "❌ Invalid value. Available: 2 4 6 8 12 24 48 or off",
        "db_caption":     "🦊 <b>Kitsune DB Backup</b>\n🕐 {ts}\n📋 Reply: <code>.restoredb</code>",
        "mods_caption":   "🦊 <b>Kitsune Mods Backup</b>\n🕐 {ts}\n📦 {count} files\n📋 Reply: <code>.restoremods</code>",
        "all_caption":    "🦊 <b>Kitsune Full Backup</b>\n🕐 {ts}\n📦 {count} files\n📋 Reply: <code>.restoreall</code>",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._auto_task: asyncio.Task | None = None

    async def on_load(self) -> None:
        interval_h = self.db.get(_DB_OWNER, "interval_h", None)
        if interval_h:
            self._start_auto(int(interval_h))

    # ── Хелперы ───────────────────────────────────────────────────────────────

    def _ts(self) -> str:
        return datetime.datetime.now().strftime("%d-%m-%Y %H:%M")

    def _fname_ts(self) -> str:
        return datetime.datetime.now().strftime("%d-%m-%Y-%H-%M")

    def _db_bytes(self) -> bytes:
        """
        Plain JSON дамп всей базы данных.
        Формат совместим с Hikka и Heroku — можно восстановить любым из них.
        """
        return json.dumps(dict(self.db), ensure_ascii=False, indent=2).encode("utf-8")

    def _collect_module_files(self) -> list[tuple[str, bytes]]:
        """
        Собирает все файлы из ~/.kitsune/modules/.

        Возвращает список (filename, content).
        Включает:
          • модули загруженные через dlmod (с URL)
          • модули загруженные через lm (файл без URL)
        """
        files: list[tuple[str, bytes]] = []
        if not _USER_MODULES_DIR.exists():
            return files
        for f in sorted(_USER_MODULES_DIR.glob("*.py")):
            try:
                files.append((f.name, f.read_bytes()))
            except Exception as e:
                logger.warning("backup: не удалось прочитать %s: %s", f, e)
        return files

    def _make_mods_zip(self) -> tuple[bytes, int]:
        """
        ZIP с:
          • всеми .py файлами из ~/.kitsune/modules/  (dlmod + lm)
          • urls.json — словарь {имя_модуля: url} для dlmod-модулей
        """
        module_files = self._collect_module_files()

        # URL-список из dlmod (для переустановки через URL)
        url_map: dict = self.db.get(_DB_LOADER, "user_modules", {})

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Сохраняем каждый .py файл
            for fname, content in module_files:
                zf.writestr(f"mods/{fname}", content)
            # Сохраняем маппинг URL (нужен для восстановления через URL если файл протух)
            zf.writestr(
                "urls.json",
                json.dumps(url_map, ensure_ascii=False, indent=2),
            )

        return buf.getvalue(), len(module_files)

    def _make_full_backup(self) -> tuple[bytes, int]:
        """
        Полный .backup файл — ZIP { db.json, mods.zip }.
        Формат: как у Heroku/Hikka, без шифрования.
        """
        db_bytes            = self._db_bytes()
        mods_zip, mod_count = self._make_mods_zip()

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("db.json",  db_bytes)
            zf.writestr("mods.zip", mods_zip)

        return archive.getvalue(), mod_count

    async def _get_dest(self, event=None) -> int | None:
        """Возвращает chat_id группы KitsuneBackup (создаёт при необходимости)."""
        chat_id = self.db.get(_DB_OWNER, "group_id", None)
        if chat_id:
            try:
                await asyncio.wait_for(self.client.get_entity(int(chat_id)), timeout=20)
                return int(chat_id)
            except Exception:
                pass

        if event:
            await event.reply(self.strings("no_dest"), parse_mode="html")

        try:
            from telethon.tl.functions.channels import CreateChannelRequest
            result = await self.client(CreateChannelRequest(
                title="KitsuneBackup",
                about="🦊 Kitsune Userbot — резервные копии",
                megagroup=False,
            ))
            new_id = result.chats[0].id
            await self.db.set(_DB_OWNER, "group_id", new_id)
            if event:
                await event.reply(self.strings("group_created"), parse_mode="html")
            return new_id
        except Exception as exc:
            logger.error("backup: не удалось создать группу: %s", exc)
            return None

    @staticmethod
    def _strip_tokens(db_data: dict) -> None:
        """Убирает bot_token из всех известных namespace'ов (безопасность)."""
        for ns in ("kitsune.inline", "hikka.inline", "heroku.inline"):
            try:
                db_data.get(ns, {}).pop("bot_token", None)
            except Exception:
                pass

    # ── backupdb ──────────────────────────────────────────────────────────────

    @command("backupdb", required=OWNER)
    async def backupdb_cmd(self, event) -> None:
        """Отправить дамп базы данных как .json (plain, без шифрования)."""
        async with ProgressMessage(event, self.strings("creating")) as prog:
            data    = self._db_bytes()
            dest    = await self._get_dest(event)
            fname   = f"kitsune-db-{self._fname_ts()}.json"
            caption = self.strings("db_caption").format(ts=self._ts())

            buf = io.BytesIO(data)
            buf.name = fname
            if dest:
                await hydro_send_file(self.client, dest, buf, caption=caption, parse_mode="html")
            await hydro_send_file(self.client, "me", buf, caption=caption, parse_mode="html")
            await prog.done(self.strings("done"))

    # ── restoredb ─────────────────────────────────────────────────────────────

    @command("restoredb", required=OWNER)
    async def restoredb_cmd(self, event) -> None:
        """
        Восстановить базу данных из .json или .backup.
        Ответь на файл и введи команду.
        Работает с бэкапами Kitsune, Hikka и Heroku.
        """
        reply = await event.message.get_reply_message()
        if not reply or not reply.media:
            await event.reply(
                "❌ Ответь на файл <code>.json</code> или <code>.backup</code>",
                parse_mode="html",
            )
            return

        async with ProgressMessage(event, self.strings("restoring")) as prog:
            raw     = await hydro_download(self.client, reply)
            db_data = None

            # .backup → ZIP, достаём db.json
            if raw[:2] == b"PK":
                try:
                    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                        if "db.json" in zf.namelist():
                            db_data = json.loads(zf.open("db.json").read())
                except Exception as e:
                    logger.warning("restoredb: не смог распаковать .backup: %s", e)

            # .json → прямой дамп
            if db_data is None:
                try:
                    db_data = json.loads(raw.decode("utf-8"))
                except Exception:
                    await prog.done(self.strings("bad_file"))
                    return

            if not isinstance(db_data, dict):
                await prog.done(self.strings("bad_file"))
                return

            self._strip_tokens(db_data)
            self.db.clear()
            self.db.update(**db_data)
            await self.db.force_save()
            await prog.done(self.strings("restored"))

    # ── backupmods ────────────────────────────────────────────────────────────

    @command("backupmods", required=OWNER)
    async def backupmods_cmd(self, event) -> None:
        """
        Бэкап всех модулей (dlmod + lm) → .zip файл.
        Включает физические .py файлы — восстанавливается без интернета.
        """
        async with ProgressMessage(event, self.strings("mods_creating"), total=3) as prog:
            mods_zip, count = self._make_mods_zip()
            if count == 0:
                await prog.done(self.strings("mods_no_mods"))
                return

            dest    = await self._get_dest(event)
            fname   = f"kitsune-mods-{self._fname_ts()}.zip"
            caption = self.strings("mods_caption").format(ts=self._ts(), count=count)

            buf = io.BytesIO(mods_zip)
            buf.name = fname
            if dest:
                await hydro_send_file(self.client, dest, buf, caption=caption, parse_mode="html")
            await hydro_send_file(self.client, "me", buf, caption=caption, parse_mode="html")
            await prog.done(self.strings("mods_done").format(count=count))

    # ── restoremods ───────────────────────────────────────────────────────────

    @command("restoremods", required=OWNER)
    async def restoremods_cmd(self, event) -> None:
        """
        Восстановить модули из .zip или .backup.
        Записывает .py файлы обратно в ~/.kitsune/modules/ и перезагружает.
        """
        reply = await event.message.get_reply_message()
        if not reply or not reply.media:
            await event.reply(
                "❌ Ответь на файл <code>.zip</code> или <code>.backup</code>",
                parse_mode="html",
            )
            return

        async with ProgressMessage(event, self.strings("mods_restoring"), total=3) as prog:
            raw            = await hydro_download(self.client, reply)
            mods_zip_bytes = None

            if raw[:2] == b"PK":
                try:
                    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                        names = zf.namelist()
                        if "mods.zip" in names:
                            # .backup формат
                            mods_zip_bytes = zf.open("mods.zip").read()
                        elif any(n.startswith("mods/") for n in names) or "urls.json" in names:
                            # прямой mods.zip
                            mods_zip_bytes = raw
                except Exception as e:
                    logger.warning("restoremods: %s", e)

            if mods_zip_bytes is None:
                await prog.done(self.strings("mods_bad_file"))
                return

            count = await self._restore_mods_from_zip(mods_zip_bytes)
            await prog.done(self.strings("mods_restored").format(count=count))

    # ── backupall ─────────────────────────────────────────────────────────────

    @command("backupall", required=OWNER)
    async def backupall_cmd(self, event) -> None:
        """
        🌟 Главная команда — полный бэкап в одном .backup файле.
        Содержит: базу данных + все модули (dlmod и lm).
        После переустановки: .restoreall → всё вернётся.
        """
        async with ProgressMessage(event, self.strings("all_creating"), total=4) as prog:
            archive_bytes, count = self._make_full_backup()

            dest    = await self._get_dest(event)
            fname   = f"kitsune-{self._fname_ts()}.backup"
            caption = self.strings("all_caption").format(ts=self._ts(), count=count)

            buf = io.BytesIO(archive_bytes)
            buf.name = fname
            if dest:
                await hydro_send_file(self.client, dest, buf, caption=caption, parse_mode="html")
            await hydro_send_file(self.client, "me", buf, caption=caption, parse_mode="html")
            await prog.done(self.strings("all_done"))

    # ── restoreall ────────────────────────────────────────────────────────────

    @command("restoreall", required=OWNER)
    async def restoreall_cmd(self, event) -> None:
        """
        Восстановить ВСЁ из .backup файла.
        ✅ Работает сразу после переустановки — ключи не нужны.
        ✅ Восстанавливает и URL-модули, и загруженные через lm.
        """
        reply = await event.message.get_reply_message()
        if not reply or not reply.media:
            await event.reply("❌ Ответь на файл <code>.backup</code>", parse_mode="html")
            return

        async with ProgressMessage(event, self.strings("all_restoring"), total=5) as prog:
            raw = await hydro_download(self.client, reply)

            if raw[:2] != b"PK":
                await prog.done(self.strings("all_bad_file"))
                return

            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    names = zf.namelist()
                    if "db.json" not in names:
                        await prog.done(self.strings("all_bad_file"))
                        return

                    # ── Восстановление БД ──────────────────────────────────
                    db_data = json.loads(zf.open("db.json").read().decode("utf-8"))
                    if not isinstance(db_data, dict):
                        await prog.done(self.strings("all_bad_file"))
                        return

                    self._strip_tokens(db_data)
                    self.db.clear()
                    self.db.update(**db_data)
                    await self.db.force_save()

                    # ── Восстановление модулей ─────────────────────────────
                    if "mods.zip" in names:
                        mods_zip_bytes = zf.open("mods.zip").read()
                        await self._restore_mods_from_zip(mods_zip_bytes)

            except Exception:
                logger.exception("restoreall: ошибка")
                await prog.done(self.strings("all_bad_file"))
                return

            await prog.done(self.strings("all_restored"))

    # ── setbackupinterval ─────────────────────────────────────────────────────

    @command("setbackupinterval", required=OWNER)
    async def setbackupinterval_cmd(self, event) -> None:
        """
        Изменить интервал авто-бэкапа прямо из чата.
        Примеры:
            .setbackupinterval 6    — каждые 6 часов
            .setbackupinterval off  — отключить авто-бэкап
        """
        dispatcher = getattr(self.client, "_kitsune_dispatcher", None)
        prefix     = dispatcher._prefix if dispatcher else "."
        raw        = event.message.text[len(prefix):].split(maxsplit=1)
        arg        = raw[1].strip().lower() if len(raw) > 1 else ""

        if not arg:
            current = self.db.get(_DB_OWNER, "interval_h", None)
            status  = f"каждые <b>{current} ч</b>" if current else "отключён"
            await event.reply(
                f"🗂 Авто-бэкап сейчас: {status}\n\n"
                + self.strings("interval_usage"),
                parse_mode="html",
            )
            return

        # Отключение
        if arg in ("off", "0", "no", "disable", "выкл", "отключить"):
            if self._auto_task and not self._auto_task.done():
                self._auto_task.cancel()
            await self.db.delete(_DB_OWNER, "interval_h")
            await event.reply(self.strings("interval_off"), parse_mode="html")
            return

        # Числовое значение
        try:
            h = int(arg)
        except ValueError:
            await event.reply(self.strings("interval_bad"), parse_mode="html")
            return

        if h not in _INTERVAL_OPTIONS:
            await event.reply(self.strings("interval_bad"), parse_mode="html")
            return

        await self.db.set(_DB_OWNER, "interval_h", h)
        await self.db.set(_DB_OWNER, "last_backup", int(time.time()))
        self._start_auto(h)
        await event.reply(self.strings("interval_set").format(h=h), parse_mode="html")

        # ── Внутренний restore модулей ────────────────────────────────────────────

    async def _restore_mods_from_zip(self, mods_zip_bytes: bytes) -> int:
        """
        Записывает .py файлы в ~/.kitsune/modules/ и перезагружает их.
        Возвращает количество восстановленных файлов.
        """
        _USER_MODULES_DIR.mkdir(parents=True, exist_ok=True)
        loader_inst = getattr(self.client, "_kitsune_loader", None)
        count = 0

        try:
            with zipfile.ZipFile(io.BytesIO(mods_zip_bytes)) as zf:
                names = zf.namelist()

                # Обновляем url_map в БД если есть urls.json
                if "urls.json" in names:
                    try:
                        url_map = json.loads(zf.open("urls.json").read().decode("utf-8"))
                        if isinstance(url_map, dict):
                            await self.db.set(_DB_LOADER, "user_modules", url_map)
                    except Exception as e:
                        logger.warning("restoremods: urls.json: %s", e)

                # Записываем .py файлы
                for name in names:
                    if not name.endswith(".py"):
                        continue

                    # Поддерживаем оба формата: mods/file.py и просто file.py
                    fname = Path(name).name
                    dest_path = _USER_MODULES_DIR / fname

                    try:
                        dest_path.write_bytes(zf.open(name).read())
                        count += 1
                    except Exception as e:
                        logger.error("restoremods: запись %s: %s", fname, e)
                        continue

                    # Перезагружаем модуль если лоадер доступен
                    if loader_inst:
                        try:
                            await loader_inst.load_from_file(dest_path)
                        except Exception as e:
                            logger.warning("restoremods: загрузка %s: %s", fname, e)

        except Exception:
            logger.exception("restoremods: ошибка при разборе mods.zip")

        return count

    # ── Авто-бэкап ────────────────────────────────────────────────────────────

    def _start_auto(self, interval_h: int) -> None:
        if self._auto_task and not self._auto_task.done():
            self._auto_task.cancel()
        self._auto_task = asyncio.ensure_future(self._auto_loop(interval_h))

    async def _auto_loop(self, interval_h: int) -> None:
        interval_sec = interval_h * 3_600
        while True:
            last = self.db.get(_DB_OWNER, "last_backup", 0)
            wait = max(0, last + interval_sec - time.time())
            await asyncio.sleep(wait)
            try:
                dest = await self._get_dest()
                if not dest:
                    await asyncio.sleep(60)
                    continue

                ts  = self._ts()
                fts = self._fname_ts()

                # ── 1. db.json ────────────────────────────────────────────────
                db_buf = io.BytesIO(self._db_bytes())
                db_buf.name = f"kitsune-db-{fts}.json"
                await hydro_send_file(
                    self.client, dest, db_buf,
                    caption=self.strings("db_caption").format(ts=ts),
                    parse_mode="html",
                )

                # ── 2. mods.zip ───────────────────────────────────────────────
                mods_data, count = self._make_mods_zip()
                mods_buf = io.BytesIO(mods_data)
                mods_buf.name = f"kitsune-mods-{fts}.zip"
                await hydro_send_file(
                    self.client, dest, mods_buf,
                    caption=self.strings("mods_caption").format(ts=ts, count=count),
                    parse_mode="html",
                )

                # ── 3. .backup (полный архив db + mods) ───────────────────────
                full_data, count = self._make_full_backup()
                full_buf = io.BytesIO(full_data)
                full_buf.name = f"kitsune-{fts}.backup"
                await hydro_send_file(
                    self.client, dest, full_buf,
                    caption=self.strings("all_caption").format(ts=ts, count=count),
                    parse_mode="html",
                )

                await self.db.set(_DB_OWNER, "last_backup", int(time.time()))
                logger.info("backup: авто-бэкап выполнен — db.json + mods.zip + .backup (%s)", fts)
            except Exception:
                logger.exception("backup: авто-бэкап упал")
                await asyncio.sleep(60)

    # ── Настройка интервала (вызывается из bot_setup) ─────────────────────────

    async def show_interval_setup(self, bot, owner_id: int) -> None:
        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            buttons, row = [], []
            for h in _INTERVAL_OPTIONS:
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
                chat_id=owner_id,
                text=self.strings("setup_interval"),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
                parse_mode="HTML",
            )
        except Exception as _exc:
            if "Forbidden" in type(_exc).__name__ or "forbidden" in str(_exc).lower():
                logger.warning(
                    "Backup: бот не может начать диалог с owner_id=%s. "
                    "Напиши /start боту в Telegram. (%s)", owner_id, _exc,
                )
            else:
                logger.exception("Backup: failed to send interval setup")

    async def on_callback(self, call) -> None:
        if not call.data.startswith("backup_interval:"):
            return
        h = int(call.data.split(":")[1])
        if h == 0:
            if self._auto_task and not self._auto_task.done():
                self._auto_task.cancel()
            await self.db.delete(_DB_OWNER, "interval_h")
            await call.message.edit_text(self.strings("interval_off"), parse_mode="HTML")
            return
        await self.db.set(_DB_OWNER, "interval_h", h)
        await self.db.set(_DB_OWNER, "last_backup", int(time.time()))
        self._start_auto(h)
        await call.message.edit_text(self.strings("interval_set").format(h=h), parse_mode="HTML")
