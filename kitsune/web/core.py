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
        me = self._client.tg_me
        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <title>Kitsune Userbot</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body{{font-family:system-ui,sans-serif;background:
         display:flex;flex-direction:column;align-items:center;padding:40px}}
    h1{{color:
    .card{{background:
           padding:24px 32px;max-width:420px;width:100%;margin-top:20px}}
    .row{{display:flex;justify-content:space-between;padding:6px 0;
          border-bottom:1px solid
    .row:last-child{{border-bottom:none}}
    .label{{color:
    .badge{{background:
            padding:2px 10px;font-size:.8rem}}
  </style>
</head>
<body>
  <h1>🦊 Kitsune Userbot</h1>
  <span class="badge">v{__version_str__}</span>
  <div class="card">
    <div class="row"><span class="label">Аккаунт</span>
         <span class="value">{me.first_name if me else '—'}</span></div>
    <div class="row"><span class="label">ID</span>
         <span class="value">{me.id if me else '—'}</span></div>
    <div class="row"><span class="label">Статус</span>
         <span class="value" style="color:#4ade80">● Online</span></div>
    <div class="row"><span class="label">Разработчик</span>
         <span class="value">Yushi (@Mikasu32)</span></div>
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
