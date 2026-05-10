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

  --bg:#0d0d0f;--s1:#141418;--s2:#1c1c22;

  --bd:rgba(255,255,255,0.07);--bd2:rgba(255,255,255,0.13);

  --tx:#e8e8ec;--mu:rgba(255,255,255,0.35);--mu2:rgba(255,255,255,0.58);

  --fox:#ff6b35;--fox2:#ff8c5a;

  --green:#3dffaa;--red:#ff4a6b;

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

  background:linear-gradient(135deg,#ff6b35,#ff4a6b);

  border:none;border-radius:11px;

  color:#fff;font-family:var(--body);font-size:.9rem;font-weight:700;

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

  <h1 id="setup_title">Kitsune Userbot</h1>

  <p class="sub" id="setup_sub">by Yushi · первоначальная настройка</p>

  <div class="steps-bar">

    <div class="dot active" id="d1"></div>

    <div class="dot" id="d2"></div>

    <div class="dot" id="d3"></div>

  </div>

  <div class="step active" id="step1">

    <div class="step-title" id="step1_title">🔑 API-данные Telegram</div>

    <div id="api_block">

    <label>API ID</label>

    <input type="number" id="api_id" placeholder="1234567" autocomplete="off">

    <label>API Hash</label>

    <input type="text" id="api_hash" placeholder="0abc123def456..." autocomplete="off">

    <p class="hint">Получи на <a href="https://my.telegram.org" target="_blank">my.telegram.org</a> → API development tools</p>

    </div>

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

let HYDRO_ONLY = false;

// Спрашиваем у бэка режим, ещё до взаимодействия с пользователем.
(async()=>{
  try{
    const r = await fetch('/api/mode');
    const j = await r.json();
    HYDRO_ONLY = !!(j && j.hydrogram_only);
    if(HYDRO_ONLY){
      // Меняем шапку и прячем поля api_id/api_hash —
      // в этом режиме они уже сохранены в config.toml.
      document.getElementById('setup_title').textContent = 'Kitsune · повторная регистрация';
      document.getElementById('setup_sub').textContent = 'Только Hydrogram-сессия (предыдущая истекла)';
      document.getElementById('step1_title').textContent = '🔁 Повторная регистрация Hydrogram';
      const apib = document.getElementById('api_block');
      if(apib){ apib.style.display = 'none'; }
    }
  }catch(_){ /* offline / 404 → считаем что обычный режим */ }
})();

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

  const phone=document.getElementById('phone').value.trim();

  if(!phone){showErr(1,'Введи номер телефона');return;}

  let payload;

  if(HYDRO_ONLY){

    payload = {phone};

  } else {

    const api_id=document.getElementById('api_id').value.trim();
    const api_hash=document.getElementById('api_hash').value.trim();
    if(!api_id||!api_hash){showErr(1,'Заполни API ID и API Hash');return;}
    payload = {api_id:parseInt(api_id), api_hash, phone};

  }

  setBtn('btn1','Отправляем код…',true);

  const res=await post('/api/sendcode',payload);

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

    def __init__(
        self,
        save_config_fn: Callable,
        get_config_fn: Callable,
        hydrogram_only: bool = False,
    ) -> None:

        self._save_config = save_config_fn

        self._get_config = get_config_fn

        self._client: Any = None

        self._phone: str | None = None

        self._phone_hash: str | None = None

        self._last_code: str | None = None

        self._last_password: str | None = None

        self._done = asyncio.Event()

        self._runner: Any = None

        # Если True — мы НЕ создаём Telethon-сессию заново, а только
        # проводим заново авторизацию для Hydrogram (после AuthKeyUnregistered).
        self._hydrogram_only: bool = bool(hydrogram_only)

        # Hydrogram-клиент, который живёт всё время повторной регистрации
        # (нужен, чтобы send_code → sign_in использовали один и тот же auth_key).
        self._hydro_client: Any = None

        self._hydro_phone_code_hash: str | None = None

        self._hydrogram_success: bool = False

    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:

        app = web.Application()

        app.router.add_get("/", self._index)

        app.router.add_post("/api/sendcode", self._api_sendcode)

        app.router.add_post("/api/signin", self._api_signin)

        app.router.add_post("/api/2fa", self._api_2fa)

        # Эндпоинт чтобы фронт понял в каком режиме работает мастер.
        app.router.add_get("/api/mode", self._api_mode)

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

            print(f"  🌐  Открой в браузере: \033[1;36m{url}\033[0m для регистрации")

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

    async def _api_mode(self, _: web.Request) -> web.Response:

        # Фронт спрашивает: это первичная установка или повторная только для Hydrogram.
        cfg = self._get_config() or {}

        return web.json_response({

            "hydrogram_only": bool(self._hydrogram_only),

            # В режиме hydrogram_only api_id/api_hash уже сохранены и не нужны от пользователя.
            "api_id": cfg.get("api_id") if self._hydrogram_only else None,

            "api_hash": cfg.get("api_hash") if self._hydrogram_only else None,

        })

    async def _api_sendcode(self, request: web.Request) -> web.Response:

        # Вторая ветка — только для Hydrogram, без перерегистрации Telethon.
        if self._hydrogram_only:

            return await self._api_sendcode_hydrogram(request)

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

                try:

                    import python_socks              

                    _has_python_socks = True

                except ImportError:

                    _has_python_socks = False

                    logger.warning(

                        "setup: python-socks не установлен — Telethon проигнорирует прокси. "

                        "Пытаюсь установить автоматически…"

                    )

                    try:

                        import sys as _sys, subprocess as _sp

                        _sp.check_call(

                            [_sys.executable, "-m", "pip", "install", "--quiet",

                             "--disable-pip-version-check", "--no-warn-script-location",

                             "python-socks[asyncio]>=2.4.4"]

                        )

                        import importlib

                        importlib.invalidate_caches()

                        import python_socks              

                        _has_python_socks = True

                        logger.info("setup: python-socks[asyncio] установлен в рантайме")

                    except Exception as _exc:

                        logger.error(

                            "setup: не удалось установить python-socks: %s. "

                            "Прокси будет отключён.", _exc,

                        )

                if not _has_python_socks:

                    pass                         

                elif ptype == "MTPROTO":

                    secret = proxy_cfg.get("secret", "00000000000000000000000000000000")

                    try:

                        from ..rkn_bypass import get_mtproto_connection_class, normalize_secret

                        secret = normalize_secret(str(secret))

                        conn_cls = get_mtproto_connection_class(secret)

                    except Exception:

                        conn_cls = None

                    proxy = (str(proxy_cfg["host"]), int(proxy_cfg["port"]), secret)

                    if conn_cls is not None:

                        extra["connection"] = conn_cls

                    logger.info("setup: using MTProto proxy → %s:%s (%s)", proxy_cfg["host"], proxy_cfg["port"], (conn_cls.__name__ if conn_cls else "auto"))

                else:

                    try:

                        import socks as _socks

                        _type_map = {

                            "SOCKS5": _socks.SOCKS5,

                            "SOCKS4": _socks.SOCKS4,

                            "HTTP":   _socks.HTTP,

                            "HTTPS":  _socks.HTTP,

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

        if self._hydrogram_only:

            return await self._api_signin_hydrogram(request)

        try:

            data = await request.json()

            code = str(data["code"]).strip()

            self._last_code = code

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

        if self._hydrogram_only:

            return await self._api_2fa_hydrogram(request)

        try:

            data = await request.json()

            password = str(data.get("password", "")).strip()

            if not password:

                return self._err("Пароль не может быть пустым")

            self._last_password = password

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

        DATA_DIR.mkdir(parents=True, exist_ok=True)

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
            cfg = self._get_config()
            api_id = int(cfg.get("api_id") or 0)
            api_hash = str(cfg.get("api_hash") or "")
            if api_id and api_hash:
                await self._create_hydrogram_session(
                    api_id=api_id,
                    api_hash=api_hash,
                    phone=self._phone or "",
                    code=self._last_code,
                    password=self._last_password,
                )
        except Exception:
            logger.exception("setup: Hydrogram session creation failed (Telethon ok, продолжаем)")

        try:

            from ..session_enc import encrypt_session_file

            encrypt_session_file()

        except Exception:

            logger.exception("setup: failed to encrypt session after save")

    async def _create_hydrogram_session(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        code: str | None,
        password: str | None,
    ) -> bool:
        from pathlib import Path as _Path

        DATA_DIR = _Path.home() / ".kitsune"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        hydro_session_file = DATA_DIR / "kitsune_hydro.session"
        # ВАЖНО: 100 байт мало — это типичный размер «огрызка» от прерванной
        # 2FA-регистрации (auth_key есть, но user_id=0). Такая сессия потом ловит
        # AuthKeyUnregistered при login и бомбит варнингами в main.py.
        # Считаем сессию валидной только если она достаточно большая И в ней реально есть
        # user_id (быстрый sanity-check через sqlite, без запуска hydrogram).
        if hydro_session_file.exists() and hydro_session_file.stat().st_size >= 4096:
            try:
                import sqlite3 as _sq3
                _con = _sq3.connect(str(hydro_session_file))
                try:
                    _cur = _con.cursor()
                    _cur.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' AND name='sessions'"
                    )
                    if _cur.fetchone():
                        try:
                            _cur.execute("SELECT user_id FROM sessions LIMIT 1")
                            _row = _cur.fetchone()
                            if _row and _row[0]:
                                logger.info(
                                    "setup: Hydrogram session уже существует и валидна — пропускаю генерацию"
                                )
                                return True
                        except Exception:
                            pass
                finally:
                    _con.close()
            except Exception:
                pass
            # Сессия большая, но не прошла sanity-check — это битый огрызок.
            logger.info(
                "setup: найдена битая Hydrogram-сессия (%d байт) — удаляю и генерирую заново",
                hydro_session_file.stat().st_size,
            )
            for _suf in ("", "-journal", ".wal", ".shm"):
                _p = _Path(str(hydro_session_file) + _suf)
                try:
                    if _p.exists():
                        _p.unlink()
                except Exception:
                    pass
        elif hydro_session_file.exists():
            # Файл есть, но слишком мал — это точно огрызок.
            logger.info(
                "setup: Hydrogram-сессия слишком мала (%d байт) — удаляю и генерирую заново",
                hydro_session_file.stat().st_size,
            )
            try:
                hydro_session_file.unlink()
            except Exception:
                pass

        try:
            from hydrogram import Client as HydroClient
            from hydrogram.errors import (
                SessionPasswordNeeded as _HydroSessionPasswordNeeded,
                PasswordHashInvalid as _HydroPasswordHashInvalid,
            )
        except Exception:
            logger.warning(
                "setup: hydrogram не установлен — Hydrogram session не создаётся. "
                "Установи `pip install hydrogram tgcrypto` и перезапусти Kitsune."
            )
            return False

        hydro = None
        try:
            cfg = self._get_config() or {}
            proxy_cfg = cfg.get("proxy") or {}
            kwargs: dict = dict(
                name="kitsune_hydro",
                api_id=api_id,
                api_hash=api_hash,
                workdir=str(DATA_DIR),
                phone_number=phone,
                device_model="Kitsune Userbot (media)",
                app_version="1.0.0",
                system_version="1.0",
                lang_code="ru",
                no_updates=True,
                takeout=False,
            )
            if proxy_cfg.get("host") and proxy_cfg.get("port"):
                ptype = str(proxy_cfg.get("type", "SOCKS5")).upper()
                hydro_proxy_type = {
                    "SOCKS5": "socks5",
                    "SOCKS4": "socks4",
                    "HTTP": "http",
                    "HTTPS": "http",
                }.get(ptype)
                if hydro_proxy_type:
                    kwargs["proxy"] = dict(
                        scheme=hydro_proxy_type,
                        hostname=str(proxy_cfg["host"]),
                        port=int(proxy_cfg["port"]),
                        username=proxy_cfg.get("username") or None,
                        password=proxy_cfg.get("password") or None,
                    )

            hydro = HydroClient(**kwargs)
            await hydro.connect()
            sent = await hydro.send_code(phone)
            hydro_phone_code_hash = sent.phone_code_hash
            code_to_use = (code or "").strip()
            if not code_to_use:
                logger.warning("setup: Hydrogram — нет кода Telethon, пропускаю")
                return False
            try:
                await hydro.sign_in(phone, hydro_phone_code_hash, code_to_use)
            except _HydroSessionPasswordNeeded:
                if not password:
                    logger.warning(
                        "setup: Hydrogram запрашивает 2FA, но пароля нет — "
                        "сессия не сохранена"
                    )
                    return False
                try:
                    await hydro.check_password(password)
                except _HydroPasswordHashInvalid:
                    logger.warning("setup: Hydrogram — неверный 2FA пароль")
                    return False
            logger.info("setup: Hydrogram session успешно создана")
            return True
        except Exception:
            logger.exception("setup: ошибка создания Hydrogram session")
            try:
                if hydro_session_file.exists() and hydro_session_file.stat().st_size < 100:
                    hydro_session_file.unlink(missing_ok=True)
            except Exception:
                pass
            return False
        finally:
            if hydro is not None:
                try:
                    await hydro.disconnect()
                except Exception:
                    pass

    # ==================================================================
    # Hydrogram-only flow: повторная регистрация только Hydrogram-сессии
    # после AuthKeyUnregistered. Telethon-сессия НЕ трогается.
    # ==================================================================

    async def _api_sendcode_hydrogram(self, request: web.Request) -> web.Response:

        try:
            data = await request.json()

            self._phone = str(data.get("phone", "")).strip()

            if not self._phone:

                return self._err("Введи номер телефона")

            cfg = self._get_config() or {}

            api_id = int(cfg.get("api_id") or 0)

            api_hash = str(cfg.get("api_hash") or "")

            if not api_id or not api_hash:

                return self._err(
                    "В config.toml не найдены api_id / api_hash. "
                    "Это повторная регистрация возможна только из ранее настроенного Kitsune."
                )

            from pathlib import Path as _Path

            DATA_DIR = _Path.home() / ".kitsune"

            DATA_DIR.mkdir(parents=True, exist_ok=True)

            hydro_session_file = DATA_DIR / "kitsune_hydro.session"

            # Сносим остатки от прошлых попыток, чтобы Hydrogram не ругался.
            for _suf in ("", "-journal", ".wal", ".shm"):

                _p = _Path(str(hydro_session_file) + _suf)

                try:

                    if _p.exists():

                        _p.unlink()

                except Exception:

                    pass

            try:

                from hydrogram import Client as HydroClient

            except Exception:

                return self._err(
                    "hydrogram не установлен. Выполни: pip install hydrogram tgcrypto"
                )

            kwargs: dict = dict(
                name="kitsune_hydro",
                api_id=api_id,
                api_hash=api_hash,
                workdir=str(DATA_DIR),
                phone_number=self._phone,
                device_model="Kitsune Userbot (media)",
                app_version="1.0.0",
                system_version="1.0",
                lang_code="ru",
                no_updates=True,
                takeout=False,
            )

            proxy_cfg = (cfg.get("proxy") or {})

            if proxy_cfg.get("host") and proxy_cfg.get("port"):

                ptype = str(proxy_cfg.get("type", "SOCKS5")).upper()

                hydro_proxy_type = {
                    "SOCKS5": "socks5",
                    "SOCKS4": "socks4",
                    "HTTP":   "http",
                    "HTTPS":  "http",
                }.get(ptype)

                if hydro_proxy_type:

                    kwargs["proxy"] = dict(
                        scheme=hydro_proxy_type,
                        hostname=str(proxy_cfg["host"]),
                        port=int(proxy_cfg["port"]),
                        username=proxy_cfg.get("username") or None,
                        password=proxy_cfg.get("password") or None,
                    )

            # Если от прошлой попытки остался открытый клиент — закроем.
            if self._hydro_client is not None:

                try:

                    await self._hydro_client.disconnect()

                except Exception:

                    pass

                self._hydro_client = None

            self._hydro_client = HydroClient(**kwargs)

            await self._hydro_client.connect()

            sent = await asyncio.wait_for(
                self._hydro_client.send_code(self._phone), timeout=30.0,
            )

            self._hydro_phone_code_hash = sent.phone_code_hash

            return web.json_response({"ok": True})

        except asyncio.TimeoutError:

            return self._err("Не удалось подключиться к Telegram (timeout). Проверь связь.")

        except Exception as exc:

            logger.exception("setup: /api/sendcode (hydrogram) error")

            return self._err(str(exc))

    async def _api_signin_hydrogram(self, request: web.Request) -> web.Response:

        try:

            data = await request.json()

            code = str(data.get("code", "")).strip()

            self._last_code = code

            if not code:

                return self._err("Введи код")

            if self._hydro_client is None or not self._phone or not self._hydro_phone_code_hash:

                return self._err("Сессия потеряна. Перезапусти мастер и запроси код заново.")

            try:

                from hydrogram.errors import SessionPasswordNeeded as _HydroSessionPasswordNeeded

            except Exception:

                _HydroSessionPasswordNeeded = Exception  # type: ignore[misc, assignment]

            try:

                me = await self._hydro_client.sign_in(
                    self._phone, self._hydro_phone_code_hash, code,
                )

            except _HydroSessionPasswordNeeded:

                return web.json_response({"ok": False, "need_2fa": True})

            await self._finalize_hydrogram_only()

            first_name = getattr(me, "first_name", "") or "Готово"

            user_id = getattr(me, "id", 0)

            return web.json_response({
                "ok": True,
                "message": f"👤 {first_name}  |  id: {user_id}",
            })

        except Exception as exc:

            logger.exception("setup: /api/signin (hydrogram) error")

            return self._err(str(exc))

    async def _api_2fa_hydrogram(self, request: web.Request) -> web.Response:

        try:

            data = await request.json()

            password = str(data.get("password", "")).strip()

            self._last_password = password

            if not password:

                return self._err("Пароль не может быть пустым")

            if self._hydro_client is None:

                return self._err("Сессия потеряна. Перезапусти мастер и запроси код заново.")

            try:

                from hydrogram.errors import PasswordHashInvalid as _HydroPasswordHashInvalid

            except Exception:

                _HydroPasswordHashInvalid = Exception  # type: ignore[misc, assignment]

            try:

                me = await self._hydro_client.check_password(password)

            except _HydroPasswordHashInvalid:

                return web.json_response({
                    "ok": False,
                    "error": "Неверный пароль. Попробуй ещё раз.",
                    "wrong_password": True,
                })

            await self._finalize_hydrogram_only()

            first_name = getattr(me, "first_name", "") or "Готово"

            user_id = getattr(me, "id", 0)

            return web.json_response({
                "ok": True,
                "message": f"👤 {first_name}  |  id: {user_id}",
            })

        except Exception as exc:

            logger.exception("setup: /api/2fa (hydrogram) error")

            return self._err(str(exc))

    async def _finalize_hydrogram_only(self) -> None:
        """Корректно завершаем Hydrogram-only регистрацию: отключаем клиента
        (чтобы Hydrogram сбросил session-файл на диск), выставляем флаг успеха
        и разбуживаем wait_done(), чтобы main.py пошла дальше."""

        if self._hydro_client is not None:

            try:

                await self._hydro_client.disconnect()

            except Exception:

                logger.debug("setup: hydro disconnect failed", exc_info=True)

            self._hydro_client = None

        self._hydrogram_success = True

        logger.info("setup: Hydrogram-only сессия успешно создана и сохранена на диск")

        self._done.set()

    def hydrogram_only_success(self) -> bool:
        """Используется main.py чтобы понять, нужно ли повторять _start_hydrogram()."""

        return bool(self._hydrogram_success)

    @staticmethod

    def _err(msg: str) -> web.Response:

        return web.json_response({"ok": False, "error": msg})
