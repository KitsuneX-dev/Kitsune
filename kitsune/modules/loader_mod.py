from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path

import aiohttp

from ..core.loader import KitsuneModule, command, ModuleConfig, ConfigValue
from ..core.security import OWNER

logger = logging.getLogger(__name__)

_DB_OWNER = "kitsune.loader"


class LoaderModule(KitsuneModule):
    """Загрузка, выгрузка и управление модулями."""

    name        = "Loader"
    description = "Управление модулями"
    author      = "@Mikasu32"
    version     = "1.0"
    _builtin    = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = ModuleConfig(
            ConfigValue(
                "MODULES_REPO",
                default="https://raw.githubusercontent.com/KitsuneX-dev/modules/main",
                doc="Основной репозиторий модулей",
            ),
            ConfigValue(
                "ADDITIONAL_REPOS",
                default=[],
                doc="Дополнительные репозитории (список URL)",
            ),
        )

    strings_ru = {
        "installing":       "⏳ Устанавливаю <code>{name}</code>...",
        "installed":        "✅ Модуль <b>{name}</b> установлен.",
        "install_fail":     "❌ Не удалось установить <b>{name}</b>:\n<code>{err}</code>",
        "no_module":        "❌ Модуль <code>{name}</code> не найден в репозиториях.",
        "unloaded":         "✅ Модуль <b>{name}</b> выгружен.",
        "not_loaded":       "❌ Модуль <code>{name}</code> не загружен.",
        "no_args":          "❌ Укажи название или URL модуля.",
        "no_file":          "❌ Ответь на файл .py или прикрепи его.",
        "bad_file":         "❌ Не удалось прочитать файл. Убедись что это .py файл.",
        "loading":          "⏳ Загружаю модуль из файла...",
        "ml_info":          "📦 <b>{name}</b>\nURL: <code>{url}</code>",
        "ml_file":          "📦 <b>{name}</b> — встроенный/локальный модуль.",
        "ml_not_found":     "❌ Модуль <code>{name}</code> не найден.",
        "cleared":          "✅ Все пользовательские модули выгружены.",
        "repo_added":       "✅ Репозиторий добавлен: <code>{url}</code>",
        "repo_exists":      "ℹ️ Репозиторий уже добавлен: <code>{url}</code>",
        "repo_removed":     "✅ Репозиторий удалён: <code>{url}</code>",
        "repo_not_found":   "❌ Репозиторий не найден: <code>{url}</code>",
        "repo_invalid":     "❌ Неверный URL репозитория.",
        "repos_list":       "📋 <b>Репозитории:</b>\n{list}",
    }

    # ─── helpers ──────────────────────────────────────────────────────────

    def _loader(self):
        return getattr(self.client, "_kitsune_loader", None)

    def _get_user_modules(self) -> dict:
        return self.db.get(_DB_OWNER, "user_modules", {})

    async def _save_user_modules(self, mods: dict) -> None:
        await self.db.set(_DB_OWNER, "user_modules", mods)

    async def _find_in_repos(self, name: str) -> str | None:
        """Ищет модуль в репозиториях, возвращает URL или None."""
        repos = [self.config["MODULES_REPO"]] + (self.config["ADDITIONAL_REPOS"] or [])

        for repo in repos:
            repo = repo.rstrip("/")
            # try direct URL
            candidates = [
                f"{repo}/{name}.py",
                f"{repo}/{name.lower()}.py",
            ]
            # try full.txt index
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(f"{repo}/full.txt", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            for line in text.splitlines():
                                line = line.strip()
                                if line.lower().endswith(f"/{name.lower()}.py"):
                                    candidates.insert(0, line if line.startswith("http") else f"{repo}/{line}")
            except Exception:
                pass

            for url in candidates:
                try:
                    async with aiohttp.ClientSession() as sess:
                        async with sess.head(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                            if resp.status == 200:
                                return url
                except Exception:
                    continue

        return None

    # ─── команды ──────────────────────────────────────────────────────────

    @command("dlmod", required=OWNER, aliases=["dlm"])
    async def dlmod_cmd(self, event) -> None:
        """.dlmod <название|URL> — скачать и установить модуль."""
        arg = self.get_args(event).strip()
        if not arg:
            await event.message.edit(self.strings("no_args"), parse_mode="html")
            return

        await event.message.edit(
            self.strings("installing").format(name=arg), parse_mode="html"
        )

        loader = self._loader()
        if not loader:
            return

        # direct URL
        if arg.startswith("http"):
            url = arg.replace("/blob/", "/raw/")
        else:
            url = await self._find_in_repos(arg)
            if not url:
                await event.message.edit(
                    self.strings("no_module").format(name=arg), parse_mode="html"
                )
                return

        try:
            mod = await loader.load_from_url(url)
            user_mods = self._get_user_modules()
            user_mods[mod.name] = url
            await self._save_user_modules(user_mods)
            await event.message.edit(
                self.strings("installed").format(name=mod.name), parse_mode="html"
            )
        except Exception as exc:
            logger.exception("dlmod: failed to install %s", url)
            await event.message.edit(
                self.strings("install_fail").format(name=arg, err=str(exc)[:300]),
                parse_mode="html",
            )

    @command("loadmod", required=OWNER, aliases=["lm"])
    async def loadmod_cmd(self, event) -> None:
        """.loadmod — загрузить модуль из .py файла (ответь на файл)."""
        reply = await event.message.get_reply_message()
        msg = reply if (reply and reply.file) else (event.message if event.message.file else None)

        if not msg or not msg.file:
            await event.message.edit(self.strings("no_file"), parse_mode="html")
            return

        await event.message.edit(self.strings("loading"), parse_mode="html")

        try:
            raw = await msg.download_media(bytes)
            text = raw.decode("utf-8")
        except Exception:
            await event.message.edit(self.strings("bad_file"), parse_mode="html")
            return

        loader = self._loader()
        if not loader:
            return

        # write to user modules dir and load
        user_dir = Path.home() / ".kitsune" / "modules"
        user_dir.mkdir(parents=True, exist_ok=True)

        filename = getattr(msg.file, "name", None) or "custom_module.py"
        if not filename.endswith(".py"):
            filename += ".py"

        path = user_dir / filename
        path.write_text(text, encoding="utf-8")

        try:
            mod = await loader.load_from_file(path)
            await event.message.edit(
                self.strings("installed").format(name=mod.name), parse_mode="html"
            )
        except Exception as exc:
            logger.exception("loadmod: failed")
            await event.message.edit(
                self.strings("install_fail").format(name=filename, err=str(exc)[:300]),
                parse_mode="html",
            )

    @command("unloadmod", required=OWNER)
    async def unloadmod_cmd(self, event) -> None:
        """.unloadmod <название> — выгрузить модуль."""
        name = self.get_args(event).strip()
        if not name:
            await event.message.edit(self.strings("no_args"), parse_mode="html")
            return

        loader = self._loader()
        if not loader:
            return

        ok = await loader.unload_module(name)
        if ok:
            user_mods = self._get_user_modules()
            user_mods.pop(name, None)
            user_mods.pop(name.lower(), None)
            await self._save_user_modules(user_mods)
            await event.message.edit(
                self.strings("unloaded").format(name=name), parse_mode="html"
            )
        else:
            await event.message.edit(
                self.strings("not_loaded").format(name=name), parse_mode="html"
            )

    @command("ml", required=OWNER)
    async def ml_cmd(self, event) -> None:
        """.ml <название> — показать файл/ссылку модуля."""
        name = self.get_args(event).strip()
        if not name:
            await event.message.edit(self.strings("no_args"), parse_mode="html")
            return

        loader = self._loader()
        mod = loader.get_module(name) if loader else None
        if not mod:
            await event.message.edit(
                self.strings("ml_not_found").format(name=name), parse_mode="html"
            )
            return

        url = getattr(mod, "_source_url", None)
        path = getattr(mod, "_source_path", None)

        if url:
            await event.message.edit(
                self.strings("ml_info").format(name=mod.name, url=url),
                parse_mode="html",
            )
            # also send file
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(url) as resp:
                        content = await resp.read()
                buf = io.BytesIO(content)
                buf.name = f"{mod.name}.py"
                buf.seek(0)
                await self.client.send_file(
                    event.message.peer_id, buf, reply_to=event.message.id
                )
            except Exception:
                pass
        elif path:
            try:
                buf = io.BytesIO(Path(path).read_bytes())
                buf.name = f"{mod.name}.py"
                buf.seek(0)
                await self.client.send_file(
                    event.message.peer_id, buf,
                    caption=self.strings("ml_file").format(name=mod.name),
                    parse_mode="html",
                    reply_to=event.message.id,
                )
                await event.message.delete()
            except Exception as exc:
                await event.message.edit(f"❌ {exc}", parse_mode="html")
        else:
            await event.message.edit(
                self.strings("ml_file").format(name=mod.name), parse_mode="html"
            )

    @command("clearmodules", required=OWNER)
    async def clearmodules_cmd(self, event) -> None:
        """.clearmodules — выгрузить все пользовательские модули."""
        loader = self._loader()
        if not loader:
            return

        user_mods = dict(self._get_user_modules())
        for name in list(user_mods.keys()):
            await loader.unload_module(name)

        await self._save_user_modules({})

        # also delete files from user module dir
        user_dir = Path.home() / ".kitsune" / "modules"
        if user_dir.exists():
            import shutil
            for f in user_dir.glob("*.py"):
                try:
                    f.unlink()
                except Exception:
                    pass

        await event.message.edit(self.strings("cleared"), parse_mode="html")

    @command("addrepo", required=OWNER)
    async def addrepo_cmd(self, event) -> None:
        """.addrepo <URL> — добавить репозиторий модулей."""
        url = self.get_args(event).strip().rstrip("/")
        if not url or not url.startswith("http"):
            await event.message.edit(self.strings("repo_invalid"), parse_mode="html")
            return

        repos = list(self.config["ADDITIONAL_REPOS"] or [])
        if url in repos:
            await event.message.edit(
                self.strings("repo_exists").format(url=url), parse_mode="html"
            )
            return

        repos.append(url)
        self.config["ADDITIONAL_REPOS"] = repos
        await self.db.set(_DB_OWNER, "additional_repos", repos)
        await event.message.edit(self.strings("repo_added").format(url=url), parse_mode="html")

    @command("delrepo", required=OWNER)
    async def delrepo_cmd(self, event) -> None:
        """.delrepo <URL> — удалить репозиторий."""
        url = self.get_args(event).strip().rstrip("/")
        if not url:
            await event.message.edit(self.strings("repo_invalid"), parse_mode="html")
            return

        repos = list(self.config["ADDITIONAL_REPOS"] or [])
        if url not in repos:
            await event.message.edit(
                self.strings("repo_not_found").format(url=url), parse_mode="html"
            )
            return

        repos.remove(url)
        self.config["ADDITIONAL_REPOS"] = repos
        await self.db.set(_DB_OWNER, "additional_repos", repos)
        await event.message.edit(self.strings("repo_removed").format(url=url), parse_mode="html")
