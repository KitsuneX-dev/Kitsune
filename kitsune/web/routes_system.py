
from __future__ import annotations

import logging
import os
import platform
import time
import typing
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

try:
    import aiohttp.web
except ImportError:
    aiohttp = None

from .dashboard_html import build_dashboard_html

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_EMPTY_SYSTEM_KEYS = (
    "cpu_pct", "ram_used_mb", "ram_total_mb", "ram_pct",
    "disk_used_gb", "disk_total_gb", "disk_pct",
)


class RoutesSystemMixin:

    async def _handle_static(self, request):
        filename = request.match_info.get("filename", "")
        if (not filename) or ("/" in filename) or ("\\" in filename) or (".." in filename):
            return aiohttp.web.Response(status=404, text="not found")
        path = (_STATIC_DIR / filename).resolve()
        try:
            path.relative_to(_STATIC_DIR)
        except ValueError:
            return aiohttp.web.Response(status=404, text="not found")
        if not path.is_file():
            return aiohttp.web.Response(status=404, text="not found")
        return aiohttp.web.FileResponse(path)

    async def _handle_root(self, request):
        from ..version import __version_str__
        me = self._client.tg_me
        html = build_dashboard_html(
            name=me.first_name if me else "—",
            uid=me.id if me else "—",
            username=f"@{me.username}" if me and getattr(me, "username", None) else "",
            version=__version_str__,
        )
        response = aiohttp.web.Response(text=html, content_type="text/html")
        from .auth import apply_security_headers
        apply_security_headers(response)
        return response

    def _process_cpu_percent(self) -> float:
        if psutil is None:
            return 0.0
        try:
            if getattr(self, "_proc", None) is None:
                self._proc = psutil.Process()
                self._proc.cpu_percent(interval=None)
            return float(self._proc.cpu_percent(interval=None))
        except Exception:
            logger.debug("status: не удалось получить cpu_percent процесса", exc_info=True)
            return 0.0

    @staticmethod
    def _disk_usage():
        if psutil is None:
            return None
        try:
            return psutil.disk_usage("/")
        except Exception:
            logger.debug("status: disk_usage('/') недоступен, пробуем cwd", exc_info=True)
            try:
                return psutil.disk_usage(os.getcwd())
            except Exception:
                logger.debug("status: disk_usage(cwd) тоже недоступен", exc_info=True)
                return None

    async def _handle_status(self, request):
        from ..version import __version_str__
        if psutil is None:
            system: dict[str, typing.Any] = {k: 0 for k in _EMPTY_SYSTEM_KEYS}
        else:
            mem = psutil.virtual_memory()
            disk = self._disk_usage()
            cpu = self._process_cpu_percent()
            system = {
                "cpu_pct":       round(cpu, 1),
                "ram_used_mb":   mem.used // 1024 // 1024,
                "ram_total_mb":  mem.total // 1024 // 1024,
                "ram_pct":       round(mem.percent, 1),
                "disk_used_gb":  round(disk.used / 1024 ** 3, 1) if disk else 0,
                "disk_total_gb": round(disk.total / 1024 ** 3, 1) if disk else 0,
                "disk_pct":      round(disk.percent, 1) if disk else 0,
            }
            try:
                system["system_ram_used_mb"] = system["ram_used_mb"]
                system["system_ram_total_mb"] = system["ram_total_mb"]
            except Exception:
                logger.debug("status: не удалось добавить system_ram_* поля", exc_info=True)
            try:
                if getattr(self, "_proc", None) is None:
                    self._proc = psutil.Process()
                system["process_ram_mb"] = round(
                    self._proc.memory_info().rss / 1024 / 1024, 1
                )
            except Exception:
                logger.debug("status: не удалось получить RSS процесса", exc_info=True)
            try:
                system["kernel"] = platform.release()
            except Exception:
                logger.debug("status: platform.release() не сработал", exc_info=True)

        loader = getattr(self._client, "_kitsune_loader", None)
        me = self._client.tg_me
        return self._json({
            "ok": True, "version": __version_str__, "timestamp": int(time.time()),
            "account": {
                "name": me.first_name if me else "—",
                "id": me.id if me else 0,
                "username": getattr(me, "username", "") or "",
            },
            "modules": len(loader.modules) if loader else 0,
            "system": system,
        })

    async def _handle_health(self, request):
        try:
            from ..modules.health import collect_health
            snapshot = await collect_health(self._client, self._db)
            status = 200 if snapshot.get("ok") else 503
            return self._json(snapshot, status=status)
        except Exception as exc:
            return self._json({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "timestamp": int(time.time()),
            }, status=500)

    async def _handle_modules(self, request):
        loader = getattr(self._client, "_kitsune_loader", None)
        if not loader:
            return self._json({"ok": False, "error": "loader not available"})
        modules = [{
            "name": mod.name,
            "description": getattr(mod, "description", ""),
            "author": getattr(mod, "author", ""),
            "version": getattr(mod, "version", "1.0"),
            "icon": getattr(mod, "icon", "📦"),
            "category": getattr(mod, "category", "other"),
            "is_builtin": getattr(mod, "_is_builtin", False),
            "has_config": mod.config is not None and len(list(mod.config.keys())) > 0,
        } for mod in loader.modules.values()]
        return self._json({"ok": True, "modules": modules})

    async def _handle_module_action(self, request):
        loader = getattr(self._client, "_kitsune_loader", None)
        if not loader:
            return self._json({"ok": False, "error": "loader not available"})
        name = request.match_info.get("name", "")
        try:
            action = request.query.get("action", "unload")
            if action == "unload":
                result = await loader.unload_module(name)
                return self._json({"ok": result, "action": "unloaded"})
            elif action == "reload":
                mod = await loader.reload_module(name)
                return self._json({"ok": True, "action": "reloaded", "module": mod.name})
            return self._json({"ok": False, "error": "unknown action"})
        except Exception as exc:
            logger.debug("module action failed", exc_info=True)
            return self._json({"ok": False, "error": str(exc)})

    async def _handle_module_load(self, request):
        loader = getattr(self._client, "_kitsune_loader", None)
        if not loader:
            return self._json({"ok": False, "error": "loader not available"})
        try:
            body = await request.json()
            url = body.get("url", "")
            if not url:
                return self._json({"ok": False, "error": "url required"})
            mod = await loader.load_from_url(url)
            return self._json({"ok": True, "module": mod.name, "version": mod.version})
        except Exception as exc:
            logger.debug("module load failed", exc_info=True)
            return self._json({"ok": False, "error": str(exc)})

    async def _handle_module_config(self, request):
        loader = getattr(self._client, "_kitsune_loader", None)
        if not loader:
            return self._json({"ok": False, "error": "loader not available"})
        name = request.match_info.get("name", "")
        mod = loader.get_module(name)
        if not mod or not mod.config:
            return self._json({"ok": False, "error": "module or config not found"})
        if request.method == "GET":
            return self._json({"ok": True, "config": {
                k: {
                    "value": mod.config[k],
                    "default": mod.config.get_default(k),
                    "doc": mod.config.get_doc(k),
                }
                for k in mod.config.keys()
            }})
        try:
            body = await request.json()
            for k, v in body.items():
                if k in mod.config:
                    mod.config[k] = v
            for k in mod.config.keys():
                await self._db.set(f"kitsune.config.{mod.name.lower()}", k, mod.config[k])
            return self._json({"ok": True})
        except Exception as exc:
            logger.exception("web: не удалось сохранить конфиг модуля %s", name)
            return self._json({"ok": False, "error": str(exc)})

    async def _handle_settings(self, request):
        db = self._db
        if request.method == "GET":
            return self._json({"ok": True, "settings": {
                "prefix": db.get("kitsune.core", "prefix", "."),
                "lang": db.get("kitsune.core", "lang", "ru"),
                "autodel": db.get("kitsune.core", "autodel", 0),
            }})
        try:
            body = await request.json()
            for k, v in body.items():
                await db.set("kitsune.core", k, v)
            from ..main import set_config_key
            for k, v in body.items():
                set_config_key(k, v)
            return self._json({"ok": True})
        except Exception as exc:
            logger.exception("web: не удалось сохранить основные настройки")
            return self._json({"ok": False, "error": str(exc)})

    async def _handle_logs(self, request):


        try:
            from ..log import LOG_FILE as log_file
        except Exception:
            from ..paths import data_dir as _kdd
            log_file = _kdd() / "logs" / "kitsune.log"
        if not log_file.exists():
            return self._json({"ok": True, "logs": []})
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            limit = int(request.query.get("limit", 200))
            return self._json({"ok": True, "logs": lines[-limit:] if len(lines) > limit else lines})
        except Exception:
            logger.debug("web: не удалось прочитать файл логов", exc_info=True)
            return self._json({"ok": True, "logs": []})
