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



async def _ensure_kitsune_folder(client, *peer_ids: int) -> None:
    """
    Создаёт папку «Kitsune» если её нет, и добавляет туда переданные чаты.
    Использует низкоуровневый API Telethon (DialogFilter).
    """
    from telethon.tl.functions.messages import (
        GetDialogFiltersRequest,
        UpdateDialogFilterRequest,
    )
    from telethon.tl.types import (
        DialogFilter,
        InputPeerChannel,
        InputPeerChat,
    )

    FOLDER_NAME = "Kitsune"

    # Получаем текущие папки
    filters = await client(GetDialogFiltersRequest())
    existing: DialogFilter | None = None
    max_id = 2  # id=1 зарезервирован Telegram, наши папки начинаются с 2

    for f in filters.filters:
        fid = getattr(f, "id", 0)
        if fid > max_id:
            max_id = fid
        title = getattr(f, "title", None)
        if title == FOLDER_NAME:
            existing = f
            break

    # Конвертируем peer_ids → InputPeer
    new_peers = []
    for pid in peer_ids:
        try:
            entity = await client.get_entity(pid)
            eid = getattr(entity, "id", None)
            ah  = getattr(entity, "access_hash", 0)
            if eid:
                new_peers.append(InputPeerChannel(channel_id=eid, access_hash=ah or 0))
        except Exception:
            pass

    if existing:
        # Добавляем в существующую папку если peer ещё не там
        current_ids = {
            getattr(p, "channel_id", None) or getattr(p, "chat_id", None)
            for p in getattr(existing, "include_peers", [])
        }
        to_add = [
            p for p in new_peers
            if (getattr(p, "channel_id", None) or getattr(p, "chat_id", None)) not in current_ids
        ]
        if not to_add:
            return  # уже есть
        existing.include_peers = list(getattr(existing, "include_peers", [])) + to_add
        await client(UpdateDialogFilterRequest(id=existing.id, filter=existing))
        logger.debug("_ensure_kitsune_folder: добавлено %d чатов в папку Kitsune", len(to_add))
    else:
        # Создаём папку заново
        new_filter = DialogFilter(
            id=max_id + 1,
            title=FOLDER_NAME,
            pinned_peers=[],
            include_peers=new_peers,
            exclude_peers=[],
            contacts=False,
            non_contacts=False,
            groups=False,
            broadcasts=False,
            bots=False,
            exclude_muted=False,
            exclude_read=False,
            exclude_archived=False,
            emoticon="🦊",
        )
        await client(UpdateDialogFilterRequest(id=new_filter.id, filter=new_filter))
        logger.debug("_ensure_kitsune_folder: создана папка Kitsune с %d чатами", len(new_peers))


def _to_bot_chat_id(chat_id) -> int | None:
    """
    Нормализует chat_id к формату, который понимает Telegram Bot API
    (aiogram / pyrogram-bot).

    Правила:
      • -100XXXXXXXXXX  — уже супергруппа/канал в bot-формате → как есть.
      • отрицательное «короткое» (-XXXXXXXXX) — обычный chat (legacy) → как есть.
      • положительное < 1_000_000_000 — user_id → как есть.
      • положительное «большое» (Telethon raw channel_id, обычно 10+ цифр)
        → дописываем префикс -100.

    Возвращает int либо None, если нормализовать невозможно.
    """
    if chat_id is None:
        return None
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return None

    # Уже в bot-формате
    if cid < 0:
        return cid

    s = str(cid)
    # Уже содержит префикс 100 в положительном виде (редкий кейс)
    if s.startswith("100") and len(s) >= 13:
        return -cid

    # Эвристика: всё, что > 1_000_000_000 и не похоже на user_id, считаем
    # «голым» channel_id из Telethon → дописываем -100.
    # Современные user_id тоже могут перевалить за 1e9, поэтому ориентируемся
    # на типичную длину channel_id (обычно 10 цифр и больше).
    if cid > 1_000_000_000:
        return int(f"-100{cid}")

    # user_id — отдаём как есть
    return cid


def _extract_msg_ids(sent) -> tuple[int | None, int | None]:
    """
    Унифицировано достаёт (chat_id, msg_id) из объекта Message,
    возвращённого Hydrogram или Telethon.

    chat_id всегда возвращается в формате Bot API (-100… для каналов).
    """
    if sent is None:
        return None, None

    msg_id = getattr(sent, "id", None)

    chat_id = None
    chat_obj = getattr(sent, "chat", None)  # Hydrogram
    if chat_obj is not None:
        chat_id = getattr(chat_obj, "id", None)

    if chat_id is None:
        chat_id = getattr(sent, "chat_id", None)  # Telethon

    if chat_id is None:
        peer = getattr(sent, "peer_id", None)
        if peer is not None:
            chat_id = (
                getattr(peer, "channel_id", None)
                or getattr(peer, "chat_id", None)
                or getattr(peer, "user_id", None)
            )
            # Каналы в Telethon отдают «голый» id — приводим к -100…
            if chat_id and getattr(peer, "channel_id", None):
                chat_id = int(f"-100{chat_id}")

    # Финальная нормализация (на случай если пришло «голое» положительное)
    chat_id = _to_bot_chat_id(chat_id)
    return chat_id, msg_id


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
            "Доступные значения: 2 4 6 8 12 24 48\n"
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
        # restore button
        "restore_btn":     "🔄 Восстановить",
        "restore_form_db": (
            "🦊 <b>Управление бэкапом БД</b>\n"
            "🕐 {ts}\n\n"
            "Нажми кнопку, чтобы восстановить базу данных из этого бэкапа."
        ),
        "restore_form_mods": (
            "🦊 <b>Управление бэкапом модулей</b>\n"
            "🕐 {ts}\n"
            "📦 Файлов: {count}\n\n"
            "Нажми кнопку, чтобы восстановить модули из этого бэкапа."
        ),
        "restore_form_all": (
            "🦊 <b>Управление полным бэкапом</b>\n"
            "🕐 {ts}\n"
            "📦 Файлов: {count}\n\n"
            "Нажми кнопку, чтобы восстановить БД и модули из этого бэкапа."
        ),
        "restore_alert":   "⏳ Восстанавливаю...",
        "restore_done_db":   "✅ База данных восстановлена из бэкапа.\n🕐 {ts}\n♻️ Перезапустите бота.",
        "restore_done_mods": "✅ Модули восстановлены ({count} шт.).\n🕐 {ts}\n♻️ Перезапустите бота.",
        "restore_done_all":  "✅ Полное восстановление выполнено ({count} модулей).\n🕐 {ts}\n♻️ Перезапустите бота.",
        "restore_fail":      "❌ Не удалось восстановить: {err}",
        "restore_lost":      "❌ Не нашёл исходный файл бэкапа в чате.",
    }

    strings_en = {
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
        "restore_btn":      "🔄 Restore",
        "restore_form_db":  "🦊 <b>DB Backup management</b>\n🕐 {ts}\n\nTap the button to restore the database from this backup.",
        "restore_form_mods":"🦊 <b>Mods Backup management</b>\n🕐 {ts}\n📦 {count} files\n\nTap the button to restore modules from this backup.",
        "restore_form_all": "🦊 <b>Full Backup management</b>\n🕐 {ts}\n📦 {count} files\n\nTap the button to restore everything from this backup.",
        "restore_alert":    "⏳ Restoring...",
        "restore_done_db":  "✅ Database restored from backup.\n🕐 {ts}\n♻️ Please restart.",
        "restore_done_mods":"✅ Modules restored ({count}).\n🕐 {ts}\n♻️ Please restart.",
        "restore_done_all": "✅ Full restore done ({count} modules).\n🕐 {ts}\n♻️ Please restart.",
        "restore_fail":     "❌ Restore failed: {err}",
        "restore_lost":     "❌ Original backup file not found in chat.",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._auto_task: asyncio.Task | None = None

    async def on_load(self) -> None:
        interval_h = self.db.get(_DB_OWNER, "interval_h", None)
        if interval_h:
            val = interval_h if interval_h == "1m" else int(interval_h)
            self._start_auto(val)

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
        # Фикс: dict(self.db) вызывает __getitem__ с int-ключами → KeyError.
        # export_data() возвращает правильный dict {owner: {key: value}}.
        if hasattr(self.db, "export_data"):
            data = self.db.export_data()
        else:
            data = {k: dict(v) for k, v in self.db._data.items()}
        return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

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
        """
        Возвращает chat_id группы KitsuneBackup.
        Порядок:
          1. Берём сохранённый group_id из БД и проверяем что он живой
          2. Ищем группу с названием KitsuneBackup среди всех диалогов
          3. Только если не нашли — создаём новую
          4. Добавляем группу в папку Kitsune (создаём папку если нет)
        """
        # ── 1. Проверяем сохранённый ID ───────────────────────────────────────
        chat_id = self.db.get(_DB_OWNER, "group_id", None)
        if chat_id:
            try:
                # get_entity Telethon принимает любой формат — bot и raw.
                entity = await asyncio.wait_for(
                    self.client.get_entity(int(chat_id)), timeout=20
                )
                # Нормализуем к bot-формату (-100…) — это и есть тот ID,
                # который потом уйдёт в aiogram-бота.
                normalized = _to_bot_chat_id(int(chat_id))
                # Если в БД лежит «голый» raw-id, перезаписываем актуальным,
                # иначе bot.send_document будет падать с chat not found.
                if normalized is not None and normalized != int(chat_id):
                    try:
                        await self.db.set(_DB_OWNER, "group_id", int(normalized))
                        logger.debug(
                            "backup: group_id мигрирован %s → %s",
                            chat_id, normalized,
                        )
                    except Exception:
                        pass
                final_id = int(normalized) if normalized is not None else int(chat_id)
                await self._ensure_bot_in_channel(final_id)
                return final_id
            except Exception:
                logger.debug("backup: сохранённый group_id %s недоступен — ищем заново", chat_id)

        # ── 2. Ищем KitsuneBackup в диалогах ─────────────────────────────────
        found_id: int | None = None
        try:
            async for dialog in self.client.iter_dialogs(limit=500):
                if (dialog.title or "").strip() == "KitsuneBackup":
                    entity = dialog.entity
                    cid = getattr(entity, "id", None)
                    if cid:
                        if getattr(entity, "megagroup", False) or getattr(entity, "broadcast", False):
                            found_id = int(f"-100{cid}")
                        else:
                            found_id = -cid
                        logger.info("backup: нашли существующий KitsuneBackup id=%s", found_id)
                        break
        except Exception as e:
            logger.warning("backup: ошибка поиска KitsuneBackup: %s", e)

        if found_id:
            await self.db.set(_DB_OWNER, "group_id", found_id)
            await self._ensure_bot_in_channel(found_id)
            return found_id

        # ── 3. Создаём новую группу ───────────────────────────────────────────
        if event:
            await event.reply(self.strings("no_dest"), parse_mode="html")

        new_id: int | None = None
        try:
            from telethon.tl.functions.channels import CreateChannelRequest
            result = await self.client(CreateChannelRequest(
                title="KitsuneBackup",
                about="🦊 Kitsune Userbot — резервные копии",
                megagroup=False,
            ))
            entity = result.chats[0]
            new_id = int(f"-100{entity.id}")
            await self.db.set(_DB_OWNER, "group_id", new_id)
            if event:
                await event.reply(self.strings("group_created"), parse_mode="html")
            logger.info("backup: создана группа KitsuneBackup id=%s", new_id)
        except Exception as exc:
            logger.error("backup: не удалось создать KitsuneBackup: %s", exc)
            return None

        # ── 4. Бот в канале + Аватарка + папка Kitsune ───────────────────────
        if new_id:
            await self._ensure_bot_in_channel(new_id)
            try:
                from ..assets import ensure_channel_photo, BACKUP_AVATAR
                await ensure_channel_photo(self.client, self.db, new_id, BACKUP_AVATAR)
            except Exception as e:
                logger.debug("backup: аватарка не установлена: %s", e)
            try:
                await _ensure_kitsune_folder(self.client, new_id)
            except Exception as e:
                logger.debug("backup: не удалось добавить в папку Kitsune: %s", e)

        return new_id

    async def _ensure_bot_in_channel(self, channel_id: int) -> None:
        """
        Добавляет aiogram-бота как администратора в KitsuneBackup.
        Это обязательно — иначе bot.send_document() упадёт с Forbidden
        и кнопка «🔄 Восстановить» не прикрепится к файлу.
        """
        inline = self._inline()
        if not inline or not getattr(inline, "_bot", None):
            return
        try:
            from telethon.tl.functions.channels import InviteToChannelRequest, EditAdminRequest
            from telethon.tl.types import ChatAdminRights

            bot_me = await inline._bot.get_me()
            bot_username = bot_me.username

            entity = await self.client.get_entity(channel_id)

            # Приглашаем (игнорируем если уже в чате)
            try:
                await self.client(InviteToChannelRequest(channel=entity, users=[bot_username]))
            except Exception:
                pass

            # Даём права на публикацию и редактирование
            await self.client(EditAdminRequest(
                channel=entity,
                user_id=bot_username,
                admin_rights=ChatAdminRights(
                    post_messages=True,
                    edit_messages=True,
                    delete_messages=True,
                ),
                rank="",
            ))
            logger.debug("backup: бот @%s добавлен в KitsuneBackup как админ", bot_username)
        except Exception as exc:
            logger.warning("backup: не удалось добавить бота в KitsuneBackup: %s", exc)

    @staticmethod
    def _strip_tokens(db_data: dict) -> None:
        """Убирает bot_token из всех известных namespace'ов (безопасность)."""
        for ns in ("kitsune.inline", "hikka.inline", "heroku.inline"):
            try:
                db_data.get(ns, {}).pop("bot_token", None)
            except Exception:
                pass

    # ── Кнопка «Восстановить» под бэкапом ─────────────────────────────────────

    def _inline(self):
        return getattr(self.client, "_kitsune_inline", None)

    def _register_restore_cb(self, chat_id: int, msg_id: int, kind: str) -> str:
        """
        Регистрирует обработчик кнопки «🔄 Восстановить» в InlineManager
        в том же формате, что и `cfg`/`config` (5-tuple), и возвращает cb_id
        для использования в callback_data.
        """
        inline = self._inline()
        import uuid as _uuid
        cb_id = str(_uuid.uuid4())[:12]
        inline._callbacks[cb_id] = (
            self._cb_restore,
            (int(chat_id), int(msg_id), kind),
            self.client.tg_id,
            False,
            {},
        )
        return cb_id

    def _build_restore_markup(self, cb_id: str):
        """Aiogram-разметка с одной кнопкой «🔄 Восстановить»."""
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(
                text=self.strings("restore_btn"),
                callback_data=cb_id,
            ),
        ]])

    async def _send_with_button_via_bot(
        self,
        dest: int,
        data: bytes,
        fname: str,
        caption: str,
        kind: str,
        ts: str,
        count: int = 0,
    ) -> bool:
        """
        Отправляет файл бэкапа через aiogram-бота с прикреплённой
        инлайн-кнопкой «🔄 Восстановить» в одном сообщении
        (документ + caption + кнопка) — ровно как просит пользователь.

        Возвращает True если получилось, False — иначе (тогда вызывающая сторона
        пробует fallback: юзербот + bot.edit_message_reply_markup).
        """
        inline = self._inline()
        if not inline or not getattr(inline, "_bot", None):
            logger.warning("backup: inline-бот недоступен — кнопка не будет добавлена")
            return False

        bot = inline._bot

        try:
            from aiogram.types import BufferedInputFile
        except Exception as exc:
            logger.warning("backup: aiogram недоступен (%s)", exc)
            return False

        # Регистрируем callback заранее — реальные chat/msg id подставим после
        # получения ответа от Telegram.
        cb_id = self._register_restore_cb(0, 0, kind)
        markup = self._build_restore_markup(cb_id)

        # Нормализуем dest к bot-формату: aiogram падает с
        # «chat not found», если ему передать «голый» raw-id канала.
        bot_dest = _to_bot_chat_id(dest)
        if bot_dest is None:
            logger.warning("backup: невалидный dest=%s — кнопка не будет добавлена", dest)
            inline._callbacks.pop(cb_id, None)
            return False

        try:
            input_file = BufferedInputFile(data, filename=fname)
            sent = await bot.send_document(
                chat_id=bot_dest,
                document=input_file,
                caption=caption,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except Exception as exc:
            # Бот не в чате / нет прав / другая ошибка → fallback (с видимым логом).
            logger.warning(
                "backup: bot.send_document(chat=%s, normalized=%s) упал: %s — пробую fallback",
                dest, bot_dest, exc,
            )
            inline._callbacks.pop(cb_id, None)
            return False

        # Обновляем args колбэка реальным chat_id / message_id
        try:
            sent_chat_id = _to_bot_chat_id(sent.chat.id) or sent.chat.id
            sent_msg_id  = sent.message_id
            inline._callbacks[cb_id] = (
                self._cb_restore,
                (int(sent_chat_id), int(sent_msg_id), kind),
                self.client.tg_id,
                False,
                {},
            )
            logger.debug(
                "backup: бот отправил %s (chat=%s msg=%s) с кнопкой «Восстановить»",
                kind, sent_chat_id, sent_msg_id,
            )
        except Exception as exc:
            logger.warning("backup: не смог достать sent.chat/message_id: %s", exc)
            inline._callbacks.pop(cb_id, None)
            return False
        return True

    async def _attach_button_to_userbot_msg(
        self,
        sent_msg,
        kind: str,
    ) -> bool:
        """
        Fallback: файл уже отправлен юзерботом, добавляем кнопку «🔄 Восстановить»
        через bot.edit_message_reply_markup. Бот должен быть админом канала с
        правом edit_messages (выдаём в _ensure_bot_in_channel).
        """
        inline = self._inline()
        if not inline or not getattr(inline, "_bot", None):
            return False

        chat_id, msg_id = _extract_msg_ids(sent_msg)
        if not chat_id or not msg_id:
            logger.warning("backup: не смог извлечь chat/msg id — кнопка не будет добавлена")
            return False

        # _extract_msg_ids уже нормализует, но дублируем явно — на случай
        # если объект пришёл из неожиданного источника.
        bot_chat_id = _to_bot_chat_id(chat_id)
        if bot_chat_id is None:
            logger.warning("backup: chat_id=%s не нормализуется — кнопка пропущена", chat_id)
            return False

        cb_id  = self._register_restore_cb(int(bot_chat_id), int(msg_id), kind)
        markup = self._build_restore_markup(cb_id)
        try:
            await inline._bot.edit_message_reply_markup(
                chat_id=int(bot_chat_id),
                message_id=int(msg_id),
                reply_markup=markup,
            )
            logger.info(
                "backup: кнопка «Восстановить» прикреплена к %s/%s (kind=%s)",
                bot_chat_id, msg_id, kind,
            )
            return True
        except Exception as exc:
            logger.warning(
                "backup: edit_message_reply_markup(chat=%s raw=%s msg=%s) упал: %s",
                bot_chat_id, chat_id, msg_id, exc,
            )
            inline._callbacks.pop(cb_id, None)
            return False

    async def _send_backup(
        self,
        dest: int | None,
        data: bytes,
        fname: str,
        caption: str,
        kind: str,
        ts: str,
        count: int = 0,
    ) -> None:
        """
        Отправка бэкапа ТОЛЬКО в группу KitsuneBackup.
        Saved Messages намеренно не используются.

        Цепочка попыток (любая выдаёт «файл + текст + кнопка»):
          1. bot.send_document(reply_markup=…) — одно сообщение, атомарно.
          2. юзербот шлёт файл, затем bot.edit_message_reply_markup
             прикрепляет кнопку «🔄 Восстановить» (нужно admin/edit_messages).
          3. крайний случай — юзербот без кнопки (логируем warning).
        """
        if not dest:
            logger.warning("backup: нет KitsuneBackup — отправка пропущена")
            return

        # ── 1. Основной путь — через бота, файл+текст+кнопка одним сообщением.
        if await self._send_with_button_via_bot(
            dest, data, fname, caption, kind, ts, count,
        ):
            return

        # ── 2. Fallback: юзербот шлёт файл, бот пристёгивает кнопку.
        sent = None
        try:
            buf = io.BytesIO(data)
            buf.name = fname
            sent = await hydro_send_file(
                self.client, dest, buf, caption=caption, parse_mode="html",
            )
        except Exception:
            logger.exception("backup: send to KitsuneBackup failed")
            return

        if sent is not None:
            attached = await self._attach_button_to_userbot_msg(sent, kind)
            if not attached:
                logger.warning(
                    "backup: %s отправлен без кнопки — проверь права бота "
                    "в KitsuneBackup (нужен admin + edit_messages)",
                    kind,
                )

    # ── backupdb ──────────────────────────────────────────────────────────────

    @command("backupdb", required=OWNER)
    async def backupdb_cmd(self, event) -> None:
        """Отправить дамп базы данных как .json (plain, без шифрования)."""
        async with ProgressMessage(event, self.strings("creating")) as prog:
            data    = self._db_bytes()
            dest    = await self._get_dest(event)
            ts      = self._ts()
            fname   = f"kitsune-db-{self._fname_ts()}.json"
            caption = self.strings("db_caption").format(ts=ts)

            await self._send_backup(dest, data, fname, caption, "db", ts)
            await prog.done(self.strings("done"))

    # ── restoredb ─────────────────────────────────────────────────────────────

    async def _do_restore_db(self, raw: bytes) -> bool:
        """
        Чистый restore БД из сырых байтов файла. Возвращает True/False.
        Принимает .json или .backup (ZIP с db.json внутри).
        """
        db_data = None

        if raw[:2] == b"PK":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    if "db.json" in zf.namelist():
                        db_data = json.loads(zf.open("db.json").read())
            except Exception as e:
                logger.warning("restoredb: не смог распаковать .backup: %s", e)

        if db_data is None:
            try:
                db_data = json.loads(raw.decode("utf-8"))
            except Exception:
                return False

        if not isinstance(db_data, dict):
            return False

        self._strip_tokens(db_data)
        self.db.clear()
        for owner, keys in db_data.items():
            if isinstance(keys, dict):
                for key, val in keys.items():
                    self.db.force_set(owner, key, val)
        await self.db.force_save()
        return True

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
            raw = await hydro_download(self.client, reply)
            ok = await self._do_restore_db(raw)
            if not ok:
                await prog.done(self.strings("bad_file"))
                return
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
            ts      = self._ts()
            fname   = f"kitsune-mods-{self._fname_ts()}.zip"
            caption = self.strings("mods_caption").format(ts=ts, count=count)

            await self._send_backup(dest, mods_zip, fname, caption, "mods", ts, count)
            await prog.done(self.strings("mods_done").format(count=count))

    # ── restoremods ───────────────────────────────────────────────────────────

    async def _do_restore_mods(self, raw: bytes) -> int | None:
        """
        Чистый restore модулей из сырых байтов файла.
        Принимает .zip (mods.zip напрямую) или .backup (с mods.zip внутри).
        Возвращает количество восстановленных файлов или None при ошибке.
        """
        mods_zip_bytes = None

        if raw[:2] == b"PK":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    names = zf.namelist()
                    if "mods.zip" in names:
                        mods_zip_bytes = zf.open("mods.zip").read()
                    elif any(n.startswith("mods/") for n in names) or "urls.json" in names:
                        mods_zip_bytes = raw
            except Exception as e:
                logger.warning("restoremods: %s", e)

        if mods_zip_bytes is None:
            return None

        return await self._restore_mods_from_zip(mods_zip_bytes)

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
            raw = await hydro_download(self.client, reply)
            count = await self._do_restore_mods(raw)
            if count is None:
                await prog.done(self.strings("mods_bad_file"))
                return
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
            ts      = self._ts()
            fname   = f"kitsune-{self._fname_ts()}.backup"
            caption = self.strings("all_caption").format(ts=ts, count=count)

            await self._send_backup(dest, archive_bytes, fname, caption, "all", ts, count)
            await prog.done(self.strings("all_done"))

    # ── restoreall ────────────────────────────────────────────────────────────

    async def _do_restore_all(self, raw: bytes) -> int | None:
        """
        Чистый restore полного .backup. Возвращает количество восстановленных
        модулей или None при ошибке.
        """
        if raw[:2] != b"PK":
            return None

        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                if "db.json" not in names:
                    return None

                db_data = json.loads(zf.open("db.json").read().decode("utf-8"))
                if not isinstance(db_data, dict):
                    return None

                self._strip_tokens(db_data)
                self.db.clear()
                for owner, keys in db_data.items():
                    if isinstance(keys, dict):
                        for key, val in keys.items():
                            self.db.force_set(owner, key, val)
                await self.db.force_save()

                count = 0
                if "mods.zip" in names:
                    mods_zip_bytes = zf.open("mods.zip").read()
                    count = await self._restore_mods_from_zip(mods_zip_bytes)
                return count
        except Exception:
            logger.exception("restoreall: ошибка")
            return None

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
            raw   = await hydro_download(self.client, reply)
            count = await self._do_restore_all(raw)
            if count is None:
                await prog.done(self.strings("all_bad_file"))
                return
            await prog.done(self.strings("all_restored"))

    # ── Кнопочный callback восстановления ─────────────────────────────────────

    async def _cb_restore(self, call, chat_id: int, msg_id: int, kind: str) -> None:
        """
        Обработчик кнопки «🔄 Восстановить» из формы под файлом.
        kind ∈ {"db", "mods", "all"}.
        """
        try:
            await call.answer(self.strings("restore_alert"))
        except Exception:
            pass

        inline = self._inline()
        ts     = self._ts()

        # Достаём оригинальное сообщение с файлом
        try:
            msg = await self.client.get_messages(chat_id, ids=int(msg_id))
        except Exception as exc:
            logger.warning("backup: get_messages failed: %s", exc)
            msg = None

        if not msg or not getattr(msg, "media", None):
            if inline:
                try:
                    await inline.edit(call, self.strings("restore_lost"), [])
                except Exception:
                    pass
            return

        # Качаем содержимое
        try:
            raw = await hydro_download(self.client, msg)
        except Exception as exc:
            logger.exception("backup: download failed")
            if inline:
                try:
                    await inline.edit(
                        call,
                        self.strings("restore_fail").format(err=str(exc)[:200]),
                        [],
                    )
                except Exception:
                    pass
            return

        # Делаем restore по типу
        try:
            if kind == "db":
                ok = await self._do_restore_db(raw)
                if not ok:
                    raise RuntimeError("bad DB format")
                final = self.strings("restore_done_db").format(ts=ts)
            elif kind == "mods":
                count = await self._do_restore_mods(raw)
                if count is None:
                    raise RuntimeError("bad mods format")
                final = self.strings("restore_done_mods").format(ts=ts, count=count)
            else:
                count = await self._do_restore_all(raw)
                if count is None:
                    raise RuntimeError("bad backup format")
                final = self.strings("restore_done_all").format(ts=ts, count=count)
        except Exception as exc:
            logger.exception("backup: restore via button failed")
            if inline:
                try:
                    await inline.edit(
                        call,
                        self.strings("restore_fail").format(err=str(exc)[:200]),
                        [],
                    )
                except Exception:
                    pass
            return

        # Финальный экран — без кнопок (восстановление уже выполнено)
        if inline:
            try:
                await inline.edit(call, final, [])
            except Exception:
                pass

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

        # 1m — специальный тестовый режим (отключён)
        if False and arg == "1m":
            await self.db.set(_DB_OWNER, "interval_h", "1m")
            await self.db.set(_DB_OWNER, "last_backup", int(time.time()))
            self._start_auto("1m")
            await event.reply("✅ Авто-бэкап каждые <b>1 мин</b> (тест).", parse_mode="html")
            return

        # Числовое значение (часы)
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

    def _start_auto(self, interval_h) -> None:
        if self._auto_task and not self._auto_task.done():
            self._auto_task.cancel()
        self._auto_task = asyncio.ensure_future(self._auto_loop(interval_h))

    async def _auto_loop(self, interval_h) -> None:
        interval_sec = 60 if interval_h == "1m" else int(interval_h) * 3_600
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
                db_data = self._db_bytes()
                await self._send_backup(
                    dest, db_data,
                    f"kitsune-db-{fts}.json",
                    self.strings("db_caption").format(ts=ts),
                    "db", ts,
                )

                # ── 2. mods.zip ───────────────────────────────────────────────
                mods_data, count = self._make_mods_zip()
                await self._send_backup(
                    dest, mods_data,
                    f"kitsune-mods-{fts}.zip",
                    self.strings("mods_caption").format(ts=ts, count=count),
                    "mods", ts, count,
                )

                # ── 3. .backup (полный архив db + mods) ───────────────────────
                full_data, count = self._make_full_backup()
                await self._send_backup(
                    dest, full_data,
                    f"kitsune-{fts}.backup",
                    self.strings("all_caption").format(ts=ts, count=count),
                    "all", ts, count,
                )

                await self.db.set(_DB_OWNER, "last_backup", int(time.time()))
                logger.debug("backup: авто-бэкап выполнен — db.json + mods.zip + .backup (%s)", fts)
            except Exception:
                logger.exception("backup: авто-бэкап упал")
                await asyncio.sleep(60)

    # ── Настройка интервала (вызывается из bot_setup) ─────────────────────────

    async def show_interval_setup(self, bot, owner_id: int) -> None:
        try:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            buttons, row = [], []
            for h in _INTERVAL_OPTIONS:
                label = f"{h}ч"
                row.append(InlineKeyboardButton(
                    text=label,
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

    async def handle_interval_callback(self, call) -> None:
        """Алиас для совместимости с bot_runner."""
        await self.on_callback(call)

    async def on_callback(self, call) -> None:
        if not call.data.startswith("backup_interval:"):
            return
        raw_h = call.data.split(":")[1]
        h = raw_h if raw_h == "1m" else int(raw_h)
        if h == 0:
            if self._auto_task and not self._auto_task.done():
                self._auto_task.cancel()
            await self.db.delete(_DB_OWNER, "interval_h")
            await call.message.edit_text(self.strings("interval_off"), parse_mode="HTML")
            return
        if h == "1m":
            await self.db.set(_DB_OWNER, "interval_h", "1m")
            await self.db.set(_DB_OWNER, "last_backup", int(time.time()))
            self._start_auto("1m")
            await call.message.edit_text("✅ Авто-бэкап каждые <b>1 мин</b> (тест).", parse_mode="HTML")
        else:
            await self.db.set(_DB_OWNER, "interval_h", h)
            await self.db.set(_DB_OWNER, "last_backup", int(time.time()))
            self._start_auto(h)
            await call.message.edit_text(self.strings("interval_set").format(h=h), parse_mode="HTML")
