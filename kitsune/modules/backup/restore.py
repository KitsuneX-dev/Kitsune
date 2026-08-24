from __future__ import annotations
import io
import json
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

from ...core.loader import command
from ...core.loader import _scan_ast_with_cache as _scan_ast
from ...core.security import OWNER
from ...hydro_media import download_media as hydro_download
from ...paths import data_dir as _kdd
from ...utils import ProgressMessage
from .helpers import _DB_LOADER, _DB_OWNER, _user_modules_dir

logger = logging.getLogger(__name__)


def _quarantine_dir() -> Path:
    path = _kdd() / "quarantine"
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError as exc:
        logger.debug("backup: не удалось выставить права на карантин: %s", exc)
    return path


class RestoreMixin:

    async def _do_restore_db(self, raw: bytes) -> bool:
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
        _kept_backup_ns = self.db.get(_DB_OWNER, None, None)
        if isinstance(_kept_backup_ns, dict):
            _kept_backup_ns = dict(_kept_backup_ns)
        else:
            _kept_backup_ns = None
        self.db.clear()
        for owner, keys in db_data.items():
            if isinstance(keys, dict):
                for key, val in keys.items():
                    self.db.set_sync(owner, key, val)
        if _kept_backup_ns:
            restored_cbs = _kept_backup_ns.get("restore_callbacks")
            if isinstance(restored_cbs, dict) and restored_cbs:
                merged = self.db.get(_DB_OWNER, "restore_callbacks", {}) or {}
                if not isinstance(merged, dict):
                    merged = {}
                for cb_id, info in restored_cbs.items():
                    merged.setdefault(cb_id, info)
                self.db.set_sync(_DB_OWNER, "restore_callbacks", merged)
        await self.db.force_save()
        return True
    @command("restoredb", required=OWNER)
    async def restoredb_cmd(self, event) -> None:
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
    @staticmethod
    def _media_name(msg) -> str:
        try:
            for attr in getattr(getattr(msg, "document", None), "attributes", None) or ():
                name = getattr(attr, "file_name", None)
                if name:
                    return str(name)
            name = getattr(getattr(msg, "file", None), "name", None)
            if name:
                return str(name)
        except Exception as exc:
            logger.debug("backup: имя файла бэкапа не определено: %s", exc)
        return ""

    async def _do_restore_mods(
        self, raw: bytes, backup_name: str = ""
    ) -> tuple[int, int] | None:
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
        return await self._restore_mods_from_zip(mods_zip_bytes, backup_name)
    @command("restoremods", required=OWNER)
    async def restoremods_cmd(self, event) -> None:
        reply = await event.message.get_reply_message()
        if not reply or not reply.media:
            await event.reply(
                "❌ Ответь на файл <code>.zip</code> или <code>.backup</code>",
                parse_mode="html",
            )
            return
        async with ProgressMessage(event, self.strings("mods_restoring"), total=3) as prog:
            raw = await hydro_download(self.client, reply)
            result = await self._do_restore_mods(raw, self._media_name(reply))
            if result is None:
                await prog.done(self.strings("mods_bad_file"))
                return
            count, cfg_count = result
            await prog.done(
                self.strings("mods_restored").format(count=count, cfg=cfg_count)
                + self._quarantine_report()
            )
    async def _do_restore_all(self, raw: bytes, backup_name: str = "") -> int | None:
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
                _kept_backup_ns = self.db.get(_DB_OWNER, None, None)
                if isinstance(_kept_backup_ns, dict):
                    _kept_backup_ns = dict(_kept_backup_ns)
                else:
                    _kept_backup_ns = None
                self.db.clear()
                for owner, keys in db_data.items():
                    if isinstance(keys, dict):
                        for key, val in keys.items():
                            self.db.set_sync(owner, key, val)
                if _kept_backup_ns:
                    restored_cbs = _kept_backup_ns.get("restore_callbacks")
                    if isinstance(restored_cbs, dict) and restored_cbs:
                        merged = self.db.get(_DB_OWNER, "restore_callbacks", {}) or {}
                        if not isinstance(merged, dict):
                            merged = {}
                        for cb_id, info in restored_cbs.items():
                            merged.setdefault(cb_id, info)
                        self.db.set_sync(_DB_OWNER, "restore_callbacks", merged)
                await self.db.force_save()
                count     = 0
                if "mods.zip" in names:
                    mods_zip_bytes   = zf.open("mods.zip").read()
                    count, cfg_count = await self._restore_mods_from_zip(
                        mods_zip_bytes, backup_name
                    )
                    logger.info(
                        "restoreall: восстановлено модулей — %d, конфигов модулей — %d",
                        count, cfg_count,
                    )
                return count
        except Exception:
            logger.exception("restoreall: ошибка")
            return None
    @command("restoreall", required=OWNER)
    async def restoreall_cmd(self, event) -> None:
        reply = await event.message.get_reply_message()
        if not reply or not reply.media:
            await event.reply("❌ Ответь на файл <code>.backup</code>", parse_mode="html")
            return
        async with ProgressMessage(event, self.strings("all_restoring"), total=5) as prog:
            raw   = await hydro_download(self.client, reply)
            count = await self._do_restore_all(raw, self._media_name(reply))
            if count is None:
                await prog.done(self.strings("all_bad_file"))
                return
            await prog.done(self.strings("all_restored") + self._quarantine_report())
    async def _cb_restore(self, call, chat_id: int, msg_id: int, kind: str) -> None:
        try:
            await call.answer(self.strings("restore_alert"))
        except Exception:
            pass
        inline = self._inline()
        ts     = self._ts()
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
        try:
            if kind == "db":
                ok = await self._do_restore_db(raw)
                if not ok:
                    raise RuntimeError("bad DB format")
                final = self.strings("restore_done_db").format(ts=ts)
            elif kind == "mods":
                result = await self._do_restore_mods(raw, self._media_name(msg))
                if result is None:
                    raise RuntimeError("bad mods format")
                count, cfg_count = result
                final = (
                    self.strings("restore_done_mods").format(ts=ts, count=count, cfg=cfg_count)
                    + self._quarantine_report()
                )
            else:
                count = await self._do_restore_all(raw, self._media_name(msg))
                if count is None:
                    raise RuntimeError("bad backup format")
                final = (
                    self.strings("restore_done_all").format(ts=ts, count=count)
                    + self._quarantine_report()
                )
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
        if inline:
            try:
                await inline.edit(call, final, [])
            except Exception:
                pass
    def _quarantine_file(
        self, tmp_path: Path, fname: str, backup_name: str, reason: str
    ) -> None:
        target: Path | None = None
        try:
            qdir   = _quarantine_dir()
            stamp  = self._fname_ts()
            target = qdir / f"{stamp}-{fname}"
            attempt = 1
            while target.exists():
                target = qdir / f"{stamp}-{attempt}-{fname}"
                attempt += 1
            shutil.move(str(tmp_path), str(target))
        except Exception as exc:
            logger.error("restoremods: карантин для %s не удался: %s", fname, exc)
            target = None
        self._rejected.append({
            "file":   fname,
            "source": backup_name or "—",
            "reason": reason,
            "path":   str(target) if target else "",
        })

    def _quarantine_report(self) -> str:
        if not self._rejected:
            return ""
        items = "\n".join(
            self.strings("quarantine_item").format(
                file=info["file"],
                source=info["source"],
                reason=str(info["reason"]).replace("<", "&lt;").replace(">", "&gt;")[:300],
            )
            for info in self._rejected
        )
        return self.strings("quarantine_head").format(
            count=len(self._rejected), items=items
        )

    async def _install_module_file(
        self,
        zf: zipfile.ZipFile,
        name: str,
        fname: str,
        backup_name: str,
        loader_inst,
    ) -> bool:
        tmp_dir  = Path(tempfile.mkdtemp(prefix="kitsune-restore-"))
        tmp_path = tmp_dir / fname
        try:
            try:
                tmp_path.write_bytes(zf.open(name).read())
            except Exception as exc:
                logger.error("restoremods: распаковка %s: %s", fname, exc)
                return False
            try:
                source = tmp_path.read_text(encoding="utf-8")
                _scan_ast(source, filename=fname)
            except Exception as exc:
                self._quarantine_file(tmp_path, fname, backup_name, str(exc))
                logger.warning("restoremods: %s отклонён проверкой: %s", fname, exc)
                return False
            dest_path = _user_modules_dir() / fname
            try:
                if dest_path.exists():
                    dest_path.unlink()
                shutil.move(str(tmp_path), str(dest_path))
            except Exception as exc:
                logger.error("restoremods: запись %s: %s", fname, exc)
                return False
            if loader_inst:
                try:
                    await loader_inst.load_from_file(dest_path)
                except Exception as exc:
                    logger.warning("restoremods: загрузка %s: %s", fname, exc)
            return True
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    async def _restore_mods_from_zip(
        self, mods_zip_bytes: bytes, backup_name: str = ""
    ) -> tuple[int, int]:
        _user_modules_dir().mkdir(parents=True, exist_ok=True)
        loader_inst = getattr(self.client, "_kitsune_loader", None)
        count     = 0
        cfg_count = 0
        self._rejected = []
        try:
            with zipfile.ZipFile(io.BytesIO(mods_zip_bytes)) as zf:
                names = zf.namelist()


                if "urls.json" in names:
                    try:
                        url_map = json.loads(zf.open("urls.json").read().decode("utf-8"))
                        if isinstance(url_map, dict):
                            await self.db.set(_DB_LOADER, "user_modules", url_map)
                    except Exception as e:
                        logger.warning("restoremods: urls.json: %s", e)


                if "configs.json" in names:
                    try:
                        configs = json.loads(zf.open("configs.json").read().decode("utf-8"))
                        if isinstance(configs, dict):
                            for owner, keys in configs.items():

                                if not owner.startswith("kitsune.config."):
                                    continue
                                if not isinstance(keys, dict):
                                    continue
                                for key, val in keys.items():
                                    self.db.set_sync(owner, key, val)
                                cfg_count += 1
                            if cfg_count:
                                await self.db.force_save()
                                logger.info(
                                    "restoremods: конфиги восстановлены (%d пространств)", cfg_count
                                )

                                try:
                                    loader = getattr(self.client, "_kitsune_loader", None)
                                    if loader and hasattr(loader, "_modules"):
                                        for mod in loader._modules.values():
                                            if hasattr(mod, "_load_config_from_db"):
                                                try:
                                                    mod._load_config_from_db()
                                                except Exception:
                                                    pass
                                except Exception as exc:
                                    logger.debug("restoremods: hot-reload конфигов не удался: %s", exc)
                    except Exception as e:
                        logger.warning("restoremods: configs.json: %s", e)


                for name in names:
                    if not name.endswith(".py"):
                        continue
                    fname = Path(name).name
                    if await self._install_module_file(
                        zf, name, fname, backup_name, loader_inst
                    ):
                        count += 1
        except Exception:
            logger.exception("restoremods: ошибка при разборе mods.zip")
        return count, cfg_count

__all__ = ["RestoreMixin", "_quarantine_dir"]
