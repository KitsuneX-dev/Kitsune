"""
kitsune/assets — менеджер встроенных ассетов (аватарки, баннеры).

Структура папки:
    kitsune/assets/
        kitsune.jpeg        — аватарка бота Kitsune {first_name}
        kitsune_assets.png  — аватарка канала kitsune-assets
        kitsune_backup.png  — аватарка группы KitsuneBackup
        kitsune_logs.png    — аватарка канала kitsune-logs
        kitsune_info.png    — баннер welcome-сообщения
        kitsune_guide.png   — баннер команды .help

Логика установки аватарок:
    • Бот, каналы, группы — проверяются ОДИН РАЗ при запуске.
    • Если аватарка уже стоит (флаг в БД) — пропускаем.
    • Если нет — устанавливаем и сохраняем флаг.
    • Баннеры (info, guide) всегда прикладываются к сообщениям — не проверяются.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telethon import TelegramClient

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).parent

# ── Пути к файлам ─────────────────────────────────────────────────────────────
BOT_AVATAR     = ASSETS_DIR / "kitsune.jpeg"
ASSETS_AVATAR  = ASSETS_DIR / "kitsune_assets.png"
BACKUP_AVATAR  = ASSETS_DIR / "kitsune_backup.png"
LOGS_AVATAR    = ASSETS_DIR / "kitsune_logs.png"
INFO_BANNER    = ASSETS_DIR / "kitsune_info.png"
GUIDE_BANNER   = ASSETS_DIR / "kitsune_guide.png"

_DB_NS = "kitsune.assets"


def get_asset(name: str) -> Path:
    """Возвращает Path к ассету. name = имя файла без расширения."""
    for ext in (".png", ".jpeg", ".jpg", ".gif"):
        p = ASSETS_DIR / f"{name}{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"Asset not found: {name}")


# ── Установка аватарки канала/группы ─────────────────────────────────────────

async def ensure_channel_photo(
    client: "TelegramClient",
    db,
    channel_id: int,
    photo_path: Path,
) -> bool:
    """
    Устанавливает фото канала/группы если ещё не установлено.
    Использует флаг в БД чтобы не проверять повторно.
    Возвращает True если фото было установлено (или уже стояло).
    """
    flag_key = f"photo_{abs(channel_id)}"
    if db.get(_DB_NS, flag_key, False):
        return True  # уже установлено

    if not photo_path.exists():
        logger.warning("assets: файл не найден: %s", photo_path)
        return False

    try:
        from telethon.tl.functions.channels import EditPhotoRequest
        from telethon.tl.functions.messages import UploadMediaRequest
        from telethon.tl.types import InputChatUploadedPhoto, InputMediaUploadedPhoto

        uploaded = await client.upload_file(str(photo_path))
        photo    = InputChatUploadedPhoto(file=uploaded)
        entity   = await client.get_entity(channel_id)
        await client(EditPhotoRequest(channel=entity, photo=photo))

        db.force_set(_DB_NS, flag_key, True)
        await db.force_save()
        logger.info("assets: аватарка установлена для %s", channel_id)
        return True
    except Exception as exc:
        logger.warning("assets: не удалось установить аватарку для %s: %s", channel_id, exc)
        return False


# ── Установка аватарки бота через BotFather ───────────────────────────────────

async def ensure_bot_photo(
    client: "TelegramClient",
    db,
    bot_username: str,
) -> bool:
    """
    Устанавливает фото бота через @BotFather если ещё не установлено.
    """
    flag_key = f"bot_photo_{bot_username.lstrip('@').lower()}"
    if db.get(_DB_NS, flag_key, False):
        return True

    if not BOT_AVATAR.exists():
        logger.warning("assets: bot avatar не найден: %s", BOT_AVATAR)
        return False

    try:
        async with client.conversation("@BotFather", timeout=60) as conv:
            await conv.send_message("/setuserpic")
            r1 = await conv.get_response()

            # BotFather пришлёт список ботов — выбираем нашего
            username_clean = bot_username.lstrip("@")
            await conv.send_message(f"@{username_clean}")
            r2 = await conv.get_response()

            # BotFather просит прислать фото
            if "photo" in (r2.text or "").lower() or "фото" in (r2.text or "").lower() or "pic" in (r2.text or "").lower():
                await conv.send_file(str(BOT_AVATAR))
                r3 = await conv.get_response()
                if "updated" in (r3.text or "").lower() or "установлено" in (r3.text or "").lower() or "success" in (r3.text or "").lower():
                    db.force_set(_DB_NS, flag_key, True)
                    await db.force_save()
                    logger.info("assets: аватарка бота @%s установлена", username_clean)
                    return True
    except Exception as exc:
        logger.warning("assets: не удалось установить аватарку бота @%s: %s", bot_username, exc)

    return False


# ── Проверка и установка всех аватарок при старте ────────────────────────────

async def setup_all_avatars(client: "TelegramClient", db) -> None:
    """
    Вызывается при запуске бота.
    Проходит по всем известным каналам/группам и устанавливает аватарки
    если они ещё не установлены (проверка через флаги в БД).
    """
    # Собираем channel_id → photo_path из БД
    pairs: list[tuple[int, Path]] = []

    backup_id = db.get("kitsune.backup", "group_id", None)
    if backup_id:
        pairs.append((int(backup_id), BACKUP_AVATAR))

    logs_id = db.get("kitsune.logs", "channel_id", None)
    if logs_id:
        pairs.append((int(logs_id), LOGS_AVATAR))

    assets_id = db.get("kitsune.assets_channel", "channel_id", None)
    if assets_id:
        pairs.append((int(assets_id), ASSETS_AVATAR))

    for channel_id, photo_path in pairs:
        await ensure_channel_photo(client, db, channel_id, photo_path)

    # Аватарка бота
    bot_username = db.get("kitsune.inline", "bot_username", None)
    if bot_username:
        await ensure_bot_photo(client, db, bot_username)
