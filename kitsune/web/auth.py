
from __future__ import annotations

import hmac
import logging
import secrets
import time
import typing

try:
    import aiohttp
    import aiohttp.web
    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False

logger = logging.getLogger(__name__)

_DB_WEB = "kitsune.web"
_DB_TOKEN_KEY = "access_token"

COOKIE_NAME = "kitsune_token"

_PUBLIC_PATHS = frozenset({"/health"})

SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "script-src 'self' 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    ),
}


def generate_token() -> str:
    return secrets.token_urlsafe(32)


async def ensure_web_token(db: typing.Any) -> str:
    token = None
    try:
        token = db.get(_DB_WEB, _DB_TOKEN_KEY, None)
    except Exception:
        logger.debug("auth: не удалось прочитать токен из БД", exc_info=True)
    if isinstance(token, str) and token:
        return token
    token = generate_token()
    try:
        result = db.set(_DB_WEB, _DB_TOKEN_KEY, token)
        if hasattr(result, "__await__"):
            await result
    except Exception:
        logger.exception("auth: не удалось сохранить токен веб-панели")
    return token


def tokens_equal(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(str(a), str(b))


class RateLimiter:

    def __init__(self, max_fails: int = 10, window: float = 60.0, block: float = 300.0) -> None:
        self._max = max_fails
        self._window = window
        self._block = block
        self._fails: dict[str, list[float]] = {}
        self._blocked: dict[str, float] = {}

    def is_blocked(self, ip: str) -> bool:
        until = self._blocked.get(ip)
        if until is None:
            return False
        if time.monotonic() >= until:
            self._blocked.pop(ip, None)
            self._fails.pop(ip, None)
            return False
        return True

    def register_fail(self, ip: str) -> None:
        now = time.monotonic()
        bucket = [t for t in self._fails.get(ip, []) if now - t < self._window]
        bucket.append(now)
        self._fails[ip] = bucket
        if len(bucket) >= self._max:
            self._blocked[ip] = now + self._block
            logger.warning(
                "auth: IP %s заблокирован на %.0f c за %d неудачных попыток",
                ip, self._block, len(bucket),
            )

    def register_success(self, ip: str) -> None:
        self._fails.pop(ip, None)
        self._blocked.pop(ip, None)


def _client_ip(request: typing.Any) -> str:
    peer = request.remote or "?"
    return str(peer)


def extract_token(request: typing.Any) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        tok = auth[len("Bearer "):].strip()
        if tok:
            return tok
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie
    q = request.query.get("token")
    if q:
        return q
    return None


def build_auth_middleware(
    get_token: typing.Callable[[], str | None],
    limiter: RateLimiter,
    public_paths: typing.Iterable[str] = _PUBLIC_PATHS,
) -> typing.Any:
    public = frozenset(public_paths)

    @aiohttp.web.middleware
    async def auth_middleware(request, handler):
        path = request.path
        if path in public:
            return await handler(request)

        ip = _client_ip(request)
        if limiter.is_blocked(ip):
            return aiohttp.web.Response(
                status=429, text="too many attempts, try later",
            )

        expected = get_token()
        provided = extract_token(request)

        if not tokens_equal(provided, expected):
            limiter.register_fail(ip)
            return aiohttp.web.Response(status=401, text="unauthorized")

        limiter.register_success(ip)
        response = await handler(request)

        if request.query.get("token") and expected:
            response.set_cookie(
                COOKIE_NAME, expected,
                httponly=True, samesite="Strict", path="/",
                max_age=7 * 24 * 3600,
            )
        return response

    return auth_middleware


def apply_security_headers(response: typing.Any) -> None:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
