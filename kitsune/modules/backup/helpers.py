from __future__ import annotations
import logging
from pathlib import Path

from ...paths import data_dir as _kdd

logger = logging.getLogger(__name__)

_DB_OWNER         = "kitsune.backup"

_DB_LOADER        = "kitsune.loader_mod"

_INTERVAL_OPTIONS = [2, 4, 6, 8, 12, 24, 48]


def _user_modules_dir() -> Path:
    return _kdd() / "modules"

async def _ensure_kitsune_folder(client, *peer_ids: int) -> None:
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
    filters = await client(GetDialogFiltersRequest())
    existing: DialogFilter | None = None
    max_id = 2
    for f in filters.filters:
        fid = getattr(f, "id", 0)
        if fid > max_id:
            max_id = fid
        title = getattr(f, "title", None)
        if title == FOLDER_NAME:
            existing = f
            break
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
        current_ids = {
            getattr(p, "channel_id", None) or getattr(p, "chat_id", None)
            for p in getattr(existing, "include_peers", [])
        }
        to_add = [
            p for p in new_peers
            if (getattr(p, "channel_id", None) or getattr(p, "chat_id", None)) not in current_ids
        ]
        if not to_add:
            return
        existing.include_peers = list(getattr(existing, "include_peers", [])) + to_add
        await client(UpdateDialogFilterRequest(id=existing.id, filter=existing))
        logger.debug("_ensure_kitsune_folder: добавлено %d чатов в папку Kitsune", len(to_add))
    else:
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
    if chat_id is None:
        return None
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return None
    if cid < 0:
        return cid
    s = str(cid)
    if s.startswith("100") and len(s) >= 13:
        return -cid
    if cid > 1_000_000_000:
        return int(f"-100{cid}")
    return cid
def _extract_msg_ids(sent) -> tuple[int | None, int | None]:
    if sent is None:
        return None, None
    msg_id = getattr(sent, "id", None)
    chat_id = None
    chat_obj = getattr(sent, "chat", None)
    if chat_obj is not None:
        chat_id = getattr(chat_obj, "id", None)
    if chat_id is None:
        chat_id = getattr(sent, "chat_id", None)
    if chat_id is None:
        peer = getattr(sent, "peer_id", None)
        if peer is not None:
            chat_id = (
                getattr(peer, "channel_id", None)
                or getattr(peer, "chat_id", None)
                or getattr(peer, "user_id", None)
            )
            if chat_id and getattr(peer, "channel_id", None):
                chat_id = int(f"-100{chat_id}")
    chat_id = _to_bot_chat_id(chat_id)
    return chat_id, msg_id

__all__ = [
    "_DB_OWNER",
    "_DB_LOADER",
    "_INTERVAL_OPTIONS",
    "_user_modules_dir",
    "_ensure_kitsune_folder",
    "_to_bot_chat_id",
    "_extract_msg_ids",
]
