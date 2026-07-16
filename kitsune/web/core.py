from __future__ import annotations
import asyncio
import json
import logging
import typing
from pathlib import Path
import os

_STATIC_DIR = Path(__file__).resolve().parent / "static"

logger = logging.getLogger(__name__)

try:
    import aiohttp
    import aiohttp.web
    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False
class WebCore:
    def __init__(self, client: typing.Any, db: typing.Any) -> None:
        self._client = client
        self._db = db
        self._runner: typing.Any = None
        self._site: typing.Any = None
    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        if not WEB_AVAILABLE:
            logger.warning("WebCore: aiohttp not available, web UI disabled")
            return
        app = aiohttp.web.Application()
        app.router.add_get("/",                              self._handle_root)
        app.router.add_get("/api/status",                   self._handle_status)
        app.router.add_get("/api/modules",                  self._handle_modules)
        app.router.add_post("/api/modules/action/{name}",   self._handle_module_action)
        app.router.add_post("/api/modules/load",            self._handle_module_load)
        app.router.add_route("GET",  "/api/modules/config/{name}", self._handle_module_config)
        app.router.add_route("POST", "/api/modules/config/{name}", self._handle_module_config)
        app.router.add_get("/api/settings",                 self._handle_settings)
        app.router.add_post("/api/settings",                self._handle_settings)
        app.router.add_get("/api/logs",                     self._handle_logs)
        app.router.add_get("/health",                        self._handle_health)
        app.router.add_get("/static/{filename}",             self._handle_static)
        self._runner = aiohttp.web.AppRunner(app)
        await self._runner.setup()
        self._site = aiohttp.web.TCPSite(self._runner, host, port)
        try:
            await self._site.start()
            logger.info("WebCore: listening on http://%s:%d", host, port)
        except OSError as exc:
            logger.error("WebCore: could not bind to %s:%d — %s", host, port, exc)
    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
    def _json(self, data, status=200):
        return aiohttp.web.Response(
            text=json.dumps(data, ensure_ascii=False),
            content_type="application/json", status=status,
            headers={"Access-Control-Allow-Origin": "*"},
        )
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
        html = _build_html(
            name=me.first_name if me else "—",
            uid=me.id if me else "—",
            username=f"@{me.username}" if me and getattr(me, "username", None) else "",
            version=__version_str__,
        )
        return aiohttp.web.Response(text=html, content_type="text/html")
    async def _handle_status(self, request):
        import time
        from ..version import __version_str__
        try:
            import psutil
            mem  = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            try: cpu = psutil.cpu_percent(interval=0.2)
            except Exception: cpu = 0.0
            system = {
                "cpu_pct":       round(cpu, 1),
                "ram_used_mb":   mem.used // 1024 // 1024,
                "ram_total_mb":  mem.total // 1024 // 1024,
                "ram_pct":       round(mem.percent, 1),
                "disk_used_gb":  round(disk.used / 1024 ** 3, 1),
                "disk_total_gb": round(disk.total / 1024 ** 3, 1),
                "disk_pct":      round(disk.percent, 1),
            }
        except ImportError:
            system = {k: 0 for k in ("cpu_pct","ram_used_mb","ram_total_mb","ram_pct","disk_used_gb","disk_total_gb","disk_pct")}
        loader = getattr(self._client, "_kitsune_loader", None)
        me = self._client.tg_me
        return self._json({
            "ok": True, "version": __version_str__, "timestamp": int(time.time()),
            "account": {"name": me.first_name if me else "—", "id": me.id if me else 0, "username": getattr(me, "username", "") or ""},
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
            import time as _time
            return self._json({
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "timestamp": int(_time.time()),
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
                k: {"value": mod.config[k], "default": mod.config.get_default(k), "doc": mod.config.get_doc(k)}
                for k in mod.config.keys()
            }})
        try:
            body = await request.json()
            for k, v in body.items():
                if k in mod.config: mod.config[k] = v
            for k in mod.config.keys():
                self._db.set(f"kitsune.config.{mod.name.lower()}", k, mod.config[k])
            return self._json({"ok": True})
        except Exception as exc:
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
            for k, v in body.items(): db.set("kitsune.core", k, v)
            from ..main import set_config_key
            for k, v in body.items(): set_config_key(k, v)
            return self._json({"ok": True})
        except Exception as exc:
            return self._json({"ok": False, "error": str(exc)})
    async def _handle_logs(self, request):
        log_file = Path.home() / ".kitsune" / "kitsune.log"
        if not log_file.exists():
            return self._json({"ok": True, "logs": []})
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            limit = int(request.query.get("limit", 200))
            return self._json({"ok": True, "logs": lines[-limit:] if len(lines) > limit else lines})
        except Exception:
            return self._json({"ok": True, "logs": []})
def _build_html(*, name, uid, username, version):
    _tpl = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Kitsune __KVERSION__</title>
<link rel="icon" type="image/png" href="/static/favicon-32.png">
<link rel="apple-touch-icon" href="/static/favicon-180.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700&family=DM+Sans:opsz,wght@9..40,300;9..40,500;9..40,700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/theme.css">
<style>
.app {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 clamp(10px, 3.5vw, 16px) 40px;
  padding-left: max(clamp(10px, 3.5vw, 16px), env(safe-area-inset-left));
  padding-right: max(clamp(10px, 3.5vw, 16px), env(safe-area-inset-right));
  padding-bottom: max(40px, env(safe-area-inset-bottom));
}

/* Header */
.hdr { padding: 20px 0 18px; display: flex; align-items: center; gap: 14px; border-bottom: 1px solid var(--bd); position: relative; flex-wrap: wrap; }
@media (max-width: 420px) {
  .hdr { gap: 10px; padding: 16px 0 14px; }
  .brand-mark.hdr-logo { width: 40px !important; height: 40px !important; }
}
@media (max-width: 340px) {
  .hdr-info { flex-basis: calc(100% - 52px); }
  .online { margin-left: 52px; }
}
.hdr::after {
  content: '';
  position: absolute;
  left: 0; right: 40%; bottom: -1px;
  height: 1px;
  background: linear-gradient(90deg, var(--violet), var(--fox), transparent);
  opacity: .55;
}
.brand-mark.hdr-logo { width: 46px; height: 46px; flex-shrink: 0; animation: logo-breathe 5s ease-in-out infinite; }
@keyframes logo-breathe {
  0%, 100% { box-shadow: 0 0 0 1px var(--bd2), 0 0 14px var(--violet-glow); }
  50%      { box-shadow: 0 0 0 1px var(--bd3), 0 0 26px var(--violet-glow), 0 0 14px var(--fox-glow); }
}
.hdr-info { flex: 1; min-width: 0; }
.hdr-title {
  font-family: var(--mono); font-size: clamp(.8rem, 3.4vw, .92rem); font-weight: 700;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  background: linear-gradient(100deg, var(--tx) 30%, var(--violet2) 70%, var(--fox2) 100%);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.hdr-sub { font-size: .68rem; color: var(--mu); margin-top: 3px; font-family: var(--mono); }
.online {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--green-dim); border: 1px solid rgba(56, 255, 176, 0.25);
  border-radius: 20px; padding: 5px 12px;
  font-size: .65rem; font-weight: 700; color: var(--green);
  font-family: var(--mono); letter-spacing: .05em;
}
.dot { width: 5px; height: 5px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px var(--green); animation: blink 2s infinite; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }

/* Nav — адаптивная сетка: на узких экранах кнопки делят ширину поровну,
   ничего не обрезается */
.nav { display: flex; gap: 4px; padding: 12px 0 0; overflow-x: auto; scrollbar-width: none; }
.nav::-webkit-scrollbar { display: none; }
.nb {
  flex-shrink: 0; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  padding: 9px 16px; border-radius: 9px; border: 1px solid var(--bd);
  background: var(--glass2);
  font-family: var(--body); font-size: .78rem; font-weight: 500;
  color: var(--mu2); cursor: pointer;
  transition: var(--ease); white-space: nowrap;
}
@media (max-width: 560px) {
  .nav { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; overflow: visible; }
  .nb { padding: 9px 4px; font-size: .7rem; gap: 4px; }
  .nb .icon { width: 13px !important; height: 13px !important; }
}
@media (max-width: 340px) {
  .nav { grid-template-columns: repeat(2, 1fr); }
}
.nb:hover { color: var(--tx); background: var(--s2); }
.nb.on { color: var(--violet2); background: rgba(184, 44, 240, 0.12); border-color: rgba(216, 130, 255, 0.25); box-shadow: 0 0 14px rgba(184, 44, 240, 0.18), inset 0 0 12px rgba(184, 44, 240, 0.06); }
.nb .icon { width: 15px; height: 15px; }

/* Panel */
.panel { display: none; padding-top: 20px; animation: panel-in .2s ease both; }
.panel.on { display: block; }
@keyframes panel-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

/* Card */
.card {
  background: var(--glass);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid var(--bd2);
  border-radius: var(--r);
  padding: clamp(14px, 3.5vw, 18px);
  margin-bottom: 12px;
  transition: border-color var(--ease), box-shadow var(--ease);
  position: relative;
  overflow: hidden;
  box-shadow: 0 0 0 1px rgba(184, 44, 240, 0.05), 0 6px 24px rgba(0, 0, 0, .30), 0 0 18px rgba(184, 44, 240, 0.07);
}
.card::before {
  content: '';
  position: absolute;
  top: 0; left: 12px; right: 60%;
  height: 1px;
  background: linear-gradient(90deg, rgba(216, 130, 255, 0.45), transparent);
  pointer-events: none;
}
.card:hover { border-color: var(--bd2); box-shadow: 0 8px 34px rgba(0, 0, 0, .35), 0 0 24px rgba(184, 44, 240, 0.08); }
.ctit { font-family: var(--mono); font-size: .62rem; font-weight: 700; color: var(--mu2); letter-spacing: .1em; text-transform: uppercase; margin-bottom: 14px; }

/* Stat grid */
.sg { display: grid; grid-template-columns: 1fr 1fr; gap: clamp(8px, 2vw, 10px); margin-bottom: 12px; }
@media (min-width: 640px) { .sg { grid-template-columns: repeat(4, 1fr); } }
.sb {
  background: var(--glass2);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--bd2);
  border-radius: var(--r2);
  padding: clamp(11px, 3vw, 14px) clamp(12px, 3.2vw, 16px);
  position: relative;
  overflow: hidden;
  transition: border-color var(--ease), transform var(--ease), box-shadow var(--ease);
  box-shadow: 0 4px 16px rgba(0, 0, 0, .28), 0 0 14px rgba(184, 44, 240, 0.07);
}
.sb::after {
  content: '';
  position: absolute;
  right: -22px; top: -22px;
  width: 62px; height: 62px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(184, 44, 240, 0.16), transparent 70%);
  pointer-events: none;
}
.sb:nth-child(odd)::after { background: radial-gradient(circle, rgba(255, 90, 43, 0.14), transparent 70%); }
.sb:hover { border-color: var(--bd2); transform: translateY(-2px); box-shadow: 0 10px 26px rgba(0, 0, 0, .3), 0 0 18px rgba(184, 44, 240, 0.10); }
.sl { font-size: .62rem; color: var(--mu2); font-family: var(--mono); letter-spacing: .08em; text-transform: uppercase; margin-bottom: 6px; }
.sv { font-family: var(--mono); font-size: clamp(.95rem, 3vw, 1.1rem); font-weight: 700; color: var(--tx); }
.sv.fox { color: var(--fox2); text-shadow: 0 0 16px var(--fox-glow); } .sv.violet { color: var(--violet2); text-shadow: 0 0 16px var(--violet-glow); }

/* Row */
.rows { display: flex; flex-direction: column; }
.row { display: flex; justify-content: space-between; align-items: center; padding: 9px 0; border-bottom: 1px solid rgba(238, 233, 251, 0.05); }
.row:last-child { border: none; }
.rk { font-size: .78rem; color: var(--mu2); font-weight: 300; }
.rv { font-size: .78rem; color: var(--tx); font-weight: 500; font-family: var(--mono); max-width: 60%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: right; }
.rv.fox { color: var(--fox2); }

/* Bars */
.bar { margin-top: 10px; }
.bh { display: flex; justify-content: space-between; margin-bottom: 5px; }
.bn { font-size: .7rem; color: var(--mu2); } .bvv { font-size: .7rem; color: var(--mu); font-family: var(--mono); }
.bt { height: 4px; border-radius: 2px; background: rgba(238, 233, 251, 0.07); overflow: hidden; }
.bf { height: 100%; border-radius: 2px; background: linear-gradient(90deg, var(--violet), var(--fox)); transition: width .8s cubic-bezier(.4, 0, .2, 1); }
.bf.mid { background: linear-gradient(90deg, #ffc857, var(--fox2)); }
.bf.hi { background: linear-gradient(90deg, var(--red), var(--fox)); }

/* Modules */
.mc { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; gap: 10px; flex-wrap: wrap; }
.mf { display: flex; gap: 6px; flex-wrap: wrap; }
.fi { padding: 6px 12px; border-radius: 20px; border: 1px solid var(--bd); background: var(--glass2); color: var(--mu2); cursor: pointer; font-size: .72rem; font-family: var(--body); transition: var(--ease); }
.fi:hover { border-color: var(--bd2); color: var(--tx); }
.fi.on { background: rgba(184, 44, 240, 0.14); border-color: rgba(216, 130, 255, 0.3); color: var(--violet2); }
.mb { font-size: .68rem; color: var(--mu); font-family: var(--mono); padding: 3px 8px; background: var(--s2); border-radius: 6px; }
.mg { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(250px, 100%), 1fr)); gap: 12px; }
@media (max-width: 580px) { .mg { grid-template-columns: 1fr; } }
.mc2 {
  background: var(--glass);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--bd2);
  border-radius: var(--r);
  padding: clamp(13px, 3vw, 16px);
  box-shadow: 0 4px 18px rgba(0, 0, 0, .28), 0 0 14px rgba(184, 44, 240, 0.06);
  display: flex; flex-direction: column; gap: 10px;
  transition: border-color var(--ease), transform var(--ease), box-shadow var(--ease);
  animation: rv-up .45s cubic-bezier(.22, .8, .3, 1) both;
}
.mc2:hover { border-color: rgba(216, 130, 255, 0.3); transform: translateY(-3px); box-shadow: 0 12px 30px rgba(0, 0, 0, .35), 0 0 22px rgba(184, 44, 240, 0.12); }
.mct { display: flex; align-items: center; gap: 10px; }
.mi {
  width: 38px; height: 38px; flex-shrink: 0; border-radius: 10px;
  background: linear-gradient(135deg, rgba(184, 44, 240, 0.2), rgba(255, 90, 43, 0.08));
  border: 1px solid rgba(216, 130, 255, 0.2);
  display: flex; align-items: center; justify-content: center; font-size: 1.05rem;
}
.mi .icon { width: 18px; height: 18px; color: var(--violet2); }
.mn { font-size: .85rem; font-weight: 700; color: var(--tx); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mm { font-size: .66rem; color: var(--mu); margin-top: 2px; font-family: var(--mono); }
.md { font-size: .73rem; color: var(--mu2); line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.mf2 { display: flex; gap: 6px; justify-content: flex-end; padding-top: 8px; border-top: 1px solid var(--bd); }
.tsys {
  display: inline-flex; padding: 2px 7px; border-radius: 5px;
  font-size: .6rem; font-weight: 700; font-family: var(--mono);
  background: rgba(74, 168, 255, 0.14); color: var(--blue);
  border: 1px solid rgba(74, 168, 255, 0.25); margin-left: 6px;
}

/* Settings */
.sr { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px 0; border-bottom: 1px solid rgba(238, 233, 251, 0.07); flex-wrap: wrap; }
.sr > div:first-child { flex: 1 1 180px; min-width: 0; }
.sr:last-child { border: none; }
@media (max-width: 420px) {
  .sr .inp, .sr .sel { width: 100%; flex: 1 1 100%; }
}
.slb { font-size: .8rem; color: var(--tx); }
.ss { font-size: .68rem; color: var(--mu); margin-top: 2px; }
.inp {
  background: var(--s2); border: 1px solid var(--bd2); border-radius: 8px;
  padding: 8px 12px; color: var(--tx); font-size: .8rem; font-family: var(--mono);
  outline: none; transition: border-color var(--ease); width: 100px;
}
.inp:focus { border-color: var(--violet); }
.sel {
  background: var(--s2); border: 1px solid var(--bd2); border-radius: 8px;
  padding: 8px 12px; color: var(--tx); font-size: .8rem; font-family: var(--body);
  outline: none; cursor: pointer; width: 140px;
}

/* Logs */
.lw {
  background: var(--glass); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--bd2); border-radius: var(--r2);
  padding: 14px; font-family: var(--mono); font-size: .68rem;
  max-height: min(500px, 62vh); overflow-y: auto; line-height: 1.65;
  overflow-wrap: anywhere;
  box-shadow: 0 4px 18px rgba(0, 0, 0, .28), 0 0 14px rgba(184, 44, 240, 0.06);
}
.le { color: var(--red); } .lwarn { color: var(--yellow); } .li { color: var(--mu2); } .ld { color: var(--mu); }

/* Modal */
.ov {
  position: fixed; inset: 0; background: rgba(3, 1, 8, .78);
  display: none; align-items: center; justify-content: center; z-index: 100;
  padding: 16px; backdrop-filter: blur(4px);
}
.ov.on { display: flex; }
.modal {
  background: var(--glass); backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--bd3); border-radius: 18px;
  padding: clamp(18px, 4.5vw, 24px); width: 100%; max-width: 400px;
  max-height: calc(100dvh - 32px); overflow-y: auto;
  box-shadow: 0 24px 60px rgba(0, 0, 0, .6), 0 0 40px var(--violet-glow);
  animation: modal-in .22s cubic-bezier(.22, .8, .3, 1) both;
}
@keyframes modal-in { from { opacity: 0; transform: translateY(10px) scale(.97); } to { opacity: 1; transform: none; } }
.mtit { display: flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: .9rem; font-weight: 700; margin-bottom: 16px; }
.mi2 {
  width: 100%; background: var(--s2); border: 1px solid var(--bd2); border-radius: 10px;
  padding: 11px 14px; color: var(--tx); font-size: .85rem; font-family: var(--mono);
  outline: none; margin-bottom: 14px; transition: border-color var(--ease);
}
.mi2:focus { border-color: var(--violet); }
.mbs { display: flex; gap: 10px; justify-content: flex-end; }
.mok {
  padding: 10px 18px; border-radius: 10px; border: none;
  font-size: .82rem; font-weight: 700; cursor: pointer;
  background: linear-gradient(135deg, var(--violet), var(--fox)); color: #fff;
  font-family: var(--body); transition: var(--ease);
}
.mok:hover { filter: brightness(1.1); }
.mno {
  padding: 10px 18px; border-radius: 10px; background: var(--s2); color: var(--mu2);
  border: 1px solid var(--bd); font-size: .82rem; cursor: pointer;
  font-family: var(--body); transition: var(--ease);
}
.mno:hover { border-color: var(--bd2); color: var(--tx); }

/* Pager */
.pg { display: flex; justify-content: center; gap: 6px; margin-top: 16px; flex-wrap: wrap; }
.pgb {
  padding: 7px 12px; border-radius: 8px; border: 1px solid var(--bd);
  background: transparent; color: var(--mu2); cursor: pointer;
  font-size: .74rem; transition: var(--ease); font-family: var(--mono);
}
.pgb:hover { border-color: var(--bd2); color: var(--tx); }
.pgb.on { background: rgba(184, 44, 240, 0.14); border-color: rgba(216, 130, 255, 0.3); color: var(--violet2); }

/* Footer */
.footer {
  display: flex; justify-content: space-between; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 14px 0 0; border-top: 1px solid var(--bd); margin-top: 6px;
  font-size: .65rem; color: var(--mu); font-family: var(--mono);
}

/* Мобильная шапка списка модулей */
@media (max-width: 480px) {
  .mc { flex-direction: column; align-items: stretch; }
  .mc .btn.pri { justify-content: center; }
}
</style>
</head>
<body>
<div class="bg-scene" aria-hidden="true"></div>
<div class="bg-grid" aria-hidden="true"></div>
<canvas id="fx" aria-hidden="true"></canvas>

<div class="app">
<header class="hdr rv-up">
  <img class="brand-mark hdr-logo" src="/static/kitsune_logo.png" alt="Kitsune">
  <div class="hdr-info">
    <div class="hdr-title">kitsune_userbot</div>
    <div class="hdr-sub">v__KVERSION__ &nbsp;·&nbsp; @__KUSERNAME__</div>
  </div>
  <div class="online"><div class="dot"></div>online</div>
</header>
<nav class="nav rv-up rv-d1">
  <button class="nb on" onclick="go('dash',this)"><svg class="icon"><use href="#icon-grid"/></svg> Обзор</button>
  <button class="nb" onclick="go('mods',this)"><svg class="icon"><use href="#icon-box"/></svg> Модули</button>
  <button class="nb" onclick="go('sets',this)"><svg class="icon"><use href="#icon-sliders"/></svg> Настройки</button>
  <button class="nb" onclick="go('logs',this)"><svg class="icon"><use href="#icon-list"/></svg> Логи</button>
</nav>
<!-- DASH -->
<div class="panel on" id="p-dash">
  <div class="sg rv-up rv-d2">
    <div class="sb"><div class="sl">модули</div><div class="sv fox" id="s-mods">—</div></div>
    <div class="sb"><div class="sl">CPU</div><div class="sv" id="s-cpu">—</div></div>
    <div class="sb"><div class="sl">RAM</div><div class="sv" id="s-ram">—</div></div>
    <div class="sb"><div class="sl">DISK</div><div class="sv" id="s-disk">—</div></div>
  </div>
  <div class="card rv-up rv-d3">
    <div class="ctit">Аккаунт</div>
    <div class="rows">
      <div class="row"><span class="rk">Имя</span><span class="rv fox">__KNAME__</span></div>
      <div class="row"><span class="rk">Username</span><span class="rv">@__KUSERNAME__</span></div>
      <div class="row"><span class="rk">ID</span><span class="rv">__KUID__</span></div>
      <div class="row"><span class="rk">Разработчик</span><span class="rv">Yushi · @Mikasu32</span></div>
    </div>
  </div>
  <div class="card rv-up rv-d4">
    <div class="ctit">Ресурсы системы</div>
    <div id="bars"><div class="ld2"><span class="sp"></span>загрузка...</div></div>
  </div>
  <div class="footer"><span id="ts">обновление...</span><span>kitsune v__KVERSION__</span></div>
</div>

<!-- MODULES -->
<div class="panel" id="p-mods">
  <div class="mc">
    <div class="mf">
      <button class="fi on" onclick="filt('all',this)">Все <span class="mb" id="mc-a">0</span></button>
      <button class="fi" onclick="filt('sys',this)">Системные <span class="mb" id="mc-s">0</span></button>
      <button class="fi" onclick="filt('usr',this)">Пользовательские <span class="mb" id="mc-u">0</span></button>
    </div>
    <button class="btn pri" onclick="showMod()"><svg class="icon"><use href="#icon-plus"/></svg> Загрузить</button>
  </div>
  <div class="mg" id="mg"><div class="ld2"><span class="sp"></span>загрузка...</div></div>
  <div class="pg" id="pg"></div>
</div>

<!-- SETTINGS -->
<div class="panel" id="p-sets">
  <div class="card">
    <div class="ctit">Основные настройки</div>
    <div class="sr">
      <div><div class="slb">Префикс команд</div><div class="ss">Символ перед командами бота</div></div>
      <input type="text" class="inp" id="pfx" value="." onchange="sv('prefix',this.value)" maxlength="3">
    </div>
    <div class="sr">
      <div><div class="slb">Язык</div><div class="ss">Язык ответов</div></div>
      <select class="sel" id="lng" onchange="sv('lang',this.value)">
        <option value="ru">Русский</option>
        <option value="en">English</option>
      </select>
    </div>
    <div class="sr">
      <div><div class="slb">Автоудаление (сек)</div><div class="ss">0 = выключено</div></div>
      <input type="number" class="inp" id="adel" value="0" min="0" onchange="sv('autodel',this.value)">
    </div>
  </div>
</div>

<!-- LOGS -->
<div class="panel" id="p-logs">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
    <div class="ctit" style="margin:0">Системные логи</div>
    <button class="btn sm" onclick="loadLogs()"><svg class="icon"><use href="#icon-refresh"/></svg> Обновить</button>
  </div>
  <div class="lw" id="lw"><div class="ld2"><span class="sp"></span>загрузка...</div></div>
</div>

</div>

<div class="toast" id="toast"><span class="tdot"></span><span id="tmsg"></span></div>

<div class="ov" id="ov">
  <div class="modal">
    <div class="mtit"><svg class="icon"><use href="#icon-box"/></svg> Загрузить модуль</div>
    <input type="text" class="mi2" id="murl" placeholder="URL модуля (.py) или название">
    <div class="mbs">
      <button class="mno" onclick="hideMod()">Отмена</button>
      <button class="mok" onclick="doLoad()">Загрузить</button>
    </div>
  </div>
</div>

<!-- inline icon sprite -->
<svg aria-hidden="true" style="position:absolute;width:0;height:0;overflow:hidden">
  <symbol id="icon-grid" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1.2"/><rect x="14" y="3" width="7" height="7" rx="1.2"/><rect x="3" y="14" width="7" height="7" rx="1.2"/><rect x="14" y="14" width="7" height="7" rx="1.2"/></symbol>
  <symbol id="icon-box" viewBox="0 0 24 24"><path d="M21 8 12 3 3 8v8l9 5 9-5V8Z"/><path d="M3 8l9 5 9-5"/><line x1="12" y1="13" x2="12" y2="21"/></symbol>
  <symbol id="icon-sliders" viewBox="0 0 24 24"><line x1="5" y1="21" x2="5" y2="12"/><line x1="5" y1="8" x2="5" y2="3"/><line x1="12" y1="21" x2="12" y2="14"/><line x1="12" y1="10" x2="12" y2="3"/><line x1="19" y1="21" x2="19" y2="16"/><line x1="19" y1="12" x2="19" y2="3"/><circle cx="5" cy="10" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="14" r="2"/></symbol>
  <symbol id="icon-list" viewBox="0 0 24 24"><line x1="9" y1="6" x2="20" y2="6"/><line x1="9" y1="12" x2="20" y2="12"/><line x1="9" y1="18" x2="20" y2="18"/><circle cx="4.5" cy="6" r="1" fill="currentColor" stroke="none"/><circle cx="4.5" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="4.5" cy="18" r="1" fill="currentColor" stroke="none"/></symbol>
  <symbol id="icon-plus" viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></symbol>
  <symbol id="icon-refresh" viewBox="0 0 24 24"><path d="M4 4v6h6"/><path d="M20 20v-6h-6"/><path d="M5 13a7 7 0 0 1 12-4.6L20 10"/><path d="M19 11a7 7 0 0 1-12 4.6L4 14"/></symbol>
  <symbol id="icon-x" viewBox="0 0 24 24"><line x1="5" y1="5" x2="19" y2="19"/><line x1="19" y1="5" x2="5" y2="19"/></symbol>
  <symbol id="icon-file-text" viewBox="0 0 24 24"><path d="M6 3h9l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><line x1="8" y1="12" x2="15" y2="12"/><line x1="8" y1="16" x2="15" y2="16"/></symbol>
  <symbol id="icon-alert" viewBox="0 0 24 24"><path d="M12 3 2 20h20L12 3Z"/><line x1="12" y1="10" x2="12" y2="14"/><circle cx="12" cy="17" r=".6" fill="currentColor" stroke="none"/></symbol>
</svg>

<script src="/static/fx.js" defer></script>

<script>
let _tt,_mods=[],_pg=1,_ppg=6,_filt='all',_ml=false,_sl=false;
const $=id=>document.getElementById(id);
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

function toast(m,ok=true){
  const t=$('toast');$('tmsg').textContent=m;
  t.classList.toggle('err', !ok);
  t.classList.add('on');clearTimeout(_tt);_tt=setTimeout(()=>t.classList.remove('on'),3000);
}

function go(n,btn){
  document.querySelectorAll('.nb').forEach(b=>b.classList.remove('on'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('on'));
  btn.classList.add('on');$('p-'+n).classList.add('on');
  if(n==='mods'&&!_ml)loadMods();
  if(n==='sets'&&!_sl)loadSets();
  if(n==='logs')loadLogs();
}

// Status
async function fetchSt(){
  try{
    const d=await (await fetch('/api/status')).json();if(!d.ok)return;
    const s=d.system;
    $('s-mods').textContent=d.modules;
    $('s-cpu').textContent=s.cpu_pct+'%';
    $('s-ram').textContent=s.ram_used_mb+' MB';
    $('s-disk').textContent=s.disk_used_gb+' GB';
    $('bars').innerHTML=['CPU','RAM','Disk'].map((nm,i)=>{
      const [p,vl]=[
        [s.cpu_pct,s.cpu_pct+'%'],
        [s.ram_pct,s.ram_used_mb+'/'+s.ram_total_mb+' MB'],
        [s.disk_pct,s.disk_used_gb+'/'+s.disk_total_gb+' GB']
      ][i];
      const c=p>=85?'hi':p>=60?'mid':'';
      return `<div class="bar"><div class="bh"><span class="bn">${nm}</span><span class="bvv">${vl}</span></div><div class="bt"><div class="bf ${c}" style="width:${p}%"></div></div></div>`;
    }).join('');
    const n=new Date();$('ts').textContent='обновлено '+n.toLocaleTimeString('ru',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  }catch(e){}
}
fetchSt();setInterval(fetchSt,5000);

// Modules
async function loadMods(){
  $('mg').innerHTML='<div class="ld2"><span class="sp"></span>загрузка...</div>';
  try{
    const d=await(await fetch('/api/modules')).json();_ml=true;
    if(!d.ok||!d.modules){$('mg').innerHTML='<div class="empty"><svg class="icon"><use href="#icon-box"/></svg><div>Нет модулей</div></div>';return;}
    _mods=d.modules;
    $('mc-a').textContent=_mods.length;
    $('mc-s').textContent=_mods.filter(m=>m.is_builtin).length;
    $('mc-u').textContent=_mods.filter(m=>!m.is_builtin).length;
    render();
  }catch(e){$('mg').innerHTML='<div class="empty"><svg class="icon"><use href="#icon-alert"/></svg><div>Ошибка загрузки</div></div>';}
}

function filt(t,btn){document.querySelectorAll('.fi').forEach(b=>b.classList.remove('on'));btn.classList.add('on');_filt=t;_pg=1;render();}

function render(){
  const mob=window.innerWidth<=560;_ppg=mob?4:6;
  let list=_mods;
  if(_filt==='sys')list=_mods.filter(m=>m.is_builtin);
  else if(_filt==='usr')list=_mods.filter(m=>!m.is_builtin);
  const tot=Math.ceil(list.length/_ppg);
  const page=list.slice((_pg-1)*_ppg,_pg*_ppg);
  if(!page.length){$('mg').innerHTML='<div class="empty"><svg class="icon"><use href="#icon-box"/></svg><div>Нет модулей</div></div>';$('pg').innerHTML='';return;}
  $('mg').innerHTML=page.map(m=>`
    <div class="mc2">
      <div class="mct">
        <div class="mi"><svg class="icon"><use href="#icon-file-text"/></svg></div>
        <div style="flex:1;min-width:0">
          <div class="mn">${esc(m.name)}${m.is_builtin?'<span class="tsys">sys</span>':''}</div>
          <div class="mm">v${m.version}${m.author?' · '+esc(m.author):''}</div>
        </div>
      </div>
      ${m.description?'<div class="md">'+esc(m.description)+'</div>':''}
      ${!m.is_builtin?`<div class="mf2">
        <button class="btn sm" onclick="rl('${m.name}')"><svg class="icon"><use href="#icon-refresh"/></svg></button>
        <button class="btn sm dng" onclick="ul('${m.name}')"><svg class="icon"><use href="#icon-x"/></svg></button>
      </div>`:''}
    </div>
  `).join('');
  $('pg').innerHTML=tot>1?Array.from({length:tot},(_,i)=>
    `<button class="pgb${i+1===_pg?' on':''}" onclick="gp(${i+1})">${i+1}</button>`
  ).join(''):'';
}

function gp(p){_pg=p;render();}

async function ul(name){
  if(!confirm('Выгрузить '+name+'?'))return;
  const d=await(await fetch('/api/modules/action/'+name+'?action=unload',{method:'POST'})).json();
  d.ok?(toast('Выгружен'),_ml=false,loadMods()):toast('Ошибка: '+d.error,false);
}

async function rl(name){
  const d=await(await fetch('/api/modules/action/'+name+'?action=reload',{method:'POST'})).json();
  d.ok?(toast('Перезагружен'),_ml=false,loadMods()):toast('Ошибка: '+d.error,false);
}

function showMod(){$('ov').classList.add('on');$('murl').focus();}
function hideMod(){$('ov').classList.remove('on');$('murl').value='';}

async function doLoad(){
  const url=$('murl').value.trim();if(!url)return;
  const btn=document.querySelector('.mok');btn.textContent='...';btn.disabled=true;
  try{
    const d=await(await fetch('/api/modules/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})})).json();
    d.ok?(toast('Загружен: '+d.module),hideMod(),_ml=false,loadMods()):toast('Ошибка: '+d.error,false);
  }catch(e){toast('Ошибка сети',false);}
  btn.textContent='Загрузить';btn.disabled=false;
}

$('ov').addEventListener('click',e=>{if(e.target===$('ov'))hideMod();});
document.addEventListener('keydown',e=>{if(e.key==='Escape')hideMod();});

// Settings
async function loadSets(){
  try{
    const d=await(await fetch('/api/settings')).json();_sl=true;
    if(d.ok&&d.settings){$('pfx').value=d.settings.prefix||'.';$('lng').value=d.settings.lang||'ru';$('adel').value=d.settings.autodel||0;}
  }catch(e){}
}

async function sv(k,v){
  try{
    const d=await(await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({[k]:v})})).json();
    toast(d.ok?'Сохранено':'Ошибка',d.ok);
  }catch(e){toast('Ошибка сети',false);}
}

// Logs
async function loadLogs(){
  $('lw').innerHTML='<div class="ld2"><span class="sp"></span>загрузка...</div>';
  try{
    const d=await(await fetch('/api/logs?limit=300')).json();
    if(!d.ok||!d.logs||!d.logs.length){$('lw').innerHTML='<div class="empty"><svg class="icon"><use href="#icon-file-text"/></svg><div>Логов нет</div></div>';return;}
    $('lw').innerHTML=d.logs.map(l=>{
      const ll=l.toLowerCase();
      let c='ld';
      if(ll.includes('[error]')||ll.includes('error'))c='le';
      else if(ll.includes('[warn]')||ll.includes('warning'))c='lwarn';
      else if(ll.includes('[info]'))c='li';
      return '<div class="'+c+'">'+esc(l)+'</div>';
    }).join('');
    $('lw').scrollTop=$('lw').scrollHeight;
  }catch(e){$('lw').innerHTML='<div class="empty"><svg class="icon"><use href="#icon-alert"/></svg><div>Ошибка</div></div>';}
}
</script>
</body>
</html>
"""
    return (_tpl
            .replace("__KVERSION__", str(version))
            .replace("__KNAME__", str(name))
            .replace("__KUSERNAME__", str(username or "").lstrip("@") or "—")
            .replace("__KUID__", str(uid)))
