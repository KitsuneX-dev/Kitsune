
from __future__ import annotations

import json
import logging
import typing

try:
    import psutil
except ImportError:
    psutil = None

from . import auth as _auth
from .routes_accounts import RoutesAccountsMixin
from .routes_system import RoutesSystemMixin

logger = logging.getLogger(__name__)

try:
    import aiohttp
    import aiohttp.web
    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False


class WebCore(RoutesSystemMixin, RoutesAccountsMixin):
    def __init__(self, client: typing.Any, db: typing.Any) -> None:
        self._client = client
        self._db = db
        self._runner: typing.Any = None
        self._site: typing.Any = None
        self._setup_sessions: dict = {}
        self._proc: typing.Any = None
        self._token: str | None = None
        self._limiter = _auth.RateLimiter()
        try:
            allow = db.get("kitsune.web", "cors_allow_origins", []) or []
            self._cors_allow = [str(o) for o in allow if o]
        except Exception:
            self._cors_allow = []
        if psutil is not None:
            try:
                self._proc = psutil.Process()
                self._proc.cpu_percent(interval=None)
            except Exception:
                logger.debug("WebCore: не удалось прогреть счётчик CPU", exc_info=True)
                self._proc = None

    async def start(self, host: str = "127.0.0.1", port: int = 8080) -> None:
        if not WEB_AVAILABLE:
            logger.warning("WebCore: aiohttp not available, web UI disabled")
            return

        self._token = await _auth.ensure_web_token(self._db)

        middleware = _auth.build_auth_middleware(
            get_token=lambda: self._token,
            limiter=self._limiter,
        )
        app = aiohttp.web.Application(
            middlewares=[self._build_cors_middleware(), middleware],
        )
        app.router.add_get("/",                              self._handle_root)
        app.router.add_get("/api/status",                    self._handle_status)
        app.router.add_get("/api/modules",                   self._handle_modules)
        app.router.add_post("/api/modules/action/{name}",    self._handle_module_action)
        app.router.add_post("/api/modules/load",             self._handle_module_load)
        app.router.add_route("GET",  "/api/modules/config/{name}", self._handle_module_config)
        app.router.add_route("POST", "/api/modules/config/{name}", self._handle_module_config)
        app.router.add_get("/api/settings",                  self._handle_settings)
        app.router.add_post("/api/settings",                 self._handle_settings)
        app.router.add_get("/api/logs",                      self._handle_logs)
        app.router.add_get("/api/accounts",                  self._handle_accounts_list)
        app.router.add_post("/api/accounts/create",          self._handle_accounts_create)
        app.router.add_post("/api/accounts/setup/sendcode",  self._handle_accounts_sendcode)
        app.router.add_get("/api/accounts/setup/state/{slug}", self._handle_accounts_setup_state)
        app.router.add_post("/api/accounts/setup/signin",    self._handle_accounts_signin)
        app.router.add_post("/api/accounts/setup/2fa",       self._handle_accounts_2fa)
        app.router.add_post("/api/accounts/toggle/{slug}",   self._handle_accounts_toggle)
        app.router.add_post("/api/accounts/delete/{slug}",   self._handle_accounts_delete)
        app.router.add_get("/health",                        self._handle_health)
        app.router.add_get("/static/{filename}",             self._handle_static)
        self._runner = aiohttp.web.AppRunner(app)
        await self._runner.setup()
        self._site = aiohttp.web.TCPSite(self._runner, host, port)
        try:
            await self._site.start()
            logger.info("WebCore: listening on http://%s:%d", host, port)
            if host in ("0.0.0.0", "::"):
                logger.warning(
                    "WebCore: панель слушает %s — доступна из сети! "
                    "Доступ защищён токеном, но убедитесь, что это осознанно.",
                    host,
                )
            await self._announce_token(host, port)
        except OSError as exc:
            logger.error("WebCore: could not bind to %s:%d — %s", host, port, exc)

    async def _announce_token(self, host: str, port: int) -> None:
        if not self._token:
            return
        disp_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        url = f"http://{disp_host}:{port}/?token={self._token}"
        logger.info("WebCore: токен доступа к веб-панели — %s", self._token)
        logger.info("WebCore: вход в панель по ссылке: %s", url)
        try:
            text = (
                "🦊 <b>Веб-панель Kitsune</b>\n\n"
                "Токен доступа (никому не показывайте):\n"
                f"<code>{self._token}</code>\n\n"
                f"Ссылка для входа:\n<code>{url}</code>"
            )
            await self._client.send_message("me", text, parse_mode="html")
        except Exception:
            logger.debug("WebCore: не удалось отправить токен в «Избранное»", exc_info=True)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    def _cors_headers(self, request: typing.Any) -> dict[str, str]:
        origin = request.headers.get("Origin", "")
        if origin and origin in self._cors_allow:
            return {
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Vary": "Origin",
            }
        return {}

    def _build_cors_middleware(self):
        @aiohttp.web.middleware
        async def cors_middleware(request, handler):
            response = await handler(request)
            for name, value in self._cors_headers(request).items():
                response.headers[name] = value
            return response
        return cors_middleware

    def _json(self, data, status=200):
        return aiohttp.web.Response(
            text=json.dumps(data, ensure_ascii=False),
            content_type="application/json", status=status,
        )
