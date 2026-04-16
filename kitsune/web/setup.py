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
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>🦊 Kitsune Setup</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:opsz,wght@9..40,300;9..40,500;9..40,700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
:root{
  --bg:
  --bd:rgba(255,255,255,0.07);--bd2:rgba(255,255,255,0.13);
  --tx:
  --fox:
  --green:
  --red:
  --mono:'Space Mono',monospace;--body:'DM Sans',sans-serif;
  --r:16px;--ease:.18s cubic-bezier(.4,0,.2,1);
}
html,body{min-height:100%;height:100%}
body{
  font-family:var(--body);background:var(--bg);color:var(--tx);
  display:flex;align-items:center;justify-content:center;
  padding:20px;overflow-x:hidden;
  background-image:
    radial-gradient(ellipse 70% 50% at 10% 0%,rgba(255,107,53,0.09) 0%,transparent 55%),
    radial-gradient(ellipse 50% 40% at 90% 100%,rgba(74,158,255,0.05) 0%,transparent 55%);
}
.card{
  width:100%;max-width:420px;
  background:var(--s1);border:1px solid var(--bd2);border-radius:22px;
  padding:36px 32px;
  box-shadow:0 0 60px rgba(255,107,53,0.07),0 24px 60px rgba(0,0,0,0.5);
}
@media(max-width:480px){.card{padding:28px 20px;border-radius:18px}}
.logo{text-align:center;font-size:3rem;margin-bottom:6px;filter:drop-shadow(0 0 20px rgba(255,107,53,0.4))}
h1{text-align:center;font-family:var(--mono);font-size:1.15rem;font-weight:700;color:var(--tx);margin-bottom:4px;letter-spacing:-.01em}
.sub{text-align:center;font-size:.74rem;color:var(--mu);margin-bottom:26px;font-family:var(--mono)}
.steps-bar{display:flex;gap:8px;justify-content:center;margin-bottom:28px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--bd2);transition:all .3s}
.dot.active{background:var(--fox);box-shadow:0 0 10px rgba(255,107,53,0.5);transform:scale(1.2)}
.dot.done{background:var(--green);box-shadow:0 0 8px rgba(61,255,170,0.4)}
.step{display:none;animation:fi .22s ease both}
.step.active{display:block}
@keyframes fi{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.step-title{font-size:.9rem;font-weight:700;color:var(--tx);margin-bottom:18px;font-family:var(--mono)}
label{display:block;font-size:.72rem;color:var(--mu2);margin-bottom:5px;margin-top:14px;letter-spacing:.04em;text-transform:uppercase}
input{
  width:100%;padding:11px 14px;
  background:var(--s2);border:1px solid var(--bd2);border-radius:10px;
  color:var(--tx);font-size:.88rem;font-family:var(--mono);
  outline:none;transition:border-color var(--ease),box-shadow var(--ease);
}
input:focus{border-color:rgba(255,107,53,0.5);box-shadow:0 0 0 3px rgba(255,107,53,0.12)}
input::placeholder{color:var(--mu)}
.hint{font-size:.72rem;color:var(--mu);margin-top:7px;line-height:1.4}
.hint a{color:var(--fox2);text-decoration:none}
.hint a:hover{text-decoration:underline}
button{
  width:100%;margin-top:22px;padding:13px;
  background:linear-gradient(135deg,
  border:none;border-radius:11px;
  color:
  cursor:pointer;letter-spacing:.2px;
  transition:filter var(--ease),transform .1s,box-shadow var(--ease);
  box-shadow:0 4px 20px rgba(255,107,53,0.35);
}
button:hover{filter:brightness(1.08);box-shadow:0 4px 28px rgba(255,107,53,0.5)}
button:active{transform:scale(.98)}
button:disabled{opacity:.35;cursor:not-allowed;box-shadow:none;filter:none}
.error{
  display:none;margin-top:13px;padding:10px 14px;
  background:rgba(255,74,107,0.1);border:1px solid rgba(255,74,107,0.25);
  border-radius:9px;font-size:.8rem;color:
}
.done-wrap{text-align:center;padding:8px 0}
.done-icon{font-size:3.5rem;margin-bottom:14px;filter:drop-shadow(0 0 20px rgba(61,255,170,0.5))}
.done-title{font-family:var(--mono);font-size:1.15rem;font-weight:700;color:var(--green);margin-bottom:8px}
.done-sub{font-size:.84rem;color:var(--mu2);line-height:1.5}
.done-info{
  margin-top:18px;padding:12px 16px;
  background:rgba(255,107,53,0.08);border:1px solid rgba(255,107,53,0.2);
  border-radius:11px;font-size:.82rem;color:var(--fox2);font-family:var(--mono);
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
    <input type="text" id="code" placeholder="12345" maxlength="10" autocomplete="one-time-code">
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
      <div class="done-sub">Kitsune запускается…<br>можешь закрыть это окно</div>
      <div class="done-info" id="done_info"></div>
    </div>
  </div>
</div>

<script>
function setDots(a){
  for(let i=1;i<=3;i++){
    const d=document.getElementById('d'+i);
    d.className='dot'+(i<a?' done':i===a?' active':'');
  }
}
function show(n){
  document.querySelectorAll('.step').forEach(s=>s.classList.remove('active'));
  document.getElementById('step'+n).classList.add('active');
  setDots(n);
}
function showErr(n,msg){
  const el=document.getElementById('err'+n);
  el.textContent=msg;el.style.display=msg?'block':'none';
}
function setBtn(id,text,disabled){
  const b=document.getElementById(id);b.textContent=text;b.disabled=disabled;
}
async function post(url,data){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  return r.json();
}
async function sendCode(){
  const api_id=document.getElementById('api_id').value.trim();
  const api_hash=document.getElementById('api_hash').value.trim();
  const phone=document.getElementById('phone').value.trim();
  if(!api_id||!api_hash){showErr(1,'Заполни API ID и API Hash');return;}
  if(!phone){showErr(1,'Введи номер телефона');return;}
  setBtn('btn1','Отправляем код…',true);
  const res=await post('/api/sendcode',{api_id:parseInt(api_id),api_hash,phone});
  setBtn('btn1','Получить код →',false);
  if(res.ok){showErr(1,'');show(2);}else showErr(1,res.error||'Ошибка');
}
async function signIn(){
  const code=document.getElementById('code').value.trim();
  if(!code){showErr(2,'Введи код');return;}
  setBtn('btn2','Проверяем…',true);
  const res=await post('/api/signin',{code});
  setBtn('btn2','Войти →',false);
  if(res.ok){showErr(2,'');show(4);document.getElementById('done_info').textContent=res.message||'';}
  else if(res.need_2fa){showErr(2,'');show(3);}
  else showErr(2,res.error||'Неверный код');
}
async function check2fa(){
  const pwd=document.getElementById('password').value;
  if(!pwd){showErr(3,'Введи пароль');return;}
  setBtn('btn3','Проверяем…',true);
  const res=await post('/api/2fa',{password:pwd});
  setBtn('btn3','Подтвердить →',false);
  if(res.ok){showErr(3,'');show(4);document.getElementById('done_info').textContent=res.message||'';}
  else showErr(3,res.error||'Неверный пароль');
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

        import os as _os
        is_termux = bool(_os.environ.get("PREFIX", "").find("com.termux") != -1)

        lan_url = url
        if is_termux:
            try:
                import socket as _socket
                with _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM) as _s:
                    _s.connect(("8.8.8.8", 80))
                    _lan_ip = _s.getsockname()[0]
                lan_url = f"http://{_lan_ip}:{port}"
            except Exception:
                pass

        print(f"\n{'━' * 42}")
        if is_termux:
            print(f"  🌐  Открой в браузере на телефоне:")
            print(f"      \033[1;36m{lan_url}\033[0m")
            print(f"  💡  Или на ПК в локальной сети: {lan_url}")
        else:
            print(f"  🌐  Открой в браузере: \033[1;36m{url}\033[0m")
        print(f"{'━' * 42}\n")

        if not is_termux:
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
