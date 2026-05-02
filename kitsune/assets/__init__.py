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


# ── Авто-определение bot_username из inline-модуля ────────────────────────────

def _resolve_bot_username(client: "TelegramClient", db) -> str | None:
    """
    Ищет username инлайн-бота в нескольких местах:
      1. DB: kitsune.inline / bot_username
      2. Живой объект: client._kitsune_inline._bot_username
    Если нашли через объект, попутно сохраняем в БД чтобы следующий запуск
    тоже его видел.
    """
    # 1. Из БД
    username = db.get("kitsune.inline", "bot_username", None)
    if username:
        return username

    # 2. Из живого инлайн-объекта (inline/core.py хранит его в памяти,
    #    но не сохраняет в БД — ФИКС: читаем и сохраняем)
    inline = getattr(client, "_kitsune_inline", None)
    if inline:
        username = getattr(inline, "_bot_username", None)
        if username:
            logger.info("assets: bot_username взят из inline-объекта: %s", username)
            try:
                db.set_sync("kitsune.inline", "bot_username", username)
            except Exception as e:
                logger.debug("assets: не удалось сохранить bot_username в БД: %s", e)
            return username

    return None


# ── Приглашение инлайн-бота в канал/группу и выдача прав ─────────────────────

async def _ensure_bot_in_channel(
    client: "TelegramClient",
    db,
    entity,
    channel_id: int,
) -> None:
    """
    Проверяет, добавлен ли инлайн-бот в канал/группу.
    Если нет — приглашает через аккаунт пользователя и выдаёт права админа.
    Результат запоминает в БД чтобы не проверять повторно.
    """
    inline = getattr(client, "_kitsune_inline", None)
    if not inline or not getattr(inline, "_bot", None):
        return

    mem_flag = f"bot_member_{abs(channel_id)}"
    if db.get(_DB_NS, mem_flag, False):
        return  # уже добавлен (по флагу)

    try:
        from telethon.tl.functions.channels import (
            InviteToChannelRequest, EditAdminRequest,
        )
        from telethon.tl.types import ChatAdminRights
        from telethon.errors import UserAlreadyParticipantError

        bot_obj = inline._bot
        me = await bot_obj.get_me()
        bot_id = me.id

        # Получаем полный InputUser через resolve_peer
        try:
            bot_peer = await client.get_input_entity(bot_id)
        except Exception:
            bot_peer = await client.get_input_entity(f"@{me.username}")

        # Пробуем пригласить
        try:
            await client(InviteToChannelRequest(channel=entity, users=[bot_peer]))
            logger.info("assets: бот @%s добавлен в канал %s", me.username, channel_id)
        except UserAlreadyParticipantError:
            logger.info("assets: бот @%s уже в канале %s", me.username, channel_id)
        except Exception as exc:
            logger.warning("assets: не удалось добавить бота в %s: %s", channel_id, exc)
            return

        # Выдаём права администратора (нужные для работы нотификаций)
        try:
            rights = ChatAdminRights(
                post_messages=True,
                edit_messages=True,
                delete_messages=True,
                change_info=False,
                invite_users=True,
                pin_messages=True,
            )
            await client(EditAdminRequest(
                channel=entity,
                user_id=bot_peer,
                admin_rights=rights,
                rank="Kitsune Bot",
            ))
            logger.info("assets: боту @%s выданы права в %s", me.username, channel_id)
        except Exception as exc:
            logger.warning("assets: не удалось выдать права боту в %s: %s", channel_id, exc)

        db.set_sync(_DB_NS, mem_flag, True)
        try:
            await db.force_save()
        except Exception:
            pass

    except Exception as exc:
        logger.warning("assets: _ensure_bot_in_channel ошибка для %s: %s", channel_id, exc)


# ── Установка аватарки канала/группы ─────────────────────────────────────────

async def ensure_channel_photo(
    client: "TelegramClient",
    db,
    channel_id: int,
    photo_path: Path,
    *,
    force: bool = False,
) -> bool:
    """
    Устанавливает фото канала/группы если ещё не установлено.
    Автоматически вступает в канал/группу, выдаёт себе права если нужно,
    а также приглашает инлайн-бота и выдаёт ему права.
    """
    flag_key = f"photo_{abs(channel_id)}"
    if not force and db.get(_DB_NS, flag_key, False):
        return True  # уже установлено

    if not photo_path.exists():
        logger.warning("assets: файл не найден: %s", photo_path)
        return False

    try:
        from telethon.tl.functions.channels import (
            EditPhotoRequest, EditAdminRequest, JoinChannelRequest,
        )
        from telethon.tl.types import (
            InputChatUploadedPhoto, ChatAdminRights,
        )

        entity = await client.get_entity(channel_id)

        # Вступаем если не состоим
        try:
            await client(JoinChannelRequest(entity))
            logger.info("assets: вступили в канал %s", channel_id)
        except Exception:
            pass  # уже состоим — нормально

        # Пробуем выдать себе права (если мы не создатель, но есть возможность)
        try:
            me = await client.get_me()
            me_peer = await client.get_input_entity(me.id)
            rights = ChatAdminRights(
                post_messages=True,
                edit_messages=True,
                delete_messages=True,
                change_info=True,
                invite_users=True,
                pin_messages=True,
            )
            await client(EditAdminRequest(
                channel=entity,
                user_id=me_peer,
                admin_rights=rights,
                rank="Kitsune",
            ))
        except Exception:
            pass  # уже создатель или нет прав на редактирование — не критично

        # Устанавливаем фото
        uploaded = await client.upload_file(str(photo_path), file_name=photo_path.name)
        photo    = InputChatUploadedPhoto(file=uploaded)
        await client(EditPhotoRequest(channel=entity, photo=photo))

        db.set_sync(_DB_NS, flag_key, True)
        try:
            await db.force_save()
        except Exception:
            pass
        logger.info("assets: аватарка установлена для %s (%s)", channel_id, photo_path.name)

        # Добавляем инлайн-бота в канал/группу и выдаём ему права
        await _ensure_bot_in_channel(client, db, entity, channel_id)

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
                    db.set_sync(_DB_NS, flag_key, True)
                    try:
                        await db.force_save()
                    except Exception:
                        pass
                    logger.info("assets: аватарка бота @%s установлена", username_clean)
                    return True
    except Exception as exc:
        logger.warning("assets: не удалось установить аватарку бота @%s: %s", bot_username, exc)

    return False


# ── Проверка и установка всех аватарок при старте ────────────────────────────

async def setup_all_avatars(client: "TelegramClient", db) -> None:
    """
    Вызывается при запуске бота.
    Устанавливает аватарки для всех каналов/групп/бота если ещё не установлены.

    ФИКС:
    - bot_username теперь авто-определяется из живого inline-объекта если в БД None.
    - При вступлении в канал/группу выдаются права администратора.
    - Инлайн-бот автоматически приглашается в каналы/группы и получает права.
    - Расширен поиск ID каналов по нескольким ключам БД.
    """
    pairs: list[tuple[int, Path]] = []

    # kitsune.backup использует разные ключи в разных версиях
    backup_id = (
        db.get("kitsune.backup",         "group_id",   None) or
        db.get("kitsune.backup",         "chat_id",    None) or
        db.get("kitsune.modules.backup", "group_id",   None) or
        db.get("kitsune.modules.backup", "chat_id",    None)
    )
    logger.info("assets: backup_id из БД = %s", backup_id)
    if backup_id:
        pairs.append((int(backup_id), BACKUP_AVATAR))

    logs_id = (
        db.get("kitsune.logs",         "channel_id", None) or
        db.get("kitsune.logs",         "chat_id",    None) or
        db.get("kitsune.notifier",     "logs_id",    None) or
        db.get("kitsune.notifier",     "channel_id", None) or
        db.get("kitsune.modules.logs", "channel_id", None)
    )
    if logs_id:
        pairs.append((int(logs_id), LOGS_AVATAR))

    assets_id = (
        db.get("kitsune.assets_channel",  "channel_id", None) or
        db.get("kitsune.assets",          "channel_id", None) or
        db.get("kitsune.notifier",        "assets_id",  None) or
        db.get("kitsune.modules.assets",  "channel_id", None)
    )
    if assets_id:
        pairs.append((int(assets_id), ASSETS_AVATAR))

    logger.info("assets: setup_all_avatars — найдено %d каналов/групп", len(pairs))
    for channel_id, photo_path in pairs:
        flag_key = f"photo_{abs(channel_id)}"
        already  = db.get(_DB_NS, flag_key, False)
        logger.info("assets: канал %s — флаг=%s, файл=%s", channel_id, already, photo_path.exists())
        if not already:
            await ensure_channel_photo(client, db, channel_id, photo_path)

    # Аватарка бота: ФИКС — авто-определяем username из inline-объекта если в БД None
    bot_username = _resolve_bot_username(client, db)
    logger.info("assets: bot_username = %s", bot_username)
    if bot_username:
        flag_key = f"bot_photo_{bot_username.lstrip('@').lower()}"
        if not db.get(_DB_NS, flag_key, False):
            await ensure_bot_photo(client, db, bot_username)


# ── Диагностика (вызывается из .assetcheck) ───────────────────────────────────

async def diagnose(client: "TelegramClient", db) -> str:
    """
    Возвращает диагностический отчёт — что найдено в БД и что будет делать setup_all_avatars.
    Вызови через команду .assetcheck
    """
    lines = ["🔍 <b>Kitsune Assets — диагностика</b>\n"]

    # Файлы
    lines.append("📁 <b>Файлы:</b>")
    for name, path in [
        ("kitsune.jpeg",      BOT_AVATAR),
        ("kitsune_backup.png",BACKUP_AVATAR),
        ("kitsune_logs.png",  LOGS_AVATAR),
        ("kitsune_assets.png",ASSETS_AVATAR),
        ("kitsune_info.png",  INFO_BANNER),
        ("kitsune_guide.png", GUIDE_BANNER),
    ]:
        lines.append(f"  {'✅' if path.exists() else '❌'} {name}")

    # БД ключи
    lines.append("\n🗄 <b>БД ключи:</b>")
    backup_id = db.get("kitsune.backup", "group_id", None)
    bot_user  = _resolve_bot_username(client, db)
    logs_id   = db.get("kitsune.logs", "channel_id", None)
    assets_id = db.get("kitsune.assets_channel", "channel_id", None)

    lines.append(f"  backup group_id = <code>{backup_id}</code>")
    lines.append(f"  bot_username    = <code>{bot_user}</code>")
    lines.append(f"  logs channel_id = <code>{logs_id}</code>")
    lines.append(f"  assets chan id  = <code>{assets_id}</code>")

    # Флаги установки
    lines.append("\n🚩 <b>Флаги установки (kitsune.assets):</b>")
    for cid in [backup_id, logs_id, assets_id]:
        if cid:
            key = f"photo_{abs(int(cid))}"
            val = db.get(_DB_NS, key, False)
            lines.append(f"  {key} = {val}")
    if bot_user:
        key = f"bot_photo_{bot_user.lstrip('@').lower()}"
        val = db.get(_DB_NS, key, False)
        lines.append(f"  {key} = {val}")

    # Inline-бот
    lines.append("\n🤖 <b>Inline-бот:</b>")
    inline = getattr(client, "_kitsune_inline", None)
    if inline:
        ub = getattr(inline, "_bot_username", None)
        lines.append(f"  _bot_username (в памяти) = <code>{ub}</code>")
        has_bot = bool(getattr(inline, "_bot", None))
        lines.append(f"  _bot объект = {'✅' if has_bot else '❌'}")
    else:
        lines.append("  inline-модуль не найден")

    return "\n".join(lines)
