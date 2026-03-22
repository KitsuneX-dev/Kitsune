from __future__ import annotations

import asyncio
import json
import logging
import os
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import aiohttp
    import aiohttp_jinja2
    import jinja2
    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False

_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "web-resources" / "templates"
_STATIC_DIR    = Path(__file__).parent.parent.parent / "web-resources" / "static"

class WebCore:
    def __init__(self, client: typing.Any, db: typing.Any) -> None:
        self._client  = client
        self._db      = db
        self._runner: typing.Any = None
        self._site:   typing.Any = None

    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        if not WEB_AVAILABLE:
            logger.warning("WebCore: aiohttp not available, web UI disabled")
            return

        app = aiohttp.web.Application()

        if _TEMPLATES_DIR.exists():
            aiohttp_jinja2.setup(
                app,
                loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
            )

        app.router.add_get("/",               self._handle_root)
        app.router.add_get("/api/status",     self._handle_status)
        app.router.add_post("/api/save_config", self._handle_save_config)
        if _STATIC_DIR.exists():
            app.router.add_static("/static", str(_STATIC_DIR))

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

    async def _handle_root(self, request: "aiohttp.web.Request") -> "aiohttp.web.Response":
        from ..version import __version_str__
        import psutil, time
        me = self._client.tg_me
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.1)
        mem_used = mem.used // 1024 // 1024
        mem_total = mem.total // 1024 // 1024
        mem_pct = int(mem.percent)
        name = me.first_name if me else "—"
        uid  = me.id if me else "—"
        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kitsune Userbot</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: 'Segoe UI', system-ui, sans-serif;
  background: #0a0a12;
  color: #c8b8f0;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background-image:
    linear-gradient(rgba(120,80,255,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(120,80,255,0.03) 1px, transparent 1px);
  background-size: 40px 40px;
}}
.card {{
  width: 100%;
  max-width: 460px;
  background: #12121e;
  border: 1px solid rgba(140,90,255,0.2);
  border-radius: 20px;
  padding: 36px;
  box-shadow: 0 0 60px rgba(120,60,255,0.12), 0 0 120px rgba(120,60,255,0.05);
}}
.header {{
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 28px;
  padding-bottom: 20px;
  border-bottom: 1px solid rgba(140,90,255,0.12);
}}
.logo {{ font-size: 2.2rem; }}
.header-text h1 {{
  font-size: 1.3rem;
  font-weight: 700;
  color: #e0d0ff;
  letter-spacing: 0.3px;
}}
.version {{
  font-size: 0.75rem;
  color: #6a5a8a;
  margin-top: 2px;
}}
.badge-online {{
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(74,222,128,0.1);
  border: 1px solid rgba(74,222,128,0.25);
  border-radius: 20px;
  padding: 3px 10px;
  font-size: 0.75rem;
  color: #4ade80;
  margin-left: auto;
}}
.dot-green {{
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #4ade80;
  box-shadow: 0 0 6px #4ade80;
  animation: pulse 2s infinite;
}}
@keyframes pulse {{
  0%, 100% {{ opacity: 1; }}
  50% {{ opacity: 0.5; }}
}}
.rows {{ display: flex; flex-direction: column; gap: 2px; margin-bottom: 24px; }}
.row {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border-radius: 10px;
  transition: background .15s;
}}
.row:hover {{ background: rgba(120,80,255,0.05); }}
.label {{ font-size: 0.82rem; color: #6a5a8a; }}
.value {{ font-size: 0.88rem; color: #d0b8ff; font-weight: 500; }}
.divider {{
  height: 1px;
  background: rgba(140,90,255,0.1);
  margin: 20px 0;
}}
.stats-title {{
  font-size: 0.78rem;
  color: #5a4880;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 14px;
}}
.stat-row {{
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}}
.stat-label {{
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  color: #8070a8;
}}
.bar-bg {{
  height: 6px;
  background: rgba(120,80,255,0.1);
  border-radius: 4px;
  overflow: hidden;
}}
.bar-fill {{
  height: 100%;
  background: linear-gradient(90deg, #7030d0, #a050f0);
  border-radius: 4px;
  box-shadow: 0 0 8px rgba(160,80,240,0.4);
}}
.footer {{
  text-align: center;
  font-size: 0.75rem;
  color: #3d3060;
  margin-top: 4px;
}}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <div class="logo">🦊</div>
    <div class="header-text">
      <h1>Kitsune Userbot</h1>
      <div class="version">v{__version_str__}</div>
    </div>
    <div class="badge-online"><div class="dot-green"></div> Online</div>
  </div>

  <div class="rows">
    <div class="row">
      <span class="label">Аккаунт</span>
      <span class="value">{name}</span>
    </div>
    <div class="row">
      <span class="label">ID</span>
      <span class="value">{uid}</span>
    </div>
    <div class="row">
      <span class="label">Разработчик</span>
      <span class="value">Yushi (@Mikasu32)</span>
    </div>
  </div>

  <div class="divider"></div>
  <div class="stats-title">Система</div>

  <div class="stat-row">
    <div class="stat-label"><span>CPU</span><span>{cpu:.0f}%</span></div>
    <div class="bar-bg"><div class="bar-fill" style="width:{cpu:.0f}%"></div></div>
  </div>
  <div class="stat-row">
    <div class="stat-label"><span>RAM</span><span>{mem_used} / {mem_total} MB</span></div>
    <div class="bar-bg"><div class="bar-fill" style="width:{mem_pct}%"></div></div>
  </div>

  <div class="footer">Kitsune · AGPLv3</div>
</div>
</body>
</html>"""
        return aiohttp.web.Response(text=html, content_type="text/html")

    async def _handle_status(self, request: "aiohttp.web.Request") -> "aiohttp.web.Response":
        from ..version import __version_str__
        import psutil, time
        mem = psutil.virtual_memory()
        data = {
            "ok":      True,
            "version": __version_str__,
            "uptime":  int(time.time()),
            "memory":  {"used_mb": mem.used // 1024 // 1024, "total_mb": mem.total // 1024 // 1024},
            "cpu_pct": psutil.cpu_percent(),
        }
        return aiohttp.web.Response(
            text=json.dumps(data),
            content_type="application/json",
        )

    async def _handle_save_config(self, request: "aiohttp.web.Request") -> "aiohttp.web.Response":
        try:
            body = await request.json()
        except Exception:
            return aiohttp.web.Response(status=400, text='{"ok":false,"error":"bad json"}')

        from ..main import set_config_key
        for k, v in body.items():
            set_config_key(k, v)

        return aiohttp.web.Response(text='{"ok":true}', content_type="application/json")
