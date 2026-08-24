from __future__ import annotations
import asyncio
import logging

from ...core.loader import KitsuneModule, command
from ...core.loader import _scan_ast_with_cache as _scan_ast
from ...core.security import OWNER
from ...hydro_media import send_file as hydro_send_file, download_media as hydro_download
from ...utils import ProgressMessage
from .archive import ArchiveMixin
from .callbacks import CallbackMixin
from .helpers import (
    _DB_LOADER,
    _DB_OWNER,
    _INTERVAL_OPTIONS,
    _ensure_kitsune_folder,
    _extract_msg_ids,
    _to_bot_chat_id,
    _user_modules_dir,
)
from .restore import RestoreMixin, _quarantine_dir
from .scheduler import SchedulerMixin

logger = logging.getLogger(__name__)

_USER_MODULES_DIR = _user_modules_dir()

class BackupModule(
    ArchiveMixin,
    RestoreMixin,
    SchedulerMixin,
    CallbackMixin,
    KitsuneModule,
):
    name        = "backup"
    description = "Резервное копирование — без шифрования, совместимо с Hikka/Heroku"
    version     = "1.3.0"
    author      = "Yushi"
    strings_ru = {
        "creating":       "⏳ Создаю резервную копию базы данных...",
        "done":           "✅ Бэкап базы данных отправлен.",
        "restoring":      "⏳ Восстанавливаю базу данных...",
        "restored":       "✅ База данных восстановлена. Перезапустите бота.",
        "bad_file":       "❌ Неверный формат. Ожидается .json или .backup",
        "mods_creating":  "⏳ Собираю файлы модулей и конфиги...",
        "mods_done":      "✅ Бэкап модулей отправлен ({count} файлов, {cfg} конфигов).",
        "mods_no_mods":   "❌ Нет установленных пользовательских модулей.",
        "mods_restoring": "⏳ Восстанавливаю модули и конфиги...",
        "mods_restored":  "✅ Модули восстановлены: {count} шт., конфигов: {cfg}. Перезапустите бота.",
        "mods_bad_file":  "❌ Неверный формат. Ожидается .zip или .backup",
        "all_creating":   "⏳ Создаю полный бэкап (БД + все модули)...",
        "all_done":       "✅ Полный бэкап отправлен.",
        "all_restoring":  "⏳ Восстанавливаю всё из бэкапа...",
        "all_restored":   "✅ База данных и модули восстановлены. Перезапустите бота.",
        "all_bad_file":   "❌ Неверный формат .backup",
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
        "db_caption": (
            "🦊 <b>Kitsune DB Backup</b>\n"
            "🕐 {ts}\n"
            "📋 Ответь: <code>.restoredb</code>"
        ),
        "mods_caption": (
            "🦊 <b>Kitsune Mods Backup</b>\n"
            "🕐 {ts}\n"
            "📦 Файлов: {count} | Конфигов: {cfg}\n"
            "📋 Ответь: <code>.restoremods</code>"
        ),
        "all_caption": (
            "🦊 <b>Kitsune Full Backup</b>\n"
            "🕐 {ts}\n"
            "📦 Файлов: {count}\n"
            "📋 Ответь: <code>.restoreall</code>"
        ),
        "restore_btn":     "🔄 Восстановить",
        "restore_form_db": (
            "🦊 <b>Управление бэкапом БД</b>\n"
            "🕐 {ts}\n\n"
            "Нажми кнопку, чтобы восстановить базу данных из этого бэкапа."
        ),
        "restore_form_mods": (
            "🦊 <b>Управление бэкапом модулей</b>\n"
            "🕐 {ts}\n"
            "📦 Файлов: {count} | Конфигов: {cfg}\n\n"
            "Нажми кнопку, чтобы восстановить модули и конфиги из этого бэкапа."
        ),
        "restore_form_all": (
            "🦊 <b>Управление полным бэкапом</b>\n"
            "🕐 {ts}\n"
            "📦 Файлов: {count}\n\n"
            "Нажми кнопку, чтобы восстановить БД и модули из этого бэкапа."
        ),
        "restore_alert":   "⏳ Восстанавливаю...",
        "restore_done_db":   "✅ База данных восстановлена из бэкапа.\n🕐 {ts}\n♻️ Перезапустите бота.",
        "restore_done_mods": "✅ Модули восстановлены ({count} шт., конфигов: {cfg}).\n🕐 {ts}\n♻️ Перезапустите бота.",
        "restore_done_all":  "✅ Полное восстановление выполнено ({count} модулей).\n🕐 {ts}\n♻️ Перезапустите бота.",
        "restore_fail":      "❌ Не удалось восстановить: {err}",
        "restore_lost":      "❌ Не нашёл исходный файл бэкапа в чате.",
        "quarantine_head":   "\n\n⚠️ <b>Отклонено модулей: {count}</b> (помещены в карантин)\n{items}",
        "quarantine_item":   "• <code>{file}</code> из <code>{source}</code>\n  ↳ {reason}",
    }
    strings_en = {
        "creating":       "⏳ Creating database backup...",
        "done":           "✅ Database backup sent.",
        "restoring":      "⏳ Restoring database...",
        "restored":       "✅ Database restored. Please restart.",
        "bad_file":       "❌ Invalid format. Expected .json or .backup",
        "mods_creating":  "⏳ Collecting module files and configs...",
        "mods_done":      "✅ Modules backup sent ({count} files, {cfg} configs).",
        "mods_no_mods":   "❌ No user modules found.",
        "mods_restoring": "⏳ Restoring modules and configs...",
        "mods_restored":  "✅ Modules restored: {count}, configs: {cfg}. Please restart.",
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
        "mods_caption":   "🦊 <b>Kitsune Mods Backup</b>\n🕐 {ts}\n📦 {count} files | {cfg} configs\n📋 Reply: <code>.restoremods</code>",
        "all_caption":    "🦊 <b>Kitsune Full Backup</b>\n🕐 {ts}\n📦 {count} files\n📋 Reply: <code>.restoreall</code>",
        "restore_btn":      "🔄 Restore",
        "restore_form_db":  "🦊 <b>DB Backup management</b>\n🕐 {ts}\n\nTap the button to restore the database from this backup.",
        "restore_form_mods":"🦊 <b>Mods Backup management</b>\n🕐 {ts}\n📦 {count} files | {cfg} configs\n\nTap the button to restore modules and configs from this backup.",
        "restore_form_all": "🦊 <b>Full Backup management</b>\n🕐 {ts}\n📦 {count} files\n\nTap the button to restore everything from this backup.",
        "restore_alert":    "⏳ Restoring...",
        "restore_done_db":  "✅ Database restored from backup.\n🕐 {ts}\n♻️ Please restart.",
        "restore_done_mods":"✅ Modules restored ({count}, configs: {cfg}).\n🕐 {ts}\n♻️ Please restart.",
        "restore_done_all": "✅ Full restore done ({count} modules).\n🕐 {ts}\n♻️ Please restart.",
        "restore_fail":     "❌ Restore failed: {err}",
        "restore_lost":     "❌ Original backup file not found in chat.",
        "quarantine_head":  "\n\n⚠️ <b>Rejected modules: {count}</b> (moved to quarantine)\n{items}",
        "quarantine_item":  "• <code>{file}</code> from <code>{source}</code>\n  ↳ {reason}",
    }
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._auto_task: asyncio.Task | None = None
        self._rejected: list[dict] = []
    async def on_load(self) -> None:
        interval_h = self.db.get(_DB_OWNER, "interval_h", None)
        if interval_h:
            val = interval_h if interval_h == "1m" else int(interval_h)
            self._start_auto(val)
        try:
            asyncio.ensure_future(self._restore_callbacks_from_db())
        except Exception as _exc:
            logger.debug("backup: cannot schedule callback restore: %s", _exc)

__all__ = [
    "BackupModule",
    "_quarantine_dir",
    "_user_modules_dir",
    "_USER_MODULES_DIR",
    "_DB_OWNER",
    "_DB_LOADER",
    "_INTERVAL_OPTIONS",
    "_ensure_kitsune_folder",
    "_to_bot_chat_id",
    "_extract_msg_ids",
]
