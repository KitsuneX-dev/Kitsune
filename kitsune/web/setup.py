"""
Kitsune Web Setup — first-run configuration interface.
Proxy injection pattern ported from Hikka: proxy/connection passed into
SetupServer constructor, used in _get_client() — same as Hikka's Web class.
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
  .steps-bar { display: flex; gap: 6px; margin-bottom: 28px; justify-content: center; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #2a2a4a; transition: background .3s; }
  .dot.active { background: #7c3aed; }
  .dot.done { background: #5b21b6; }
  .done-wrap { text-align: center; padding: 10px 0; }
  .done-icon { font-size: 3.5rem; margin-bottom: 12px; }
  .done-title { font-size: 1.2rem; font-weight: 700; color: #86efac; margin-bottom: 6px; }
  .done-sub { font-size: 0.85rem; color: #555; }
  .done-info { margin-top: 20px; padding: 12px 16px; background: #0d0d1a; border-radius: 10px; font-size: 0.83rem; color: #888; line-height: 1.8; text-align: left; }
  .proxy-toggle {
    margin-top: 18px; font-size: 0.82rem; color: #7c3aed;
    cursor: pointer; user-select: none; display: inline-flex; align-items: center; gap: 5px;
  }
  .proxy-toggle:hover { color: #a78bfa; }
  .proxy-block {
    display: none; margin-top: 12px; padding: 14px;
    background: #0d0d1a; border: 1px solid #7c3aed33; border-radius: 10px;
  }
  .proxy-block.open { display: block; }
  .proxy-type-row { display: flex; gap: 8px; margin-bottom: 10px; }
  .proxy-type-btn {
    flex: 1; padding: 7px; margin-top: 0;
    background: #1a1a30; border: 1px solid #7c3aed44;
    border-radius: 8px; color: #a78bfa; font-size: 0.8rem;
    font-weight: 600; cursor: pointer; transition: all .2s;
  }
  .proxy-type-btn.selected { background: #7c3aed; border-color: #7c3aed; color: #fff; }
  .proxy-row { display: flex; gap: 8px; }
  .proxy-row input:first-child { flex: 3; }
  .proxy-row input:last-child { flex: 1; }
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

  <!-- Step 1: API + Phone -->
  <div class="step active" id="step1">
    <div class="step-title">🔑 API-данные Telegram</div>
    <label>API ID</label>
    <input type="number" id="api_id" placeholder="1234567" autocomplete="off">
    <label>API Hash</label>
    <input type="text" id="api_hash" placeholder="0abc123def456..." autocomplete="off">
    <p class="hint">Получи на <a href="https://my.telegram.org" target="_blank">my.telegram.org</a> → API development tools</p>
    <label>Номер телефона</label>
    <input type="tel" id="phone" placeholder="+79001234567">
    <p class="hint">В международном формате, с символом +</p>

    <span class="proxy-toggle" onclick="toggleProxy()">▶ Настройки прокси (если Telegram недоступен)</span>
    <div class="proxy-block" id="proxy_block">
      <div class="proxy-type-row">
        <button class="proxy-type-btn selected" id="pt_MTPROTO" onclick="selectProxyType('MTPROTO')">MTProto</button>
        <button class="proxy-type-btn" id="pt_SOCKS5" onclick="selectProxyType('SOCKS5')">SOCKS5</button>
        <button class="proxy-type-btn" id="pt_HTTP" onclick="selectProxyType('HTTP')">HTTP</button>
      </div>
      <div class="proxy-row">
        <input type="text" id="proxy_host" placeholder="Хост (напр. tg.vpnspacev.com)">
        <input type="number" id="proxy_port" placeholder="443">
      </div>
      <div id="proxy_secret_wrap">
        <label>Секрет (только для MTProto)</label>
        <input type="text" id="proxy_secret" placeholder="bc184fc14b62b9b1dc5f34edf9476421">
      </div>
      <div id="proxy_auth_wrap" style="display:none">
        <label>Логин (необязательно)</label>
        <input type="text" id="proxy_user" placeholder="username">
        <label>Пароль (необязательно)</label>
        <input type="password" id="proxy_pass" placeholder="••••••••">
      </div>
    </div>

    <div class="error" id="err1"></div>
    <button id="btn1" onclick="sendCode()">Получить код →</button>
  </div>

  <!-- Step 2: Code -->
  <div class="step" id="step2">
    <div class="step-title">📱 Код подтверждения</div>
    <label>Код из Telegram</label>
    <input type="text" id="code" placeholder="12345" maxlength="10" autocomplete="off">
    <p class="hint">Проверь личные сообщения в Telegram</p>
    <div class="error" id="err2"></div>
    <button id="btn2" onclick="signIn()">Войти →</button>
  </div>

  <!-- Step 3: 2FA -->
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
let proxyType = 'MTPROTO';

function toggleProxy() {
  const block = document.getElementById('proxy_block');
  const toggle = document.querySelector('.proxy-toggle');
  const open = block.classList.toggle('open');
  toggle.textContent = (open ? '▼' : '▶') + ' Настройки прокси (если Telegram недоступен)';
}

function selectProxyType(type) {
  proxyType = type;
  ['MTPROTO','SOCKS5','HTTP'].forEach(t => {
    document.getElementById('pt_' + t).classList.toggle('selected', t === type);
  });
  document.getElementById('proxy_secret_wrap').style.display = type === 'MTPROTO' ? 'block' : 'none';
  document.getElementById('proxy_auth_wrap').style.display  = type !== 'MTPROTO' ? 'block' : 'none';
}

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

function getProxy() {
  const host = document.getElementById('proxy_host').value.trim();
  const port = document.getElementById('proxy_port').value.trim();
  if (!host || !port) return null;
  const p = { type: proxyType, host, port: parseInt(port) };
  if (proxyType === 'MTPROTO') {
    p.secret = document.getElementById('proxy_secret').value.trim();
  } else {
    p.username = document.getElementById('proxy_user').value.trim() || null;
    p.password = document.getElementById('proxy_pass').value || null;
  }
  return p;
}

async function sendCode() {
  const api_id = document.getElementById('api_id').value.trim();
  const api_hash = document.getElementById('api_hash').value.trim();
  const phone = document.getElementById('phone').value.trim();
  if (!api_id || !api_hash) { showErr(1, 'Заполни API ID и API Hash'); return; }
  if (!phone) { showErr(1, 'Введи номер телефона'); return; }
  setBtn('btn1', 'Отправляем код…', true);
  const proxy = getProxy();
  const res = await post('/api/sendcode', { api_id: parseInt(api_id), api_hash, phone, proxy });
  setBtn('btn1', 'Получить код →', false);
  if (res.ok) { showErr(1, ''); show(2); }
  else showErr(1, res.error || 'Ошибка');
}

async function signIn() {
  const code = document.getElementById('code').value.trim();
  if (!code) { showErr(2, 'Введи код'); return; }
  setBtn('btn2', 'Проверяем…', true);
  const res = await post('/api/signin', { code });
  setBtn('btn2', 'Войти →', false);
  if (res.ok) { showErr(2, ''); show(4); document.getElementById('done_info').textContent = res.message || ''; }
  else if (res.need_2fa) { showErr(2, ''); show(3); }
  else showErr(2, res.error || 'Неверный код');
}

async function check2fa() {
  const pwd = document.getElementById('password').value;
  if (!pwd) { showErr(3, 'Введи пароль'); return; }
  setBtn('btn3', 'Проверяем…', true);
  const res = await post('/api/2fa', { password: pwd });
  setBtn('btn3', 'Подтвердить →', false);
  if (res.ok) { showErr(3, ''); show(4); document.getElementById('done_info').textContent = res.message || ''; }
  else showErr(3, res.error || 'Неверный пароль');
}
</script>
</body>
</html>"""


class SetupServer:
    """
    Hikka-style: proxy and connection are injected from outside (main.py),
    exactly like Hikka's Web(proxy=..., connection=...) constructor.
    _get_client() uses self.proxy / self.connection — no config re-reading.
    """

    def __init__(
        self,
        save_config_fn: Callable,
        get_config_fn: Callable,
        proxy: Any = None,
        connection: Any = None,
    ) -> None:
        self._save_config = save_config_fn
        self._get_config  = get_config_fn
        # Injected from main.py — same pattern as Hikka
        self.proxy      = proxy
        self.connection = connection

        self._api_id:   int       = 0
        self._api_hash: str       = ""
        self._client:   Any       = None
        self._phone:    str | None = None
        self._phone_hash: str | None = None
        self._done   = asyncio.Event()
        self._runner: Any = None

    # ── Hikka pattern: single place that builds the Telethon client ───────────
    def _get_client(self) -> Any:
        from ..tl_cache import KitsuneTelegramClient
        from telethon.sessions import MemorySession

        kwargs: dict = dict(
            api_id=self._api_id,
            api_hash=self._api_hash,
            connection_retries=None,
            device_model="Kitsune Userbot",
            system_version="Windows 10",
            app_version="1.0.0",
            lang_code="en",
            system_lang_code="en-US",
        )
        if self.proxy is not None:
            kwargs["proxy"] = self.proxy
        if self.connection is not None:
            kwargs["connection"] = self.connection

        logger.info(
            "setup: _get_client proxy=%s connection=%s",
            self.proxy, self.connection,
        )
        return KitsuneTelegramClient(MemorySession(), **kwargs)

    # ── Web server ────────────────────────────────────────────────────────────
    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        app = web.Application()
        app.router.add_get("/",              self._index)
        app.router.add_post("/api/sendcode", self._api_sendcode)
        app.router.add_post("/api/signin",   self._api_signin)
        app.router.add_post("/api/2fa",      self._api_2fa)
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

    async def _index(self, _: web.Request) -> web.Response:
        return web.Response(text=_HTML, content_type="text/html")

    # ── /api/sendcode ─────────────────────────────────────────────────────────
    async def _api_sendcode(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            self._api_id   = int(data["api_id"])
            self._api_hash = str(data["api_hash"]).strip()
            self._phone    = str(data["phone"]).strip()

            # Save API credentials
            cfg = self._get_config()
            cfg["api_id"]   = self._api_id
            cfg["api_hash"] = self._api_hash

            # If the user filled proxy in the web form — override injected proxy
            form_proxy = data.get("proxy")
            if form_proxy and form_proxy.get("host"):
                ptype = str(form_proxy.get("type", "MTPROTO")).upper()
                host  = form_proxy["host"]
                port  = int(form_proxy["port"])
                if ptype == "MTPROTO":
                    from telethon.network.connection import ConnectionTcpMTProxyRandomizedIntermediate
                    self.proxy      = (host, port, form_proxy.get("secret", ""))
                    self.connection = ConnectionTcpMTProxyRandomizedIntermediate
                    logger.info("setup: form MTProto proxy → %s:%s", host, port)
                elif ptype == "SOCKS5":
                    import socks
                    self.proxy      = (socks.SOCKS5, host, port, True,
                                       form_proxy.get("username") or None,
                                       form_proxy.get("password") or None)
                    self.connection = None
                    logger.info("setup: form SOCKS5 proxy → %s:%s", host, port)
                elif ptype == "HTTP":
                    import socks
                    self.proxy      = (socks.HTTP, host, port, True,
                                       form_proxy.get("username") or None,
                                       form_proxy.get("password") or None)
                    self.connection = None
                    logger.info("setup: form HTTP proxy → %s:%s", host, port)
                cfg["proxy"] = form_proxy

            self._save_config(cfg)

            # Build client with injected (or overridden) proxy
            self._client = self._get_client()
            await asyncio.wait_for(self._client.connect(), timeout=30)
            result = await self._client.send_code_request(self._phone)
            self._phone_hash = result.phone_code_hash
            logger.info("setup: code sent to %s", self._phone)

            return web.json_response({"ok": True})

        except asyncio.TimeoutError:
            self._client = None
            return self._err("Не удалось подключиться к Telegram. Настрой прокси и попробуй снова.")
        except Exception as exc:
            logger.exception("setup: /api/sendcode error")
            return self._err(str(exc))

    # ── /api/signin ───────────────────────────────────────────────────────────
    async def _api_signin(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            code = str(data["code"]).strip()
            from telethon.errors import SessionPasswordNeededError
            try:
                me = await self._client.sign_in(
                    self._phone, code, phone_code_hash=self._phone_hash
                )
                await self._save_session(me)
                self._done.set()
                return web.json_response({"ok": True, "message": f"👤 {me.first_name}  |  id: {me.id}"})
            except SessionPasswordNeededError:
                return web.json_response({"ok": False, "need_2fa": True})
        except Exception as exc:
            logger.exception("setup: /api/signin error")
            return self._err(str(exc))

    # ── /api/2fa ──────────────────────────────────────────────────────────────
    async def _api_2fa(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            me = await self._client.sign_in(password=data["password"])
            await self._save_session(me)
            self._done.set()
            return web.json_response({"ok": True, "message": f"👤 {me.first_name}  |  id: {me.id}"})
        except Exception as exc:
            logger.exception("setup: /api/2fa error")
            return self._err(str(exc))

    # ── Session save — same as Hikka's save_client_session ───────────────────
    async def _save_session(self, me: Any) -> None:
        from telethon.sessions import SQLiteSession
        from pathlib import Path
        DATA_DIR = Path.home() / ".kitsune"
        session = SQLiteSession(str(DATA_DIR / "kitsune"))
        session.set_dc(
            self._client.session.dc_id,
            self._client.session.server_address,
            self._client.session.port,
        )
        session.auth_key = self._client.session.auth_key
        session.save()
        self._client.session = session
        self._client.tg_id   = me.id
        self._client.tg_me   = me
        logger.info("setup: session saved for %s (id=%d)", me.first_name, me.id)

    @staticmethod
    def _err(msg: str) -> web.Response:
        return web.json_response({"ok": False, "error": msg})
