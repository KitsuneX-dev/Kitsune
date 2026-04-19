from __future__ import annotations

import asyncio
import json
import logging
import typing
from pathlib import Path

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
        """
        Лёгкий health-check: отвечает 200 OK если бот жив.
        Используется мониторингом / watchdog-скриптами.
        GET /health → {"ok": true, "uptime_s": 123, "connected": true}
        """
        import time
        start = self._db.get("kitsune.ping", "start_time", None)
        uptime = int(time.time() - float(start)) if start else 0
        connected = getattr(self._client, "is_connected", lambda: False)()
        return self._json({
            "ok": True,
            "uptime_s": uptime,
            "connected": connected,
        })

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
    return """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>🦊 Kitsune """ + version + """</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700&family=DM+Sans:opsz,wght@9..40,300;9..40,500;9..40,700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{
  --bg:#0d0d0f;--s1:#141418;--s2:#1c1c22;
  --bd:rgba(255,255,255,0.07);--bd2:rgba(255,255,255,0.12);
  --tx:#e8e8ec;--mu:rgba(255,255,255,0.35);--mu2:rgba(255,255,255,0.58);
  --fox:#ff6b35;--fox2:#ff8c5a;
  --blue:#4a9eff;--red:#ff4a6b;--green:#3dffaa;
  --gr-dim:rgba(61,255,170,0.08);--ylw:#ffc857;
  --mono:'Space Mono',monospace;--body:'DM Sans',sans-serif;
  --r:14px;--r2:10px;--ease:.18s cubic-bezier(.4,0,.2,1);
}
html{height:100%}
body{
  font-family:var(--body);background:var(--bg);color:var(--tx);min-height:100%;
  overflow-x:hidden;
  background-image:
    radial-gradient(ellipse 70% 50% at 5% 0%,rgba(255,107,53,0.08) 0%,transparent 55%),
    radial-gradient(ellipse 50% 40% at 95% 100%,rgba(74,158,255,0.05) 0%,transparent 55%);
}
.app{max-width:960px;margin:0 auto;padding:0 16px 40px}
/* Header */
.hdr{padding:20px 0 18px;display:flex;align-items:center;gap:14px;border-bottom:1px solid var(--bd)}
.logo{width:46px;height:46px;flex-shrink:0;border-radius:14px;background:linear-gradient(135deg,#ff6b35,#ff4a6b);position:relative;display:flex;align-items:center;justify-content:center;font-size:1.4rem}
.logo::after{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(255,255,255,0.18),transparent)}
.hdr-info{flex:1;min-width:0}
.hdr-title{font-family:var(--mono);font-size:.92rem;font-weight:700;color:var(--tx)}
.hdr-sub{font-size:.68rem;color:var(--mu);margin-top:3px;font-family:var(--mono)}
.online{display:inline-flex;align-items:center;gap:5px;background:var(--gr-dim);border:1px solid rgba(61,255,170,0.2);border-radius:20px;padding:5px 12px;font-size:.65rem;font-weight:700;color:var(--green);font-family:var(--mono);letter-spacing:.05em}
.dot{width:5px;height:5px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);animation:blink 2s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}
/* Nav */
.nav{display:flex;gap:2px;padding:12px 0 0;overflow-x:auto;scrollbar-width:none}
.nav::-webkit-scrollbar{display:none}
.nb{flex-shrink:0;padding:9px 16px;border-radius:9px;border:none;font-family:var(--body);font-size:.78rem;font-weight:500;color:var(--mu2);background:transparent;cursor:pointer;transition:var(--ease);white-space:nowrap;border:1px solid transparent}
.nb:hover{color:var(--tx);background:var(--s2)}
.nb.on{color:var(--fox2);background:rgba(255,107,53,0.1);border-color:rgba(255,107,53,0.18)}
/* Panel */
.panel{display:none;padding-top:20px;animation:fi .2s ease both}
.panel.on{display:block}
@keyframes fi{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
/* Card */
.card{background:var(--s1);border:1px solid var(--bd);border-radius:var(--r);padding:18px;margin-bottom:12px;transition:border-color var(--ease)}
.card:hover{border-color:var(--bd2)}
.ctit{font-family:var(--mono);font-size:.62rem;font-weight:700;color:var(--mu);letter-spacing:.1em;text-transform:uppercase;margin-bottom:14px}
/* Stat grid */
.sg{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px}
.sb{background:var(--s2);border:1px solid var(--bd);border-radius:var(--r2);padding:14px 16px}
.sl{font-size:.62rem;color:var(--mu);font-family:var(--mono);letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px}
.sv{font-family:var(--mono);font-size:1.1rem;font-weight:700;color:var(--tx)}
.sv.fox{color:var(--fox2)}.sv.gr{color:var(--green)}
/* Row */
.rows{display:flex;flex-direction:column}
.row{display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-bottom:1px solid rgba(255,255,255,0.04)}
.row:last-child{border:none}
.rk{font-size:.78rem;color:var(--mu2);font-weight:300}
.rv{font-size:.78rem;color:var(--tx);font-weight:500;font-family:var(--mono);max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right}
.rv.fox{color:var(--fox2)}
/* Bars */
.bar{margin-top:10px}
.bh{display:flex;justify-content:space-between;margin-bottom:5px}
.bn{font-size:.7rem;color:var(--mu2)}.bv{font-size:.7rem;color:var(--mu);font-family:var(--mono)}
.bt{height:4px;border-radius:2px;background:rgba(255,255,255,0.06);overflow:hidden}
.bf{height:100%;border-radius:2px;background:linear-gradient(90deg,var(--fox),var(--fox2));transition:width .8s cubic-bezier(.4,0,.2,1)}
.bf.mid{background:linear-gradient(90deg,#ffc857,#ff8c5a)}
/* Modules */
.mc{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:10px;flex-wrap:wrap}
.mf{display:flex;gap:6px;flex-wrap:wrap}
.fi{padding:6px 12px;border-radius:20px;border:1px solid var(--bd);background:transparent;color:var(--mu2);cursor:pointer;font-size:.72rem;font-family:var(--body);transition:var(--ease)}
.fi:hover{border-color:var(--bd2);color:var(--tx)}
.fi.on{background:rgba(255,107,53,0.12);border-color:rgba(255,107,53,0.25);color:var(--fox2)}
.mb{font-size:.68rem;color:var(--mu);font-family:var(--mono);padding:3px 8px;background:var(--s2);border-radius:6px}
.mg{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
@media(max-width:580px){.mg{grid-template-columns:1fr}}
.mc2{background:var(--s1);border:1px solid var(--bd);border-radius:var(--r);padding:16px;display:flex;flex-direction:column;gap:10px;transition:border-color var(--ease),transform var(--ease)}
.mc2:hover{border-color:rgba(255,107,53,0.25);transform:translateY(-2px)}
.mct{display:flex;align-items:center;gap:10px}
.mi{width:38px;height:38px;flex-shrink:0;border-radius:10px;background:linear-gradient(135deg,rgba(255,107,53,0.2),rgba(255,107,53,0.04));border:1px solid rgba(255,107,53,0.15);display:flex;align-items:center;justify-content:center;font-size:1.1rem}
.mn{font-size:.85rem;font-weight:700;color:var(--tx);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mm{font-size:.66rem;color:var(--mu);margin-top:2px;font-family:var(--mono)}
.md{font-size:.73rem;color:var(--mu2);line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.mf2{display:flex;gap:6px;justify-content:flex-end;padding-top:8px;border-top:1px solid var(--bd)}
.tsys{display:inline-flex;padding:2px 7px;border-radius:5px;font-size:.6rem;font-weight:700;font-family:var(--mono);background:rgba(74,158,255,0.12);color:var(--blue);border:1px solid rgba(74,158,255,0.2);margin-left:6px}
/* Btn */
.btn{display:inline-flex;align-items:center;gap:5px;padding:8px 14px;border-radius:var(--r2);border:1px solid var(--bd2);background:transparent;color:var(--mu2);cursor:pointer;font-size:.75rem;font-family:var(--body);font-weight:500;transition:var(--ease);white-space:nowrap}
.btn:hover{border-color:rgba(255,107,53,0.4);color:var(--fox2);background:rgba(255,107,53,0.06)}
.btn.pri{background:rgba(255,107,53,0.14);border-color:rgba(255,107,53,0.28);color:var(--fox2)}
.btn.pri:hover{background:rgba(255,107,53,0.24)}
.btn.dng:hover{border-color:rgba(255,74,107,0.4);color:var(--red);background:rgba(255,74,107,0.06)}
.btn.sm{padding:5px 10px;font-size:.7rem}
/* Settings */
.sr{display:flex;align-items:center;justify-content:space-between;padding:11px 0;border-bottom:1px solid rgba(255,255,255,0.04)}
.sr:last-child{border:none}
.slb{font-size:.8rem;color:var(--tx)}
.ss{font-size:.68rem;color:var(--mu);margin-top:2px}
.inp{background:var(--s2);border:1px solid var(--bd2);border-radius:8px;padding:8px 12px;color:var(--tx);font-size:.8rem;font-family:var(--mono);outline:none;transition:border-color var(--ease);width:100px}
.inp:focus{border-color:rgba(255,107,53,0.4)}
.sel{background:var(--s2);border:1px solid var(--bd2);border-radius:8px;padding:8px 12px;color:var(--tx);font-size:.8rem;font-family:var(--body);outline:none;cursor:pointer;width:130px}
/* Logs */
.lw{background:var(--s2);border:1px solid var(--bd);border-radius:var(--r2);padding:14px;font-family:var(--mono);font-size:.68rem;max-height:500px;overflow-y:auto;line-height:1.65;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,0.1) transparent}
.lw::-webkit-scrollbar{width:4px}.lw::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:2px}
.le{color:var(--red)}.lw2{color:var(--ylw)}.li{color:var(--mu2)}.ld{color:var(--mu)}
/* Modal */
.ov{position:fixed;inset:0;background:rgba(0,0,0,.75);display:none;align-items:center;justify-content:center;z-index:100;padding:16px;backdrop-filter:blur(4px)}
.ov.on{display:flex}
.modal{background:var(--s1);border:1px solid var(--bd2);border-radius:18px;padding:24px;width:100%;max-width:400px;box-shadow:0 24px 60px rgba(0,0,0,.6)}
.mtit{font-family:var(--mono);font-size:.9rem;font-weight:700;margin-bottom:16px}
.mi2{width:100%;background:var(--s2);border:1px solid var(--bd2);border-radius:10px;padding:11px 14px;color:var(--tx);font-size:.85rem;font-family:var(--mono);outline:none;margin-bottom:14px;transition:border-color var(--ease)}
.mi2:focus{border-color:rgba(255,107,53,0.4)}
.mbs{display:flex;gap:10px;justify-content:flex-end}
.mok{padding:10px 18px;border-radius:10px;border:none;font-size:.82rem;font-weight:700;cursor:pointer;background:linear-gradient(135deg,#ff6b35,#ff4a6b);color:#fff;font-family:var(--body);transition:var(--ease)}
.mok:hover{filter:brightness(1.1)}
.mno{padding:10px 18px;border-radius:10px;background:var(--s2);color:var(--mu2);border:1px solid var(--bd);font-size:.82rem;cursor:pointer;font-family:var(--body);transition:var(--ease)}
.mno:hover{border-color:var(--bd2);color:var(--tx)}
/* Toast */
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(16px);background:var(--s2);border:1px solid var(--bd2);border-radius:12px;padding:11px 18px;font-size:.78rem;color:var(--tx);box-shadow:0 8px 32px rgba(0,0,0,.5);opacity:0;pointer-events:none;transition:all .25s cubic-bezier(.4,0,.2,1);z-index:999;display:flex;align-items:center;gap:8px;max-width:calc(100vw - 32px);white-space:nowrap}
.toast.on{opacity:1;transform:translateX(-50%) translateY(0)}
/* Pager */
.pg{display:flex;justify-content:center;gap:6px;margin-top:16px;flex-wrap:wrap}
.pgb{padding:7px 12px;border-radius:8px;border:1px solid var(--bd);background:transparent;color:var(--mu2);cursor:pointer;font-size:.74rem;transition:var(--ease);font-family:var(--mono)}
.pgb:hover{border-color:var(--bd2);color:var(--tx)}
.pgb.on{background:rgba(255,107,53,0.14);border-color:rgba(255,107,53,0.28);color:var(--fox2)}
/* Empty/Loading */
.empty{text-align:center;padding:40px 20px;color:var(--mu)}.eico{font-size:2rem;margin-bottom:8px;opacity:.35}
.ld2{text-align:center;padding:32px;color:var(--mu);font-size:.8rem}
.sp{display:inline-block;width:14px;height:14px;vertical-align:middle;border:2px solid rgba(255,255,255,.1);border-top-color:var(--fox2);border-radius:50%;animation:spin .6s linear infinite;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
/* Footer */
.footer{display:flex;justify-content:space-between;align-items:center;padding:14px 0 0;border-top:1px solid var(--bd);margin-top:6px;font-size:.65rem;color:var(--mu);font-family:var(--mono)}
</style>
</head>
<body>
<div class="app">

<header class="hdr">
  <div class="logo">🦊</div>
  <div class="hdr-info">
    <div class="hdr-title">kitsune_userbot</div>
    <div class="hdr-sub">v""" + version + """ &nbsp;·&nbsp; @Mikasu32</div>
  </div>
  <div class="online"><div class="dot"></div>online</div>
</header>

<nav class="nav">
  <button class="nb on" onclick="go('dash',this)">⬡ Обзор</button>
  <button class="nb" onclick="go('mods',this)">◫ Модули</button>
  <button class="nb" onclick="go('sets',this)">◈ Настройки</button>
  <button class="nb" onclick="go('logs',this)">≡ Логи</button>
</nav>

<!-- DASH -->
<div class="panel on" id="p-dash">
  <div class="sg">
    <div class="sb"><div class="sl">модули</div><div class="sv fox" id="s-mods">—</div></div>
    <div class="sb"><div class="sl">CPU</div><div class="sv" id="s-cpu">—</div></div>
    <div class="sb"><div class="sl">RAM</div><div class="sv" id="s-ram">—</div></div>
    <div class="sb"><div class="sl">DISK</div><div class="sv" id="s-disk">—</div></div>
  </div>
  <div class="card">
    <div class="ctit">Аккаунт</div>
    <div class="rows">
      <div class="row"><span class="rk">Имя</span><span class="rv fox">""" + name + """</span></div>
      <div class="row"><span class="rk">Username</span><span class="rv">""" + (username or "—") + """</span></div>
      <div class="row"><span class="rk">ID</span><span class="rv">""" + str(uid) + """</span></div>
      <div class="row"><span class="rk">Разработчик</span><span class="rv">Yushi · @Mikasu32</span></div>
    </div>
  </div>
  <div class="card">
    <div class="ctit">Ресурсы системы</div>
    <div id="bars"><div class="ld2"><span class="sp"></span>загрузка...</div></div>
  </div>
  <div class="footer"><span id="ts">обновление...</span><span>kitsune v""" + version + """</span></div>
</div>

<!-- MODULES -->
<div class="panel" id="p-mods">
  <div class="mc">
    <div class="mf">
      <button class="fi on" onclick="filt('all',this)">Все <span class="mb" id="mc-a">0</span></button>
      <button class="fi" onclick="filt('sys',this)">Системные <span class="mb" id="mc-s">0</span></button>
      <button class="fi" onclick="filt('usr',this)">Пользовательские <span class="mb" id="mc-u">0</span></button>
    </div>
    <button class="btn pri" onclick="showMod()">＋ Загрузить</button>
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
        <option value="ru">🇷🇺 Русский</option>
        <option value="en">🇬🇧 English</option>
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
    <button class="btn sm" onclick="loadLogs()">🔄 Обновить</button>
  </div>
  <div class="lw" id="lw"><div class="ld2"><span class="sp"></span>загрузка...</div></div>
</div>

</div>

<div class="toast" id="toast"><span id="tmsg"></span></div>

<div class="ov" id="ov">
  <div class="modal">
    <div class="mtit">Загрузить модуль</div>
    <input type="text" class="mi2" id="murl" placeholder="URL модуля (.py) или название">
    <div class="mbs">
      <button class="mno" onclick="hideMod()">Отмена</button>
      <button class="mok" onclick="doLoad()">Загрузить</button>
    </div>
  </div>
</div>

<script>
let _tt,_mods=[],_pg=1,_ppg=6,_filt='all',_ml=false,_sl=false;
const $=id=>document.getElementById(id);
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function toast(m,ok=true){
  const t=$('toast');$('tmsg').textContent=(ok?'✓  ':' ✕  ')+m;
  t.style.borderColor=ok?'rgba(61,255,170,.2)':'rgba(255,74,107,.2)';
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
      return `<div class="bar"><div class="bh"><span class="bn">${nm}</span><span class="bv">${vl}</span></div><div class="bt"><div class="bf ${c}" style="width:${p}%"></div></div></div>`;
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
    if(!d.ok||!d.modules){$('mg').innerHTML='<div class="empty"><div class="eico">📦</div>Нет модулей</div>';return;}
    _mods=d.modules;
    $('mc-a').textContent=_mods.length;
    $('mc-s').textContent=_mods.filter(m=>m.is_builtin).length;
    $('mc-u').textContent=_mods.filter(m=>!m.is_builtin).length;
    render();
  }catch(e){$('mg').innerHTML='<div class="empty"><div class="eico">⚠️</div>Ошибка загрузки</div>';}
}
function filt(t,btn){document.querySelectorAll('.fi').forEach(b=>b.classList.remove('on'));btn.classList.add('on');_filt=t;_pg=1;render();}
function render(){
  const mob=window.innerWidth<=560;_ppg=mob?4:6;
  let list=_mods;
  if(_filt==='sys')list=_mods.filter(m=>m.is_builtin);
  else if(_filt==='usr')list=_mods.filter(m=>!m.is_builtin);
  const tot=Math.ceil(list.length/_ppg);
  const page=list.slice((_pg-1)*_ppg,_pg*_ppg);
  if(!page.length){$('mg').innerHTML='<div class="empty"><div class="eico">📦</div>Нет модулей</div>';$('pg').innerHTML='';return;}
  $('mg').innerHTML=page.map(m=>`
    <div class="mc2">
      <div class="mct">
        <div class="mi">${m.icon||'📦'}</div>
        <div style="flex:1;min-width:0">
          <div class="mn">${esc(m.name)}${m.is_builtin?'<span class="tsys">sys</span>':''}</div>
          <div class="mm">v${m.version}${m.author?' · '+esc(m.author):''}</div>
        </div>
      </div>
      ${m.description?'<div class="md">'+esc(m.description)+'</div>':''}
      ${!m.is_builtin?`<div class="mf2">
        <button class="btn sm" onclick="rl('${m.name}')">🔄</button>
        <button class="btn sm dng" onclick="ul('${m.name}')">✕</button>
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
    if(!d.ok||!d.logs||!d.logs.length){$('lw').innerHTML='<div class="empty"><div class="eico">📜</div>Логов нет</div>';return;}
    $('lw').innerHTML=d.logs.map(l=>{
      const ll=l.toLowerCase();
      let c='ld';
      if(ll.includes('[error]')||ll.includes('error'))c='le';
      else if(ll.includes('[warn]')||ll.includes('warning'))c='lw2';
      else if(ll.includes('[info]'))c='li';
      return '<div class="'+c+'">'+esc(l)+'</div>';
    }).join('');
    $('lw').scrollTop=$('lw').scrollHeight;
  }catch(e){$('lw').innerHTML='<div class="empty"><div class="eico">⚠️</div>Ошибка</div>';}
}
</script>
</body>
</html>"""
