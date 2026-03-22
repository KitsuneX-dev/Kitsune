
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from ..core.loader import KitsuneModule, command, ModuleLoadError, ASTSecurityError  # noqa: F401
from ..core.security import OWNER
from ..utils import auto_delete, ProgressMessage
from ..hydro_media import download_media as hydro_download

logger = logging.getLogger(__name__)

_DB_OWNER         = "kitsune.loader"
_DB_KEY_MODS      = "user_modules"
_USER_MODULES_DIR = Path.home() / ".kitsune" / "modules"

_ALLOWED_HOSTS = {"raw.githubusercontent.com", "github.com", "gist.githubusercontent.com"}

def _is_github_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc.lower().lstrip("www.")
        return host in _ALLOWED_HOSTS
    except Exception:
        return False

class LoaderModule(KitsuneModule):
    name        = "loader"
    description = "Управление модулями"
    author      = "Yushi"

    strings_ru = {
        "loading":        "⏳ Загружаю <code>{name}</code>...",
        "loaded":         "✅ Модуль <b>{name}</b> v{ver} загружен.",
        "reloaded":       "🔄 Модуль <b>{name}</b> v{ver} перезагружен.",
        "unloaded":       "✅ Модуль <b>{name}</b> выгружен.",
        "not_found":      "❌ Модуль <code>{name}</code> не найден.",
        "security_err":   "🚫 Модуль отклонён (нарушение безопасности):\n<code>{err}</code>",
        "load_err":       "❌ Ошибка загрузки:\n<code>{err}</code>",
        "requires_err":   "🔗 Сначала загрузи зависимости:\n<code>{deps}</code>",
        "not_github":     "❌ Только GitHub! Укажи ссылку на raw.githubusercontent.com",
        "no_url":         "❌ Укажи ссылку: <code>.dlmod https://raw.githubusercontent.com/...</code>",
        "no_file":        "❌ Ответь на .py файл чтобы загрузить модуль.",
        "no_name":        "❌ Укажи имя модуля: <code>.unloadmod имя</code>",
        "mods_header":    "📦 <b>Загружённые модули:</b>\n\n",
        "mod_line":       "  • <b>{name}</b> v{ver} — {desc}\n",
        "no_mods":        "Нет загруженных модулей.",
        "watch_on":       "👁 Слежу за изменениями в <code>~/.kitsune/modules/</code>",
        "watch_off":      "👁 Слежение за файлами отключено.",
        "auto_reload":    "🔄 Авто-перезагрузка: <b>{name}</b>",
        "auto_err":       "❌ Авто-перезагрузка <b>{name}</b> провалилась:\n<code>{err}</code>",
    }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._watch_mtimes: dict[str, float] = {}
        self._watch_task: asyncio.Task | None = None

    async def on_load(self) -> None:
        saved = self.db.get(_DB_OWNER, _DB_KEY_MODS, [])
        if saved:
            loader = self._get_loader()
            if loader:
                for url in saved:
                    try:
                        await loader.load_from_url(url)
                    except Exception as exc:
                        logger.warning("Loader: failed to restore %s — %s", url, exc)

        if self.db.get(_DB_OWNER, "watch_enabled", False):
            self._start_watcher()

    async def on_unload(self) -> None:
        self._stop_watcher()

    @command("dlmod", required=OWNER)
    async def dlmod_cmd(self, event) -> None:
        url = self.get_args(event).strip()
        if not url:
            await event.reply(self.strings("no_url"), parse_mode="html")
            return

        if not _is_github_url(url):
            await event.reply(self.strings("not_github"), parse_mode="html")
            return

        url = _to_raw_url(url)

        m = await event.reply(
            self.strings("loading").format(name=url.split("/")[-1]),
            parse_mode="html",
        )
        loader = self._get_loader()
        if not loader:
            return

        try:
            async with ProgressMessage(
                event,
                f"⬇️ Загружаю <code>{url.split('/')[-1]}</code>...",
                total=3,
            ) as prog:
                await prog.update(1)
                mod = await loader.load_from_url(url)
                await prog.update(2)
                saved = list(self.db.get(_DB_OWNER, _DB_KEY_MODS, []))
                if url not in saved:
                    saved.append(url)
                    await self.db.set(_DB_OWNER, _DB_KEY_MODS, saved)
                await prog.done(
                    self.strings("loaded").format(name=mod.name, ver=mod.version)
                )
        except ASTSecurityError as exc:
            await m.edit(self.strings("security_err").format(err=str(exc)), parse_mode="html")
            await auto_delete(m, delay=10)
        except ModuleLoadError as exc:
            await m.edit(self._fmt_load_err(exc), parse_mode="html")
            await auto_delete(m, delay=10)
        except Exception as exc:
            await m.edit(self.strings("load_err").format(err=str(exc)), parse_mode="html")
            await auto_delete(m, delay=10)

    @command("loadmod", required=OWNER)
    async def loadmod_cmd(self, event) -> None:
        reply = await event.message.get_reply_message()
        if not reply or not reply.file:
            await event.reply(self.strings("no_file"), parse_mode="html")
            return

        fname = getattr(reply.file, "name", "") or ""
        if not fname.endswith(".py"):
            await event.reply("❌ Файл должен быть .py", parse_mode="html")
            return

        m = await event.reply(
            self.strings("loading").format(name=fname),
            parse_mode="html",
        )
        loader = self._get_loader()
        if not loader:
            return

        try:
            raw: bytes = await hydro_download(self.client, reply)
            source = raw.decode("utf-8")

            _USER_MODULES_DIR.mkdir(parents=True, exist_ok=True)
            dest = _USER_MODULES_DIR / fname
            dest.write_text(source, encoding="utf-8")

            mod = await loader.load_from_file(dest)
            await m.edit(
                self.strings("loaded").format(name=mod.name, ver=mod.version),
                parse_mode="html",
            )
        except ASTSecurityError as exc:
            await m.edit(self.strings("security_err").format(err=str(exc)), parse_mode="html")
        except ModuleLoadError as exc:
            await m.edit(self._fmt_load_err(exc), parse_mode="html")
        except Exception as exc:
            await m.edit(self.strings("load_err").format(err=str(exc)), parse_mode="html")

    @command("unloadmod", required=OWNER)
    async def unloadmod_cmd(self, event) -> None:
        name = self.get_args(event).strip().lower()
        if not name:
            await event.reply(self.strings("no_name"), parse_mode="html")
            return

        loader = self._get_loader()
        if loader and await loader.unload(name):
            saved = [u for u in self.db.get(_DB_OWNER, _DB_KEY_MODS, []) if name not in u.lower()]
            await self.db.set(_DB_OWNER, _DB_KEY_MODS, saved)
            await event.reply(self.strings("unloaded").format(name=name), parse_mode="html")
        else:
            await event.reply(self.strings("not_found").format(name=name), parse_mode="html")

    @command("reloadmod", required=OWNER)
    async def reloadmod_cmd(self, event) -> None:
        name = self.get_args(event).strip().lower()
        if not name:
            await event.reply("❌ Укажи имя модуля.", parse_mode="html")
            return

        loader = self._get_loader()
        if not loader:
            return

        path = self._find_module_path(name)

        if path is None:
            saved_urls: list[str] = self.db.get(_DB_OWNER, _DB_KEY_MODS, [])
            url = next((u for u in saved_urls if name in u.lower()), None)
            if not url:
                await event.reply(self.strings("not_found").format(name=name), parse_mode="html")
                return
            m = await event.reply(self.strings("loading").format(name=name), parse_mode="html")
            try:
                mod = await loader.load_from_url(url)
                await m.edit(
                    self.strings("reloaded").format(name=mod.name, ver=mod.version),
                    parse_mode="html",
                )
            except Exception as exc:
                await m.edit(self.strings("load_err").format(err=str(exc)), parse_mode="html")
            return

        m = await event.reply(self.strings("loading").format(name=name), parse_mode="html")
        try:
            mod = await loader.load_from_file(path)
            await m.edit(
                self.strings("reloaded").format(name=mod.name, ver=mod.version),
                parse_mode="html",
            )
        except ASTSecurityError as exc:
            await m.edit(self.strings("security_err").format(err=str(exc)), parse_mode="html")
        except ModuleLoadError as exc:
            await m.edit(self._fmt_load_err(exc), parse_mode="html")
        except Exception as exc:
            await m.edit(self.strings("load_err").format(err=str(exc)), parse_mode="html")

    @command("watchmod", required=OWNER)
    async def watchmod_cmd(self, event) -> None:
        enabled = not self.db.get(_DB_OWNER, "watch_enabled", False)
        await self.db.set(_DB_OWNER, "watch_enabled", enabled)
        if enabled:
            self._start_watcher()
            await event.reply(self.strings("watch_on"), parse_mode="html")
        else:
            self._stop_watcher()
            await event.reply(self.strings("watch_off"), parse_mode="html")

    @command("mods", required=OWNER)
    async def mods_cmd(self, event) -> None:
        loader = self._get_loader()
        if not loader or not loader.modules:
            await event.reply(self.strings("no_mods"), parse_mode="html")
            return

        text = self.strings("mods_header")
        for mod_name, mod in sorted(loader.modules.items()):
            text += self.strings("mod_line").format(
                name=mod.name or mod_name,
                ver=mod.version,
                desc=mod.description or "—",
            )
        await event.reply(text, parse_mode="html")


    @command("dlm", required=OWNER)
    async def dlm_cmd(self, event) -> None:
        await self.dlmod_cmd(event)

    @command("lm", required=OWNER)
    async def lm_cmd(self, event) -> None:
        await self.loadmod_cmd(event)

    def _start_watcher(self) -> None:
        self._stop_watcher()
        self._watch_mtimes = self._scan_mtimes()
        self._watch_task = asyncio.ensure_future(self._watch_loop())
        logger.info("Loader: file watcher started")

    def _stop_watcher(self) -> None:
        if self._watch_task and not self._watch_task.done():
            self._watch_task.cancel()
        self._watch_task = None

    def _scan_mtimes(self) -> dict[str, float]:
        mtimes: dict[str, float] = {}
        if _USER_MODULES_DIR.exists():
            for path in _USER_MODULES_DIR.glob("*.py"):
                if not path.name.startswith("_"):
                    try:
                        mtimes[path.name] = path.stat().st_mtime
                    except OSError:
                        pass
        return mtimes

    async def _watch_loop(self) -> None:
        while True:
            await asyncio.sleep(2)
            try:
                await self._check_changes()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Loader: watcher error")

    async def _check_changes(self) -> None:
        current = self._scan_mtimes()
        loader  = self._get_loader()
        if not loader:
            return
        for filename, mtime in current.items():
            old = self._watch_mtimes.get(filename)
            if old is None or mtime != old:
                path = _USER_MODULES_DIR / filename
                logger.info("Loader: file %s — reloading", filename)
                await self._auto_reload(loader, path)
        self._watch_mtimes = current

    async def _auto_reload(self, loader, path: Path) -> None:
        try:
            mod = await loader.load_from_file(path)
            await self.client.send_message(
                "me",
                self.strings("auto_reload").format(name=mod.name),
                parse_mode="html",
            )
        except Exception as exc:
            logger.error("Loader: auto-reload failed for %s — %s", path.name, exc)
            await self.client.send_message(
                "me",
                self.strings("auto_err").format(name=path.stem, err=str(exc)[:300]),
                parse_mode="html",
            )

    def _get_loader(self):
        return getattr(self.client, "_kitsune_loader", None)

    def _find_module_path(self, name: str) -> Path | None:
        user_path = _USER_MODULES_DIR / f"{name}.py"
        if user_path.exists():
            return user_path
        from ..core.loader import _BUILTIN_MODULES_DIR
        builtin_path = _BUILTIN_MODULES_DIR / f"{name}.py"
        if builtin_path.exists():
            return builtin_path
        return None

    def _fmt_load_err(self, exc: ModuleLoadError) -> str:
        err = str(exc)
        if "requires" in err:
            deps = err.split("requires")[-1].strip().strip("[]").replace("'", "")
            return self.strings("requires_err").format(deps=deps)
        return self.strings("load_err").format(err=err)

def _to_raw_url(url: str) -> str:
    if "raw.githubusercontent.com" in url:
        return url
    url = url.replace("https://github.com/", "https://raw.githubusercontent.com/")
    url = url.replace("/blob/", "/")
    return url
