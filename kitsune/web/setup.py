"""
Kitsune Web Setup — first-run configuration interface.
Launches a local aiohttp server so the user can configure and log in via browser.
"""

# © Yushi (@Mikasu32), 2024-2025
# Kitsune Userbot — License: AGPLv3

from __future__ import annotations

import asyncio
import logging
import webbrowser
from typing import Any, Callable

from aiohttp import web

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML page (single-file, no external deps)
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kitsune Setup</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #0d0d1a;
    color: #e0e0ff;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }
  .card {
    width: 100%;
    max-width: 460px;
    background: #13132a;
    border: 1px solid #7c3aed33;
    border-radius: 20px;
    padding: 44px 40px;
    box-shadow: 0 0 60px #7c3aed18;
  }
  .logo { text-align: center; font-size: 3rem; margin-bottom: 6px; }
  h1 { text-align: center; font-size: 1.45rem; color: #a78bfa; margin-bottom: 4px; }
  .sub { text-align: center; font-size: 0.82rem; color: #555; margin-bottom: 36px; }
  .step { display: none; animation: fadeIn .25s ease; }
  .step.active { display: block; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
  .step-title { font-size: 1rem; font-weight: 600; color: #c4b5fd; margin-bottom: 18px; }
  label { display: block; font-size: 0.8rem; color: #a78bfa; margin: 14px 0 5px; }
  input {
    width: 100%; padding: 11px 14px;
    background: #0d0d1a; border: 1px solid #7c3aed44;
    border-radius: 9px; color: #e0e0ff; font-size: 0.93rem;
    outline: none; transition: border .2s;
  }
  input:focus { border-color: #7c3aed; box-shadow: 0 0 0 3px #7c3aed18; }
  .hint { font-size: 0.77rem; color: #4a4a6a; margin-top: 5px; }
  .hint a { color: #7c3aed; text-decoration: none; }
  .hint a:hover { text-decoration: underline; }
  button {
    width: 100%; margin-top: 22px; padding: 13px;
    background: linear-gradient(135deg, #7c3aed, #5b21b6);
    border: none; border-radius: 10px; color: #fff;
    font-size: 0.97rem; font-weight: 600; cursor: pointer;
    transition: opacity .2s, transform .1s;
  }
  button:hover { opacity: .88; }
  button:active { transform: scale(.98); }
  button:disabled { opacity: .35; cursor: not-allowed; }
  .error {
    display: none; margin-top: 14px; padding: 10px 14px;
    background: #2d0000; border: 1px solid #f87171;
    border-radius: 8px; font-size: 0.82rem; color: #fca5a5;
  }
  details { margin-top: 18px; }
  details summary {
    cursor: pointer; font-size: 0.82rem; color: #7c3aed;
    user-select: none; list-style: none; display: flex; align-items: center; gap: 6px;
  }
  details summary::before { content: '▶'; font-size: .65rem; transition: transform .2s; }
  details[open] summary::before { transform: rotate(90deg); }
  details .proxy-fields { margin-top: 4px; }
  .proxy-row { display: flex; gap: 10px; }
  .proxy-row input:first-child { flex: 1; }
  .proxy-row input:last-child { width: 90px; flex-shrink: 0; }
  .done-wrap { text-align: center; padding: 10px 0; }
  .done-icon { font-size: 3.5rem; margin-bottom: 12px; }
  .done-title { font-size: 1.2rem; font-weight: 700; color: #86efac; margin-bottom: 6px; }
  .done-sub { font-size: 0.85rem; color: #555; }
  .done-info {
    margin-top: 20px; padding: 12px 16px;
    background: #0d0d1a; border-radius: 10px;
    font-size: 0.83rem; color: #888; line-height: 1.8;
    text-align: left;
  }
  .steps-bar {
    display: flex; gap: 6px; margin-bottom: 28px; justify-content: center;
  }
  .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: #2a2a4a; transition: background .3s;
  }
  .dot.active { background: #7c3aed; }
  .dot.done { background: #5b21b6; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">🦊</div>
  <h1>Kitsune Userbot</h1>
  <p class="sub">by Yushi · первоначальная настройка</p>

  <div class="steps-bar">
    <div class="dot active" id="d1"></div>
    <div class="dot" id="d2"></div>
    <div class="dot" id="d3"></div>
  </div>

  <!-- Step 1: API credentials -->
  <div class="step active" id="step1">
    <div class="step-title">🔑 API-данные Telegram</div>
    <label>API ID</label>
    <input type="number" id="api_id" placeholder="1234567" autocomplete="off">
    <label>API Hash</label>
    <input type="text" id="api_hash" placeholder="0abc123def456..." autocomplete="off">
    <p class="hint">Получи на <a href="https://my.telegram.org" target="_blank">my.telegram.org</a> → API development tools</p>

    <details id="proxy_details">
      <summary>Настройки прокси (если Telegram недоступен)</summary>
      <div class="proxy-fields">
        <label>Хост и порт</label>
        <div class="proxy-row">
          <input type="text" id="proxy_host" placeholder="127.0.0.1">
          <input type="number" id="proxy_port" placeholder="1080">
        </div>
        <label>Тип</label>
        <input type="text" id="proxy_type" placeholder="SOCKS5" value="SOCKS5">
        <label>Логин (необязательно)</label>
        <input type="text" id="proxy_user" placeholder="">
        <label>Пароль (необязательно)</label>
        <input type="password" id="proxy_pass" placeholder="">
      </div>
    </details>

    <div class="error" id="err1"></div>
    <button id="btn1" onclick="saveConfig()">Продолжить →</button>
  </div>

  <!-- Step 2: Phone + Code -->
  <div class="step" id="step2">
    <div class="step-title">📱 Вход в аккаунт</div>
    <label>Номер телефона</label>
    <input type="tel" id="phone" placeholder="+79001234567">
    <p class="hint">В международном формате, с символом +</p>

    <div id="code_block" style="display:none">
      <label>Код из Telegram</label>
      <input type="text" id="code" placeholder="12345" maxlength="10">
      <p class="hint">Проверь личные сообщения в Telegram</p>
    </div>

    <div class="error" id="err2"></div>
    <button id="btn2" onclick="phoneStep()">Получить код →</button>
  </div>

  <!-- Step 3: 2FA (if needed) -->
  <div class="step" id="step3">
    <div class="step-title">🔐 Двухфакторная аутентификация</div>
    <label>Облачный пароль Telegram</label>
    <input type="password" id="password" placeholder="••••••••">
    <div class="error" id="err3"></div>
    <button id="btn3" onclick="check2fa()">Подтвердить →</button>
  </div>

  <!-- Step 4: Done -->
  <div class="step" id="step4">
    <div class="done-wrap">
      <div class="done-icon">🎉</div>
      <div class="done-title">Готово!</div>
      <div class="done-sub">Kitsune запускается… можешь закрыть это окно</div>
      <div class="done-info" id="done_info"></div>
    </div>
  </div>
</div>

<script>
let codeSent = false;

function setDots(active) {
  for (let i = 1; i <= 3; i++) {
    const d = document.getElementById('d' + i);
    if (i < active) d.className = 'dot done';
    else if (i === active) d.className = 'dot active';
    else d.className = 'dot';
  }
}

function show(n) {
  document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
  document.getElementById('step' + n).classList.add('active');
  setDots(n);
}

function showErr(n, msg) {
  const el = document.getElementById('err' + n);
  el.textContent = msg;
  el.style.display = msg ? 'block' : 'none';
}

function setBtn(id, text, disabled) {
  const b = document.getElementById(id);
  b.textContent = text;
  b.disabled = disabled;
}

async function post(url, data) {
  const r = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  });
  return r.json();
}

async function saveConfig() {
  const api_id = document.getElementById('api_id').value.trim();
  const api_hash = document.getElementById('api_hash').value.trim();
  if (!api_id || !api_hash) { showErr(1, 'Заполни оба поля'); return; }
  const proxy_host = document.getElementById('proxy_host').value.trim();
  const proxy_port = document.getElementById('proxy_port').value.trim();
  const proxy_type = document.getElementById('proxy_type').value.trim();
  const proxy_user = document.getElementById('proxy_user').value.trim();
  const proxy_pass = document.getElementById('proxy_pass').value.trim();

  const payload = { api_id: parseInt(api_id), api_hash };
  if (proxy_host && proxy_port) {
    payload.proxy = { type: proxy_type || 'SOCKS5', host: proxy_host, port: parseInt(proxy_port) };
    if (proxy_user) payload.proxy.username = proxy_user;
    if (proxy_pass) payload.proxy.password = proxy_pass;
  }

  setBtn('btn1', 'Подключаемся…', true);
  const res = await post('/api/config', payload);
  setBtn('btn1', 'Продолжить →', false);
  if (res.ok) { showErr(1, ''); show(2); }
  else showErr(1, res.error || 'Ошибка');
}

async function phoneStep() {
  if (!codeSent) {
    const phone = document.getElementById('phone').value.trim();
    if (!phone) { showErr(2, 'Введи номер телефона'); return; }
    setBtn('btn2', 'Отправляем…', true);
    const res = await post('/api/sendcode', { phone });
    setBtn('btn2', 'Войти →', false);
    if (res.ok) {
      showErr(2, '');
      document.getElementById('code_block').style.display = 'block';
      document.getElementById('phone').disabled = true;
      codeSent = true;
    } else {
      showErr(2, res.error || 'Ошибка отправки кода');
    }
  } else {
    const code = document.getElementById('code').value.trim();
    if (!code) { showErr(2, 'Введи код'); return; }
    setBtn('btn2', 'Проверяем…', true);
    const res = await post('/api/signin', { code });
    setBtn('btn2', 'Войти →', false);
    if (res.ok) {
      showErr(2, '');
      show(4);
      document.getElementById('done_info').textContent = res.message || '';
    } else if (res.need_2fa) {
      showErr(2, '');
      show(3);
    } else {
      showErr(2, res.error || 'Неверный код');
    }
  }
}

async function check2fa() {
  const pwd = document.getElementById('password').value;
  if (!pwd) { showErr(3, 'Введи пароль'); return; }
  setBtn('btn3', 'Проверяем…', true);
  const res = await post('/api/2fa', { password: pwd });
  setBtn('btn3', 'Подтвердить →', false);
  if (res.ok) {
    showErr(3, '');
    show(4);
    document.getElementById('done_info').textContent = res.message || '';
  } else {
    showErr(3, res.error || 'Неверный пароль');
  }
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Setup server
# ---------------------------------------------------------------------------

class SetupServer:
    """
    Serves the web setup UI and drives the Telethon auth flow.
    Caller should await wait_done() — it resolves once the user is logged in.
    get_client() returns the connected, authorized KitsuneTelegramClient.
    """

    def __init__(
        self,
        save_config_fn: Callable[[dict], None],
        get_config_fn: Callable[[], dict],
    ) -> None:
        self._save_config = save_config_fn
        self._get_config = get_config_fn
        self._client: Any = None
        self._phone: str | None = None
        self._phone_hash: str | None = None
        self._done = asyncio.Event()
        self._runner: Any = None

    # ── Public ─────────────────────────────────────────────────────────────

    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_post("/api/config", self._api_config)
        app.router.add_post("/api/sendcode", self._api_sendcode)
        app.router.add_post("/api/signin", self._api_signin)
        app.router.add_post("/api/2fa", self._api_2fa)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()

        url = f"http://127.0.0.1:{port}"
        print(f"\n{'━' * 42}")
        print(f"  🌐  Открой в браузере: \033[1;36m{url}\033[0m")
        print(f"{'━' * 42}\n")
        try:
            webbrowser.open(url)
        except Exception:
            pass

    async def wait_done(self) -> None:
        await self._done.wait()
        if self._runner:
            await self._runner.cleanup()

    def get_client(self) -> Any:
        return self._client

    # ── Handlers ───────────────────────────────────────────────────────────

    async def _index(self, _: web.Request) -> web.Response:
        return web.Response(text=_HTML, content_type="text/html")

    async def _api_config(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            api_id   = int(data["api_id"])
            api_hash = str(data["api_hash"]).strip()
            if not api_id or not api_hash:
                return self._err("api_id и api_hash обязательны")

            # Persist config
            cfg = self._get_config()
            cfg["api_id"]   = api_id
            cfg["api_hash"] = api_hash
            if "proxy" in data and data["proxy"].get("host"):
                cfg["proxy"] = data["proxy"]
            self._save_config(cfg)

            # Build Telethon client
            from ..tl_cache import KitsuneTelegramClient
            from pathlib import Path

            DATA_DIR = Path.home() / ".kitsune"
            DATA_DIR.mkdir(parents=True, exist_ok=True)

            proxy = _build_proxy(cfg.get("proxy") or {})
            proxy_type = str((cfg.get("proxy") or {}).get("type", "")).upper()

            extra = {}
            if proxy_type == "MTPROTO":
                from telethon.network import connection as tl_conn
                extra["connection"] = tl_conn.ConnectionTcpMTProxyRandomizedIntermediate

            self._client = KitsuneTelegramClient(
                str(DATA_DIR / "kitsune"),
                api_id=api_id,
                api_hash=api_hash,
                connection_retries=5,
                retry_delay=3,
                proxy=proxy,
                **extra,
            )

            try:
                await asyncio.wait_for(self._client.connect(), timeout=20)
            except (TimeoutError, OSError, asyncio.TimeoutError) as exc:
                self._client = None
                return self._err(
                    f"Не удалось подключиться к Telegram. "
                    f"Настрой прокси и попробуй снова. ({exc})"
                )

            return web.json_response({"ok": True})
        except Exception as exc:
            logger.exception("setup: /api/config error")
            return self._err(str(exc))

    async def _api_sendcode(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            self._phone = data["phone"].strip()
            result = await self._client.send_code_request(self._phone)
            self._phone_hash = result.phone_code_hash
            return web.json_response({"ok": True})
        except Exception as exc:
            logger.exception("setup: /api/sendcode error")
            return self._err(str(exc))

    async def _api_signin(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            code = str(data["code"]).strip()
            from telethon.errors import SessionPasswordNeededError
            try:
                me = await self._client.sign_in(
                    self._phone, code, phone_code_hash=self._phone_hash
                )
                self._done.set()
                return web.json_response({
                    "ok": True,
                    "message": f"👤 {me.first_name}  |  id: {me.id}",
                })
            except SessionPasswordNeededError:
                return web.json_response({"ok": False, "need_2fa": True})
        except Exception as exc:
            logger.exception("setup: /api/signin error")
            return self._err(str(exc))

    async def _api_2fa(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            me = await self._client.sign_in(password=data["password"])
            self._done.set()
            return web.json_response({
                "ok": True,
                "message": f"👤 {me.first_name}  |  id: {me.id}",
            })
        except Exception as exc:
            logger.exception("setup: /api/2fa error")
            return self._err(str(exc))

    @staticmethod
    def _err(msg: str) -> web.Response:
        return web.json_response({"ok": False, "error": msg})


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build_proxy(proxy_cfg: dict) -> tuple | None:
    if not proxy_cfg.get("host") or not proxy_cfg.get("port"):
        return None
    ptype = str(proxy_cfg.get("type", "SOCKS5")).upper()
    # MTProto proxy — special Telegram protocol, no PySocks needed
    if ptype == "MTPROTO":
        secret = proxy_cfg.get("secret", "00000000000000000000000000000000")
        return (str(proxy_cfg["host"]), int(proxy_cfg["port"]), secret)
    # SOCKS4/5/HTTP
    try:
        import socks as _socks
        _map = {"SOCKS5": _socks.SOCKS5, "SOCKS4": _socks.SOCKS4, "HTTP": _socks.HTTP}
        pt = _map.get(ptype, _socks.SOCKS5)
        return (
            pt,
            str(proxy_cfg["host"]),
            int(proxy_cfg["port"]),
            True,
            proxy_cfg.get("username") or None,
            proxy_cfg.get("password") or None,
        )
    except ImportError:
        logger.warning("setup: PySocks not installed, proxy disabled")
        return None
