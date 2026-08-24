from __future__ import annotations
import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any

from .paths import (
    data_dir as _primary_data_dir,
    harden_dir as _harden_dir,
    harden_file as _harden_file,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_ACCOUNTS = 3

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def accounts_root() -> Path:

    return _harden_dir(_primary_data_dir() / "accounts")


def registry_path() -> Path:
    return _primary_data_dir() / "accounts.json"


def _read_registry() -> dict[str, Any]:
    p = registry_path()
    if not p.exists():
        return {"accounts": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"accounts": {}}
        data.setdefault("accounts", {})
        return data
    except Exception:
        logger.exception("accounts: failed to read registry")
        return {"accounts": {}}


def _write_registry(data: dict[str, Any]) -> None:
    p = registry_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
        with contextlib.suppress(Exception):
            _harden_file(p)
    except Exception:
        logger.exception("accounts: failed to write registry")


def _slugify(name: str) -> str:
    base = _SLUG_RE.sub("_", str(name).strip().lower()).strip("_")
    if not base:
        base = "acc"
    return base[:32]


def _max_accounts_from_config() -> int:
    try:
        from .main import get_config_key
        val = get_config_key("max_extra_accounts", None)
        if val is not None:
            return max(0, int(val))
    except Exception:
        pass
    env = os.environ.get("KITSUNE_MAX_EXTRA_ACCOUNTS", "").strip()
    if env:
        with contextlib.suppress(ValueError):
            return max(0, int(env))
    return DEFAULT_MAX_ACCOUNTS


class AccountsManager:
    def __init__(self) -> None:
        self._procs: dict[str, asyncio.subprocess.Process] = {}
        self._lock = asyncio.Lock()
        self._registry_lock = asyncio.Lock()

    @property
    def max_accounts(self) -> int:
        return _max_accounts_from_config()

    def _new_slug(self, name: str, existing: dict[str, Any]) -> str:
        base = _slugify(name)
        slug = base
        i = 1
        while slug in existing:
            i += 1
            slug = f"{base}_{i}"
        return slug

    def account_dir(self, slug: str) -> Path:
        return accounts_root() / slug

    def list_accounts(self) -> list[dict[str, Any]]:
        reg = _read_registry()
        out: list[dict[str, Any]] = []
        for slug, meta in reg.get("accounts", {}).items():
            running = self.is_running(slug)
            out.append({
                "slug": slug,
                "name": meta.get("name", slug),
                "phone": meta.get("phone", ""),
                "user_id": meta.get("user_id", 0),
                "username": meta.get("username", ""),
                "enabled": bool(meta.get("enabled", False)),
                "running": running,
                "created_at": meta.get("created_at", 0),
                "last_error": meta.get("last_error", ""),
            })
        out.sort(key=lambda a: a.get("created_at", 0))
        return out

    def get_meta(self, slug: str) -> dict[str, Any] | None:
        return _read_registry().get("accounts", {}).get(slug)

    def count(self) -> int:
        return len(_read_registry().get("accounts", {}))

    def can_add(self) -> bool:
        return self.count() < self.max_accounts

    def create_account(self, name: str) -> dict[str, Any]:
        reg = _read_registry()
        accounts = reg.setdefault("accounts", {})
        if len(accounts) >= self.max_accounts:
            raise RuntimeError(
                f"Достигнут лимит доп.аккаунтов ({self.max_accounts})."
            )
        slug = self._new_slug(name, accounts)
        adir = self.account_dir(slug)


        _harden_dir(adir)
        _harden_dir(adir / "modules")
        _harden_dir(adir / "logs")
        meta = {
            "name": name or slug,
            "slug": slug,
            "phone": "",
            "user_id": 0,
            "username": "",
            "enabled": False,
            "created_at": int(time.time()),
            "last_error": "",
        }
        accounts[slug] = meta
        _write_registry(reg)
        logger.info("accounts: создан доп.аккаунт '%s' (%s)", name, slug)
        return meta

    def update_meta(self, slug: str, **fields: Any) -> None:
        reg = _read_registry()
        accounts = reg.get("accounts", {})
        if slug not in accounts:
            return
        accounts[slug].update(fields)
        _write_registry(reg)

    def _env_for(self, slug: str) -> dict[str, str]:
        adir = self.account_dir(slug)
        env = dict(os.environ)
        env["KITSUNE_DATA_DIR"] = str(adir)
        env["KITSUNE_CONFIG"] = str(adir / "config.toml")
        env.pop("KITSUNE_KEY", None)
        return env

    def session_exists(self, slug: str) -> bool:
        adir = self.account_dir(slug)
        return (
            (adir / "kitsune.session").exists()
            or (adir / "kitsune.session.enc").exists()
        )

    def is_running(self, slug: str) -> bool:
        proc = self._procs.get(slug)
        if proc is None:
            return False
        return proc.returncode is None

    async def start_account(self, slug: str) -> dict[str, Any]:
        async with self._lock:
            meta = self.get_meta(slug)
            if meta is None:
                raise RuntimeError("Доп.аккаунт не найден.")
            if not self.session_exists(slug):
                raise RuntimeError(
                    "Сессия доп.аккаунта не создана. Сначала пройди регистрацию."
                )
            if self.is_running(slug):
                return {"ok": True, "running": True, "already": True}
            adir = self.account_dir(slug)
            log_path = adir / "process.log"
            log_fh = open(log_path, "ab", buffering=0)
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "kitsune", "--no-web",
                    cwd=str(adir),
                    env=self._env_for(slug),
                    stdout=log_fh,
                    stderr=log_fh,
                    stdin=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception as exc:
                with contextlib.suppress(Exception):
                    log_fh.close()
                self.update_meta(slug, last_error=str(exc)[:200])
                raise
            self._procs[slug] = proc
            self.update_meta(slug, enabled=True, last_error="")
            logger.info(
                "accounts: доп.аккаунт '%s' запущен (pid=%s)", slug, proc.pid,
            )
            asyncio.ensure_future(self._watch(slug, proc, log_fh))
            return {"ok": True, "running": True, "pid": proc.pid}

    async def _watch(
        self,
        slug: str,
        proc: asyncio.subprocess.Process,
        log_fh: Any,
    ) -> None:
        try:
            rc = await proc.wait()
        except Exception:
            rc = -1
        finally:
            with contextlib.suppress(Exception):
                log_fh.close()
        if self._procs.get(slug) is proc:
            self._procs.pop(slug, None)
        meta = self.get_meta(slug)
        was_enabled = bool(meta.get("enabled", False)) if meta else False
        logger.info(
            "accounts: доп.аккаунт '%s' завершился (rc=%s, enabled=%s)",
            slug, rc, was_enabled,
        )
        if was_enabled and rc not in (0, None):
            self.update_meta(slug, last_error=f"процесс упал (код {rc})")

    async def stop_account(self, slug: str, *, disable: bool = True) -> dict[str, Any]:
        async with self._lock:
            proc = self._procs.get(slug)
            if disable:
                self.update_meta(slug, enabled=False)
            if proc is None or proc.returncode is not None:
                self._procs.pop(slug, None)
                return {"ok": True, "running": False}
            try:
                if hasattr(os, "killpg"):
                    with contextlib.suppress(ProcessLookupError, PermissionError):
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                else:
                    proc.terminate()
            except Exception:
                with contextlib.suppress(Exception):
                    proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=12.0)
            except asyncio.TimeoutError:
                with contextlib.suppress(Exception):
                    if hasattr(os, "killpg"):
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
            self._procs.pop(slug, None)
            logger.info("accounts: доп.аккаунт '%s' остановлен", slug)
            return {"ok": True, "running": False}

    async def delete_account(self, slug: str) -> dict[str, Any]:
        await self.stop_account(slug, disable=True)
        import shutil
        adir = self.account_dir(slug)
        with contextlib.suppress(Exception):
            if adir.exists():
                shutil.rmtree(adir, ignore_errors=True)
        reg = _read_registry()
        reg.get("accounts", {}).pop(slug, None)
        _write_registry(reg)
        logger.info("accounts: доп.аккаунт '%s' удалён", slug)
        return {"ok": True}

    async def start_enabled(self) -> None:
        for meta in self.list_accounts():
            slug = meta["slug"]
            if meta.get("enabled") and self.session_exists(slug) and not self.is_running(slug):
                with contextlib.suppress(Exception):
                    await self.start_account(slug)

    async def shutdown_all(self) -> None:
        for slug in list(self._procs.keys()):
            with contextlib.suppress(Exception):
                await self.stop_account(slug, disable=False)


_MANAGER: AccountsManager | None = None


def get_manager() -> AccountsManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = AccountsManager()
    return _MANAGER
