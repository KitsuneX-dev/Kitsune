
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


def extract_token_candidates(
    request: typing.Any,
    cookie_name: str = COOKIE_NAME,
) -> list[str]:
    out: list[str] = []

    def _add(value: typing.Any) -> None:
        if not value:
            return
        text = str(value).strip()
        if text and text not in out:
            out.append(text)

    try:
        _add(request.query.get("token"))
    except Exception:
        logger.debug("auth: не удалось прочитать token из query", exc_info=True)
    try:
        auth = request.headers.get("Authorization", "") or ""
        if auth.startswith("Bearer "):
            _add(auth[len("Bearer "):])
    except Exception:
        logger.debug("auth: не удалось прочитать заголовок Authorization", exc_info=True)
    try:
        _add(request.cookies.get(cookie_name))
    except Exception:
        logger.debug("auth: не удалось прочитать cookie", exc_info=True)
    return out


def extract_token(request: typing.Any) -> str | None:
    candidates = extract_token_candidates(request)
    return candidates[0] if candidates else None


_UNAUTHORIZED_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kitsune · Доступ закрыт</title>
<style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#0f1014;color:#e6e6ec;font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:24px}
.card{max-width:520px;width:100%;background:#171821;border:1px solid #272935;border-radius:16px;padding:28px 26px}
h1{margin:0 0 14px;font-size:20px;font-weight:600;color:#fff}
p{margin:0 0 12px;color:#b6b8c6}
code{display:block;margin:14px 0 4px;padding:12px 14px;background:#0f1014;border:1px solid #272935;
border-radius:10px;color:#8fd3ff;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
font-size:13px;word-break:break-all}
.hint{margin-top:18px;font-size:13px;color:#7c7f92}
</style>
</head>
<body>
<div class="card">
<h1>🦊 Ссылка устарела</h1>
<p>⚠️ Страница открыта без актуального токена — либо ссылка устарела, либо открыта не та ссылка.</p>
<p>ℹ️ Возьми актуальную ссылку с токеном из консоли, где запущен Kitsune:</p>
<code>http://127.0.0.1:&lt;порт&gt;/?token=&lt;токен&gt;</code>
<p class="hint">Старый cookie уже удалён. Скопируй свежую ссылку целиком и открой её заново.</p>
</div>
</body>
</html>
"""


def _wants_html(request: typing.Any) -> bool:
    try:
        if str(request.method).upper() != "GET":
            return False
        accept = request.headers.get("Accept", "") or ""
    except Exception:
        return False
    return "text/html" in accept.lower()


def build_auth_middleware(
    get_token: typing.Callable[[], str | None],
    limiter: RateLimiter,
    public_paths: typing.Iterable[str] = _PUBLIC_PATHS,
    cookie_name: str = COOKIE_NAME,
    public_prefixes: typing.Iterable[str] = (),
) -> typing.Any:
    public = frozenset(public_paths)
    prefixes = tuple(public_prefixes)

    @aiohttp.web.middleware
    async def auth_middleware(request, handler):
        path = request.path
        if path in public:
            return await handler(request)
        if prefixes and path.startswith(prefixes):
            return await handler(request)

        ip = _client_ip(request)
        if limiter.is_blocked(ip):
            return aiohttp.web.Response(
                status=429, text="too many attempts, try later",
            )

        expected = get_token()
        candidates = extract_token_candidates(request, cookie_name)
        cookie_value = None
        try:
            cookie_value = request.cookies.get(cookie_name)
        except Exception:
            logger.debug("auth: не удалось прочитать cookie", exc_info=True)

        if not any(tokens_equal(t, expected) for t in candidates):
            limiter.register_fail(ip)
            if _wants_html(request):
                response = aiohttp.web.Response(
                    status=401, text=_UNAUTHORIZED_HTML, content_type="text/html",
                )
            else:
                response = aiohttp.web.Response(status=401, text="unauthorized")
            if cookie_value:
                logger.warning(
                    "auth: получен устаревший cookie %s — удаляю его", cookie_name,
                )
                response.del_cookie(cookie_name, path="/")
            return response

        limiter.register_success(ip)
        response = await handler(request)

        if expected and not tokens_equal(cookie_value, expected):
            response.set_cookie(
                cookie_name, expected,
                httponly=True, samesite="Lax", path="/",
                max_age=7 * 24 * 3600,
            )
        return response

    return auth_middleware


def apply_security_headers(response: typing.Any) -> None:
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
