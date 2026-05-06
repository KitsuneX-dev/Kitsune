from __future__ import annotations

import logging

from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:

    from telethon import TelegramClient

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).parent

BOT_AVATAR    = ASSETS_DIR / "kitsune.jpeg"

ASSETS_AVATAR = ASSETS_DIR / "kitsune_assets.png"

BACKUP_AVATAR = ASSETS_DIR / "kitsune_backup.png"

LOGS_AVATAR   = ASSETS_DIR / "kitsune_logs.png"

INFO_BANNER   = ASSETS_DIR / "kitsune_info.png"

_DB_NS = "kitsune.assets"

_CHANNEL_AVATARS: dict[str, Path] = {

    "KitsuneBackup":  BACKUP_AVATAR,

    "Kitsune-logs":   LOGS_AVATAR,

    "kitsune-assets": ASSETS_AVATAR,

}

def get_asset(name: str) -> Path:

    for ext in (".png", ".jpeg", ".jpg", ".gif"):

        p = ASSETS_DIR / f"{name}{ext}"

        if p.exists():

            return p

    raise FileNotFoundError(f"Asset not found: {name}")

async def _find_channels_by_title(

    client: "TelegramClient",

    titles: set[str],

) -> dict[str, int]:

    found: dict[str, int] = {}

    def _extract(dialog) -> None:

        t = dialog.title or ""

        if t in titles and t not in found:

            entity = dialog.entity

            cid = getattr(entity, "id", None)

            if cid:

                if getattr(entity, "megagroup", False) or getattr(entity, "broadcast", False):

                    found[t] = int(f"-100{cid}")

                else:

                    found[t] = -cid

    try:

        async for dialog in client.iter_dialogs(limit=500, folder=0):

            _extract(dialog)

            if len(found) == len(titles):

                return found

    except Exception as e:

        logger.warning("assets: ошибка iter_dialogs(folder=0): %s", e)

    try:

        async for dialog in client.iter_dialogs(limit=500, folder=1):

            _extract(dialog)

            if len(found) == len(titles):

                return found

    except Exception as e:

        logger.warning("assets: ошибка iter_dialogs(folder=1): %s", e)

    return found

def _resolve_bot_username(client: "TelegramClient", db) -> str | None:

    for ns in ("kitsune.notifier", "kitsune.inline"):

        u = db.get(ns, "bot_username", None)

        if u:

            return u

    inline = getattr(client, "_kitsune_inline", None)

    if inline:

        u = getattr(inline, "_bot_username", None)

        if u:

            logger.info("assets: bot_username взят из inline-объекта: %s", u)

            try:

                db.set_sync("kitsune.notifier", "bot_username", u)

            except Exception:

                pass

            return u

    return None

async def ensure_channel_photo(

    client: "TelegramClient",

    db,

    channel_id: int,

    photo_path: Path,

    *,

    force: bool = False,

) -> bool:

    flag_key = f"photo_{abs(channel_id)}"

    if not force and db.get(_DB_NS, flag_key, False):

        return True

    if not photo_path.exists():

        logger.warning("assets: файл не найден: %s", photo_path)

        return False

    try:

        from telethon.tl.functions.channels import EditPhotoRequest, JoinChannelRequest

        from telethon.tl.types import InputChatUploadedPhoto

        entity = await client.get_entity(channel_id)

        try:

            await client(JoinChannelRequest(entity))

            logger.debug("assets: вступили в %s", channel_id)

        except Exception:

            pass

        uploaded = await client.upload_file(str(photo_path), file_name=photo_path.name)

        await client(EditPhotoRequest(channel=entity, photo=InputChatUploadedPhoto(file=uploaded)))

        db.set_sync(_DB_NS, flag_key, True)

        try:

            await db.force_save()

        except Exception:

            pass

        logger.debug("assets: аватарка установлена для %s (%s)", channel_id, photo_path.name)

        return True

    except Exception as exc:

        logger.debug("assets: не удалось установить аватарку для %s: %s", channel_id, exc)

        return False

async def ensure_bot_photo(client: "TelegramClient", db, bot_username: str) -> bool:

    flag_key = f"bot_photo_{bot_username.lstrip('@').lower()}"

    if db.get(_DB_NS, flag_key, False):

        return True

    if not BOT_AVATAR.exists():

        logger.warning("assets: bot avatar не найден: %s", BOT_AVATAR)

        return False

    try:

        async with client.conversation("@BotFather", timeout=60) as conv:

            await conv.send_message("/setuserpic")

            await conv.get_response()

            await conv.send_message(f"@{bot_username.lstrip('@')}")

            r = await conv.get_response()

            if any(w in (r.text or "").lower() for w in ("photo", "фото", "pic", "send")):

                await conv.send_file(str(BOT_AVATAR))

                r2 = await conv.get_response()

                if any(w in (r2.text or "").lower() for w in ("updated", "установлено", "success", "saved")):

                    db.set_sync(_DB_NS, flag_key, True)

                    try:

                        await db.force_save()

                    except Exception:

                        pass

                    logger.debug("assets: аватарка бота @%s установлена", bot_username)

                    return True

    except Exception as exc:

        logger.debug("assets: не удалось установить аватарку бота @%s: %s", bot_username, exc)

    return False

async def setup_all_avatars(client: "TelegramClient", db) -> None:

    if db.get(_DB_NS, "setup_done", False):

        return

    id_map: dict[str, int | None] = {

        "KitsuneBackup": (

            db.get("kitsune.backup",         "group_id",        None) or

            db.get("kitsune.backup",         "chat_id",         None) or

            db.get("kitsune.modules.backup", "group_id",        None) or

            db.get("kitsune.assets",         "known_kitsunebackup", None)

        ),

        "Kitsune-logs": (

            db.get("kitsune.logs",           "channel_id",      None) or

            db.get("kitsune.logs",           "chat_id",         None) or

            db.get("kitsune.notifier",       "logs_id",         None) or

            db.get("kitsune.assets",         "known_kitsune_logs", None)

        ),

        "kitsune-assets": (

            db.get("kitsune.assets_channel", "channel_id",      None) or

            db.get("kitsune.assets",         "channel_id",      None) or

            db.get("kitsune.notifier",       "assets_id",       None) or

            db.get("kitsune.assets",         "known_kitsune_assets", None)

        ),

    }

    logger.debug("assets: ID из БД: %s", {k: v for k, v in id_map.items()})

    missing_titles = {t for t, cid in id_map.items() if not cid}

    if missing_titles:

        logger.debug("assets: ищем в диалогах: %s", missing_titles)

        found = await _find_channels_by_title(client, missing_titles)

        for title, cid in found.items():

            logger.debug("assets: нашли '%s' в диалогах: id=%s", title, cid)

            id_map[title] = cid

            _db_key = title.replace("-", "_").lower()

            try:

                db.set_sync("kitsune.assets", f"known_{_db_key}", cid)

                await db.force_save()

                logger.debug("assets: сохранили id '%s'=%s в БД", title, cid)

            except Exception as _e:

                logger.debug("assets: не удалось сохранить id '%s': %s", title, _e)

    if not id_map.get("kitsune-assets"):

        try:

            from telethon.tl.functions.channels import CreateChannelRequest

            from telethon.tl.functions.account import UpdateNotifySettingsRequest

            from telethon.tl.types import InputNotifyPeer, InputPeerNotifySettings

            logger.debug("assets: создаём канал kitsune-assets...")

            result = await client(CreateChannelRequest(

                title="kitsune-assets",

                about="🦊 Kitsune Userbot — ассеты и медиафайлы",

                megagroup=False,

            ))

            new_cid = int(f"-100{result.chats[0].id}")

            id_map["kitsune-assets"] = new_cid

            try:

                from telethon.tl.functions.folders import EditPeerFoldersRequest

                from telethon.tl.types import InputFolderPeer

                await client(EditPeerFoldersRequest(folder_peers=[

                    InputFolderPeer(

                        peer=await client.get_input_entity(new_cid),

                        folder_id=1,

                    )

                ]))

            except Exception:

                pass

            try:

                await client(UpdateNotifySettingsRequest(

                    peer=InputNotifyPeer(await client.get_input_entity(new_cid)),

                    settings=InputPeerNotifySettings(mute_until=2**31 - 1),

                ))

            except Exception:

                pass

            db.set_sync("kitsune.assets", "known_kitsune_assets", new_cid)

            try:

                await db.force_save()

            except Exception:

                pass

            logger.debug("assets: канал kitsune-assets создан (id=%s)", new_cid)

        except Exception as e:

            logger.debug("assets: не удалось создать kitsune-assets: %s", e)

    all_channel_ok = True

    for title, cid in id_map.items():

        if not cid:

            logger.debug("assets: канал '%s' не найден — пропускаем", title)

            all_channel_ok = False

            continue

        photo = _CHANNEL_AVATARS[title]

        flag  = f"photo_{abs(int(cid))}"

        if db.get(_DB_NS, flag, False):

            logger.debug("assets: '%s' — аватарка уже стоит, пропускаем", title)

            continue

        logger.debug("assets: устанавливаем аватарку для '%s' (id=%s)...", title, cid)

        ok = await ensure_channel_photo(client, db, int(cid), photo)

        if not ok:

            all_channel_ok = False

    bot_ok = True

    bot_username = _resolve_bot_username(client, db)

    logger.debug("assets: bot_username = %s", bot_username)

    if bot_username:

        flag = f"bot_photo_{bot_username.lstrip('@').lower()}"

        if not db.get(_DB_NS, flag, False):

            logger.debug("assets: устанавливаем аватарку бота @%s...", bot_username)

            ok = await ensure_bot_photo(client, db, bot_username)

            if not ok:

                bot_ok = False

        else:

            logger.debug("assets: аватарка бота уже стоит")

    else:

        bot_ok = False

    if all_channel_ok and bot_ok:

        try:

            db.set_sync(_DB_NS, "setup_done", True)

            await db.force_save()

        except Exception:

            pass

async def diagnose(client: "TelegramClient", db) -> str:

    lines = ["🔍 <b>Kitsune Assets — диагностика</b>\n"]

    lines.append("📁 <b>Файлы:</b>")

    for name, path in [

        ("kitsune.jpeg",      BOT_AVATAR),

        ("kitsune_backup.png",BACKUP_AVATAR),

        ("kitsune_logs.png",  LOGS_AVATAR),

        ("kitsune_assets.png",ASSETS_AVATAR),

        ("kitsune_info.png",  INFO_BANNER),

    ]:

        lines.append(f"  {'✅' if path.exists() else '❌'} {name}")

    lines.append("\n🗄 <b>БД ключи:</b>")

    backup_id = db.get("kitsune.backup", "group_id", None)

    bot_user  = _resolve_bot_username(client, db)

    logs_id   = db.get("kitsune.logs", "channel_id", None)

    assets_id = db.get("kitsune.assets_channel", "channel_id", None)

    lines.append(f"  backup group_id = <code>{backup_id}</code>")

    lines.append(f"  bot_username    = <code>{bot_user}</code>")

    lines.append(f"  logs channel_id = <code>{logs_id}</code>")

    lines.append(f"  assets chan id  = <code>{assets_id}</code>")

    lines.append("\n🔍 <b>Поиск в диалогах:</b>")

    found = await _find_channels_by_title(client, set(_CHANNEL_AVATARS.keys()))

    for title in _CHANNEL_AVATARS:

        cid = found.get(title)

        lines.append(f"  {title} = <code>{cid or 'не найден'}</code>")

    lines.append("\n🚩 <b>Флаги установки:</b>")

    all_ids = {

        "KitsuneBackup":  backup_id or found.get("KitsuneBackup"),

        "Kitsune-logs":   logs_id   or found.get("Kitsune-logs"),

        "kitsune-assets": assets_id or found.get("kitsune-assets"),

    }

    for title, cid in all_ids.items():

        if cid:

            key = f"photo_{abs(int(cid))}"

            val = db.get(_DB_NS, key, False)

            lines.append(f"  {title}: {key} = {val}")

    if bot_user:

        key = f"bot_photo_{bot_user.lstrip('@').lower()}"

        lines.append(f"  bot: {key} = {db.get(_DB_NS, key, False)}")

    lines.append("\n🤖 <b>Inline-бот:</b>")

    inline = getattr(client, "_kitsune_inline", None)

    if inline:

        lines.append(f"  _bot_username = <code>{getattr(inline, '_bot_username', None)}</code>")

        lines.append(f"  _bot объект   = {'✅' if getattr(inline, '_bot', None) else '❌'}")

    else:

        lines.append("  inline-модуль не найден")

    return "\n".join(lines)

