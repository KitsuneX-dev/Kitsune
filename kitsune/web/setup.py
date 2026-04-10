
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
  background:
  color:
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background-image:
    linear-gradient(rgba(120,80,255,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(120,80,255,0.03) 1px, transparent 1px);
  background-size: 40px 40px;
}

.card {
  width: 100%;
  max-width: 440px;
  background:
  border: 1px solid rgba(140,90,255,0.2);
  border-radius: 20px;
  padding: 40px 36px;
  box-shadow: 0 0 60px rgba(120,60,255,0.12), 0 0 120px rgba(120,60,255,0.05);
}

.logo { text-align: center; font-size: 3rem; margin-bottom: 8px; }

h1 {
  text-align: center;
  font-size: 1.4rem;
  font-weight: 700;
  color:
  margin-bottom: 4px;
  letter-spacing: 0.5px;
}

.sub {
  text-align: center;
  font-size: 0.8rem;
  color:
  margin-bottom: 28px;
}

.steps-bar {
  display: flex;
  gap: 6px;
  justify-content: center;
  margin-bottom: 28px;
}

.dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background:
  transition: all .3s;
}
.dot.active { background:
.dot.done   { background:

.step { display: none; animation: fadeIn .25s ease; }
.step.active { display: block; }

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

.step-title {
  font-size: 0.95rem;
  font-weight: 600;
  color:
  margin-bottom: 20px;
}

label {
  display: block;
  font-size: 0.78rem;
  color:
  margin-bottom: 5px;
  margin-top: 14px;
}

input {
  width: 100%;
  padding: 11px 14px;
  background:
  border: 1px solid rgba(140,90,255,0.2);
  border-radius: 9px;
  color:
  font-size: 0.9rem;
  outline: none;
  transition: border .2s, box-shadow .2s;
}

input:focus {
  border-color:
  box-shadow: 0 0 0 3px rgba(128,80,224,0.15);
}

input::placeholder { color:

.hint {
  font-size: 0.75rem;
  color:
  margin-top: 6px;
}
.hint a { color:
.hint a:hover { text-decoration: underline; }

button {
  width: 100%;
  margin-top: 22px;
  padding: 13px;
  background: linear-gradient(135deg,
  border: none;
  border-radius: 10px;
  color:
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  letter-spacing: 0.3px;
  transition: opacity .2s, transform .1s, box-shadow .2s;
  box-shadow: 0 4px 20px rgba(120,60,255,0.3);
}

button:hover { opacity: .9; box-shadow: 0 4px 28px rgba(120,60,255,0.5); }
button:active { transform: scale(.98); }
button:disabled { opacity: .35; cursor: not-allowed; box-shadow: none; }

.error {
  display: none;
  margin-top: 14px;
  padding: 10px 14px;
  background: rgba(200,50,80,0.1);
  border: 1px solid rgba(200,50,80,0.25);
  border-radius: 8px;
  font-size: 0.82rem;
  color:
}

.done-wrap { text-align: center; padding: 10px 0; }
.done-icon { font-size: 3.5rem; margin-bottom: 14px; }
.done-title {
  font-size: 1.25rem;
  font-weight: 700;
  color:
  margin-bottom: 8px;
}
.done-sub {
  font-size: 0.85rem;
  color:
}
.done-info {
  margin-top: 18px;
  padding: 12px 16px;
  background: rgba(120,60,255,0.08);
  border: 1px solid rgba(120,60,255,0.2);
  border-radius: 10px;
  font-size: 0.85rem;
  color:
}
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
    <div class="error" id="err1"></div>
    <button id="btn1" onclick="sendCode()">Получить код →</button>
  </div>

  <div class="step" id="step2">
    <div class="step-title">📱 Код подтверждения</div>
    <label>Код из Telegram</label>
    <input type="text" id="code" placeholder="12345" maxlength="10" autocomplete="off">
    <p class="hint">Проверь личные сообщения в Telegram</p>
    <div class="error" id="err2"></div>
    <button id="btn2" onclick="signIn()">Войти →</button>
  </div>

  <div class="step" id="step3">
    <div class="step-title">🔐 Двухфакторная аутентификация</div>
    <label>Облачный пароль Telegram</label>
    <input type="password" id="password" placeholder="••••••••">
    <div class="error" id="err3"></div>
    <button id="btn3" onclick="check2fa()">Подтвердить →</button>
  </div>

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
function setDots(active) {
  for (let i = 1; i <= 3; i++) {
    const d = document.getElementById('d' + i);
    if (i < active)      d.className = 'dot done';
    else if (i === active) d.className = 'dot active';
    else                   d.className = 'dot';
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
async function sendCode() {
  const api_id   = document.getElementById('api_id').value.trim();
  const api_hash = document.getElementById('api_hash').value.trim();
  const phone    = document.getElementById('phone').value.trim();
  if (!api_id || !api_hash) { showErr(1, 'Заполни API ID и API Hash'); return; }
  if (!phone) { showErr(1, 'Введи номер телефона'); return; }
  setBtn('btn1', 'Отправляем код…', true);
  const res = await post('/api/sendcode', { api_id: parseInt(api_id), api_hash, phone });
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
    def __init__(self, save_config_fn: Callable, get_config_fn: Callable) -> None:
        self._save_config = save_config_fn
        self._get_config = get_config_fn
        self._client: Any = None
        self._phone: str | None = None
        self._phone_hash: str | None = None
        self._done = asyncio.Event()
        self._runner: Any = None

    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        app = web.Application()
        app.router.add_get("/", self._index)
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

    async def _index(self, _: web.Request) -> web.Response:
        return web.Response(text=_HTML, content_type="text/html")

    async def _api_sendcode(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            api_id   = int(data["api_id"])
            api_hash = str(data["api_hash"]).strip()
            self._phone = str(data["phone"]).strip()

            cfg = self._get_config()
            cfg["api_id"]   = api_id
            cfg["api_hash"] = api_hash
            self._save_config(cfg)

            from ..tl_cache import KitsuneTelegramClient
            from telethon.sessions import MemorySession
            from pathlib import Path

            DATA_DIR = Path.home() / ".kitsune"
            DATA_DIR.mkdir(parents=True, exist_ok=True)

            proxy_cfg = cfg.get("proxy") or {}
            proxy = None
            extra: dict = {}
            if proxy_cfg.get("host") and proxy_cfg.get("port"):
                ptype = str(proxy_cfg.get("type", "SOCKS5")).upper()
                if ptype == "MTPROTO":
                    secret = proxy_cfg.get("secret", "00000000000000000000000000000000")
                    proxy = (str(proxy_cfg["host"]), int(proxy_cfg["port"]), secret)
                    from telethon.network import connection as tl_conn
                    extra["connection"] = tl_conn.ConnectionTcpMTProxyRandomizedIntermediate
                    logger.info("setup: using MTProto proxy → %s:%s", proxy_cfg["host"], proxy_cfg["port"])
                else:
                    try:
                        import socks as _socks
                        _type_map = {
                            "SOCKS5": _socks.SOCKS5,
                            "SOCKS4": _socks.SOCKS4,
                            "HTTP":   _socks.HTTP,
                        }
                        proxy = (
                            _type_map.get(ptype, _socks.SOCKS5),
                            str(proxy_cfg["host"]),
                            int(proxy_cfg["port"]),
                            True,
                            proxy_cfg.get("username") or None,
                            proxy_cfg.get("password") or None,
                        )
                        logger.info("setup: using %s proxy → %s:%s", ptype, proxy_cfg["host"], proxy_cfg["port"])
                    except ImportError:
                        logger.warning("setup: PySocks not installed, proxy disabled")

            self._client = KitsuneTelegramClient(
                MemorySession(),
                api_id=api_id,
                api_hash=api_hash,
                connection_retries=5,
                retry_delay=3,
                device_model="Kitsune Userbot",
                system_version="Windows 10",
                app_version="1.0.0",
                lang_code="en",
                system_lang_code="en-US",
                proxy=proxy,
                **extra,
            )

            await asyncio.wait_for(self._client.connect(), timeout=30)
            result = await self._client.send_code_request(self._phone)
            self._phone_hash = result.phone_code_hash

            return web.json_response({"ok": True})
        except asyncio.TimeoutError:
            self._client = None
            return self._err("Не удалось подключиться к Telegram. Проверь интернет-соединение.")
        except Exception as exc:
            logger.exception("setup: /api/sendcode error")
            return self._err(str(exc))

    async def _api_signin(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            code = str(data["code"]).strip()
            from telethon.errors import SessionPasswordNeededError
            from telethon.sessions import SQLiteSession
            from pathlib import Path
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

    async def _api_2fa(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            password = str(data.get("password", "")).strip()
            if not password:
                return self._err("Пароль не может быть пустым")

            from telethon.errors import PasswordHashInvalidError, FloodWaitError

            try:
                me = await self._client.sign_in(password=password)
            except PasswordHashInvalidError:
                return web.json_response({"ok": False, "error": "Неверный пароль. Попробуй ещё раз.", "wrong_password": True})
            except FloodWaitError as e:
                return web.json_response({"ok": False, "error": f"Слишком много попыток. Подожди {e.seconds} секунд.", "flood": True})

            await self._save_session(me)
            self._done.set()
            return web.json_response({"ok": True, "message": f"👤 {me.first_name}  |  id: {me.id}"})
        except Exception as exc:
            logger.exception("setup: /api/2fa error")
            return self._err(str(exc))

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
        self._client.tg_id = me.id
        self._client.tg_me = me

        try:
            from ..session_enc import encrypt_session_file
            encrypt_session_file()
        except Exception:
            logger.exception("setup: failed to encrypt session after save")

    @staticmethod
    def _err(msg: str) -> web.Response:
        return web.json_response({"ok": False, "error": msg})
