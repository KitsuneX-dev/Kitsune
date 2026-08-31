import asyncio
import logging
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

from telethon.tl.functions.messages import (  # noqa: E402
    GetDialogFiltersRequest,
    UpdateDialogFilterRequest,
)
from telethon.tl.types import DialogFilter, InputPeerChannel, InputPeerUser  # noqa: E402

from kitsune.utils import (  # noqa: E402
    _KITSUNE_FOLDER_TITLE,
    _dialog_filter_title,
    ensure_kitsune_folder,
)

BOT_USERNAME = "kitsune_test_bot"


class FakeDB:
    def __init__(self, data):
        self._data = data

    def get(self, owner, key, default=None):
        return self._data.get(owner, {}).get(key, default)


class FakeDialog:
    def __init__(self, did, title, username=None, is_user=False, access_hash=1):
        self.id = did
        self.title = title
        self.entity = types.SimpleNamespace(
            id=did, username=username, access_hash=access_hash
        )
        self.is_user = is_user


class FakeFilters:
    def __init__(self, filters):
        self.filters = filters


class FakeClient:
    def __init__(self, dialogs, filters):
        self._dialogs = dialogs
        self._filters = filters
        self.updates = []
        self.deleted = []

    def iter_dialogs(self):
        async def gen():
            for d in self._dialogs:
                yield d
        return gen()

    async def get_input_entity(self, did):
        for d in self._dialogs:
            if d.id == did:
                if d.is_user:
                    return InputPeerUser(user_id=d.id, access_hash=d.entity.access_hash)
                return InputPeerChannel(channel_id=d.id, access_hash=d.entity.access_hash)
        raise ValueError(did)

    async def __call__(self, request):
        if isinstance(request, GetDialogFiltersRequest):
            return FakeFilters(list(self._filters))
        if isinstance(request, UpdateDialogFilterRequest):
            if request.filter is None:
                self.deleted.append(request.id)
                self._filters = [
                    f for f in self._filters if getattr(f, "id", None) != request.id
                ]
            else:
                self.updates.append((request.id, request.filter))
            return True
        raise AssertionError(f"unexpected request {request!r}")


def make_filter(fid, title, peers=()):
    return DialogFilter(
        id=fid,
        title=_dialog_filter_title(title),
        pinned_peers=[],
        include_peers=list(peers),
        exclude_peers=[],
    )


def base_dialogs():
    return [
        FakeDialog(1001, "KitsuneBackup"),
        FakeDialog(1002, "Kitsune-logs"),
        FakeDialog(1003, "kitsune-assets"),
        FakeDialog(2001, "Kitsune Notifier", username=BOT_USERNAME, is_user=True),
        FakeDialog(3001, "Random chat", username="someone_else", is_user=True),
    ]


def peer_ids(filt):
    out = set()
    for p in filt.include_peers:
        out.add(getattr(p, "channel_id", None) or getattr(p, "user_id", None))
    return out


def title_of(filt):
    t = filt.title
    return getattr(t, "text", t)


def check(name, cond):
    print(("  PASS  " if cond else "  FAIL  ") + name)
    if not cond:
        raise SystemExit(1)


async def case_bot_added():
    print("\n[1] Бот-нотификатор попадает в папку")
    db = FakeDB({"kitsune.notifier": {"bot_username": "@Kitsune_Test_Bot"}})
    client = FakeClient(base_dialogs(), [make_filter(2, "Work")])
    await ensure_kitsune_folder(client, db)
    check("выполнен ровно один UpdateDialogFilterRequest", len(client.updates) == 1)
    fid, filt = client.updates[0]
    ids = peer_ids(filt)
    check(f"бот 2001 в include_peers ({sorted(ids)})", 2001 in ids)
    check("служебные каналы на месте", {1001, 1002, 1003} <= ids)
    check("посторонний чат не добавлен", 3001 not in ids)
    check("название с эмодзи", title_of(filt) == _KITSUNE_FOLDER_TITLE)


async def case_no_db():
    print("\n[2] Без db бот не добавляется, остальное работает")
    client = FakeClient(base_dialogs(), [])
    await ensure_kitsune_folder(client, None)
    fid, filt = client.updates[0]
    ids = peer_ids(filt)
    check("бот отсутствует", 2001 not in ids)
    check("каналы добавлены", {1001, 1002, 1003} <= ids)


async def case_legacy_only():
    print("\n[3] Только легаси-папка 'Kitsune' — переиспользуется, дубля нет")
    db = FakeDB({"kitsune.notifier": {"bot_username": BOT_USERNAME}})
    legacy = make_filter(5, "Kitsune", [InputPeerChannel(channel_id=1001, access_hash=1)])
    client = FakeClient(base_dialogs(), [legacy])
    await ensure_kitsune_folder(client, db)
    check("один апдейт", len(client.updates) == 1)
    fid, filt = client.updates[0]
    check(f"переиспользован id легаси-папки (id={fid})", fid == 5)
    check("переименована в '🦊 Kitsune'", title_of(filt) == _KITSUNE_FOLDER_TITLE)
    check("бот добавлен", 2001 in peer_ids(filt))
    check("удалений не было", client.deleted == [])


async def case_both_folders():
    print("\n[4] Есть и '🦊 Kitsune', и легаси 'Kitsune' — дубль удаляется")
    db = FakeDB({"kitsune.notifier": {"bot_username": BOT_USERNAME}})
    current = make_filter(4, _KITSUNE_FOLDER_TITLE, [InputPeerChannel(channel_id=1001, access_hash=1)])
    legacy = make_filter(
        7, "Kitsune",
        [InputPeerChannel(channel_id=1002, access_hash=1),
         InputPeerChannel(channel_id=1003, access_hash=1)],
    )
    client = FakeClient(base_dialogs(), [current, legacy])
    await ensure_kitsune_folder(client, db)
    check(f"легаси-папка удалена (deleted={client.deleted})", client.deleted == [7])
    check("один апдейт основной папки", len(client.updates) == 1)
    fid, filt = client.updates[0]
    check(f"использован id актуальной папки (id={fid})", fid == 4)
    ids = peer_ids(filt)
    check("нет дублей peer'ов", len(ids) == len(filt.include_peers))
    check("бот и все каналы на месте", {1001, 1002, 1003, 2001} <= ids)


async def case_foreign_legacy():
    print("\n[5] Легаси-папка с посторонними чатами — НЕ удаляется, только WARNING")
    db = FakeDB({"kitsune.notifier": {"bot_username": BOT_USERNAME}})
    current = make_filter(4, _KITSUNE_FOLDER_TITLE)
    legacy = make_filter(
        7, "Kitsune",
        [InputPeerChannel(channel_id=999999, access_hash=1)],
    )
    client = FakeClient(base_dialogs(), [current, legacy])
    await ensure_kitsune_folder(client, db)
    check("пользовательская папка НЕ удалена", client.deleted == [])
    fid, filt = client.updates[0]
    check("основная папка обновлена", fid == 4 and 2001 in peer_ids(filt))


async def main():
    await case_bot_added()
    await case_no_db()
    await case_legacy_only()
    await case_both_folders()
    await case_foreign_legacy()
    print("\nВСЕ ТЕСТЫ ПРОЙДЕНЫ")


asyncio.run(main())
