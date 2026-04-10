from __future__ import annotations

import asyncio
import json
import logging
import typing
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import aiohttp
    import aiohttp.web
    WEB_AVAILABLE = True
except ImportError:
    WEB_AVAILABLE = False

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
        app.router.add_get("/",                   self._handle_root)
        app.router.add_get("/api/status",         self._handle_status)
        app.router.add_get("/api/devices",        self._handle_devices)
        app.router.add_post("/api/save_config",   self._handle_save_config)

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
        name = me.first_name if me else "—"
        uid  = me.id if me else "—"
        username = f"@{me.username}" if me and getattr(me, "username", None) else ""

        html = _build_html(name=name, uid=uid, username=username, version=__version_str__)
        return aiohttp.web.Response(text=html, content_type="text/html")

    async def _handle_status(self, request: "aiohttp.web.Request") -> "aiohttp.web.Response":
        import psutil, time
        from ..version import __version_str__

        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        cpu  = psutil.cpu_percent(interval=0.2)

        loader = getattr(self._client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0

        data = {
            "ok":        True,
            "version":   __version_str__,
            "timestamp": int(time.time()),
            "account": {
                "name":     self._client.tg_me.first_name if self._client.tg_me else "—",
                "id":       self._client.tg_me.id if self._client.tg_me else 0,
                "username": getattr(self._client.tg_me, "username", "") or "",
            },
            "modules":   mod_count,
            "system": {
                "cpu_pct":      round(cpu, 1),
                "ram_used_mb":  mem.used // 1024 // 1024,
                "ram_total_mb": mem.total // 1024 // 1024,
                "ram_pct":      round(mem.percent, 1),
                "disk_used_gb": round(disk.used / 1024 ** 3, 1),
                "disk_total_gb":round(disk.total / 1024 ** 3, 1),
                "disk_pct":     round(disk.percent, 1),
            },
        }
        return aiohttp.web.Response(
            text=json.dumps(data),
            content_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def _handle_devices(self, request: "aiohttp.web.Request") -> "aiohttp.web.Response":
        devices = []
        try:
            from telethon.tl.functions.account import GetAuthorizationsRequest
            result = await self._client(GetAuthorizationsRequest())
            me = self._client.tg_me
            username = f"@{me.username}" if me and getattr(me, "username", None) else (me.first_name if me else "—")

            for auth in result.authorizations:
                device_name = auth.device_model or "Unknown device"
                app_name    = auth.app_name or ""
                platform    = auth.platform or ""
                country     = auth.country or ""
                current     = getattr(auth, "current", False)

                label = f"{device_name}"
                if app_name:
                    label += f" · {app_name}"
                if platform:
                    label += f" ({platform})"

                devices.append({
                    "device":   label,
                    "account":  username,
                    "location": country,
                    "current":  current,
                    "ip":       auth.ip or "",
                })
        except Exception as exc:
            logger.debug("WebCore: could not fetch authorizations: %s", exc)

        return aiohttp.web.Response(
            text=json.dumps({"ok": True, "devices": devices, "count": len(devices)}),
            content_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
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

def _build_html(*, name: str, uid: int, username: str, version: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kitsune {version}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:
  --accent:
  --red:
}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);
  min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;
  background-image:radial-gradient(ellipse at 20% 50%,rgba(120,60,255,0.06) 0%,transparent 60%),
    radial-gradient(ellipse at 80% 20%,rgba(80,100,255,0.04) 0%,transparent 50%);
}}
.shell{{width:100%;max-width:480px;display:flex;flex-direction:column;gap:0}}
.topbar{{background:var(--surface);border:1px solid var(--border);border-radius:20px 20px 0 0;
  padding:20px 24px;display:flex;align-items:center;gap:14px;
  border-bottom:1px solid rgba(130,80,255,0.08);
}}
.logo-box{{width:44px;height:44px;background:linear-gradient(135deg,
  border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:1.4rem;
  box-shadow:0 0 20px rgba(120,60,255,0.3);flex-shrink:0;
}}
.title-group{{flex:1}}
.title-group h1{{font-size:1.1rem;font-weight:700;color:
.title-group small{{font-size:.72rem;color:var(--muted);margin-top:1px;display:block}}
.badge{{display:inline-flex;align-items:center;gap:5px;background:rgba(74,222,128,.1);
  border:1px solid rgba(74,222,128,.2);border-radius:20px;padding:4px 10px;
  font-size:.72rem;color:var(--green);
}}
.dot{{width:6px;height:6px;border-radius:50%;background:currentColor;box-shadow:0 0 5px currentColor;
  animation:blink 2s infinite;
}}
@keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}

.tabs{{background:var(--surface);border-left:1px solid var(--border);border-right:1px solid var(--border);
  padding:0 16px;display:flex;gap:2px;
}}
.tab{{padding:10px 16px;font-size:.8rem;color:var(--muted);cursor:pointer;border-radius:8px 8px 0 0;
  border:none;background:transparent;transition:all .2s;position:relative;
  border-bottom:2px solid transparent;
}}
.tab.active{{color:var(--accent2);border-bottom-color:var(--accent);background:rgba(130,80,255,.06);}}
.tab:hover:not(.active){{color:var(--text);background:rgba(130,80,255,.04);}}

.content{{background:var(--surface);border:1px solid var(--border);border-top:none;
  border-radius:0 0 20px 20px;min-height:320px;
}}
.panel{{padding:20px;display:none;animation:fadein .2s ease}}
.panel.active{{display:block}}
@keyframes fadein{{from{{opacity:0;transform:translateY(4px)}}to{{opacity:1;transform:none}}}}

.row-group{{display:flex;flex-direction:column;gap:1px}}
.row{{display:flex;justify-content:space-between;align-items:center;
  padding:10px 12px;border-radius:10px;transition:background .15s;
}}
.row:hover{{background:rgba(130,80,255,.05)}}
.row-label{{font-size:.8rem;color:var(--muted)}}
.row-value{{font-size:.84rem;color:

.divider{{height:1px;background:var(--border);margin:16px 0}}

.section-title{{font-size:.7rem;color:var(--muted);text-transform:uppercase;
  letter-spacing:1.2px;margin-bottom:12px;padding:0 2px;
}}
.stat-block{{display:flex;flex-direction:column;gap:12px}}
.stat-item{{display:flex;flex-direction:column;gap:5px}}
.stat-head{{display:flex;justify-content:space-between;font-size:.78rem}}
.stat-name{{color:var(--muted)}}
.stat-val{{color:
.bar-bg{{height:5px;background:rgba(130,80,255,.1);border-radius:3px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:3px;transition:width .6s cubic-bezier(.4,0,.2,1);
  background:linear-gradient(90deg,
}}
.bar-warn{{background:linear-gradient(90deg,
.bar-crit{{background:linear-gradient(90deg,

.device-list{{display:flex;flex-direction:column;gap:8px}}
.device-card{{background:var(--surface2);border:1px solid var(--border);border-radius:12px;
  padding:12px 14px;transition:border-color .2s;
}}
.device-card:hover{{border-color:rgba(130,80,255,.3)}}
.device-card.current{{border-color:rgba(130,80,255,.4);background:rgba(130,80,255,.05)}}
.device-name{{font-size:.84rem;color:
.device-meta{{font-size:.74rem;color:var(--muted);margin-top:4px;display:flex;gap:12px;flex-wrap:wrap}}
.chip{{display:inline-flex;align-items:center;padding:1px 7px;border-radius:10px;font-size:.68rem;}}
.chip-current{{background:rgba(74,222,128,.1);color:var(--green);border:1px solid rgba(74,222,128,.2)}}
.chip-other{{background:rgba(130,80,255,.1);color:var(--accent2);border:1px solid rgba(130,80,255,.2)}}
.loading-msg{{text-align:center;padding:40px 20px;color:var(--muted);font-size:.85rem}}
.spinner{{display:inline-block;width:18px;height:18px;border:2px solid var(--border);
  border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;
  vertical-align:middle;margin-right:8px;
}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}

.footer{{text-align:center;padding:14px;font-size:.7rem;color:var(--muted);
  border-top:1px solid var(--border);margin-top:0;
}}
.upd-dot{{width:5px;height:5px;border-radius:50%;background:var(--accent);display:inline-block;
  margin-right:5px;animation:blink 2s infinite;
}}
</style>
</head>
<body>
<div class="shell">

  <div class="topbar">
    <div class="logo-box">🦊</div>
    <div class="title-group">
      <h1>Kitsune Userbot</h1>
      <small id="version-label">v{version}</small>
    </div>
    <div class="badge"><div class="dot"></div> Online</div>
  </div>

  <div class="tabs">
    <button class="tab active" onclick="switchTab('main',this)">🏠 Главная</button>
    <button class="tab" onclick="switchTab('devices',this)">📱 Устройства</button>
    <button class="tab" onclick="switchTab('info',this)">📊 Информация</button>
  </div>

  <div class="content">

    <div class="panel active" id="panel-main">
      <div class="row-group">
        <div class="row">
          <span class="row-label">Аккаунт</span>
          <span class="row-value" id="acc-name">{name}</span>
        </div>
        <div class="row">
          <span class="row-label">Username</span>
          <span class="row-value" id="acc-username">{username or '—'}</span>
        </div>
        <div class="row">
          <span class="row-label">ID</span>
          <span class="row-value">{uid}</span>
        </div>
        <div class="row">
          <span class="row-label">Модули</span>
          <span class="row-value" id="mod-count">—</span>
        </div>
        <div class="row">
          <span class="row-label">Разработчик</span>
          <span class="row-value">Yushi · @Mikasu32</span>
        </div>
      </div>
      <div class="divider"></div>
      <div class="footer">
        <span class="upd-dot"></span>
        <span id="last-upd">обновление...</span>
      </div>
    </div>

    <div class="panel" id="panel-devices">
      <div class="section-title">Активные сессии</div>
      <div id="devices-list" class="device-list">
        <div class="loading-msg"><span class="spinner"></span>Загружаю...</div>
      </div>
    </div>

    <div class="panel" id="panel-info">
      <div class="section-title">Ресурсы системы</div>
      <div class="stat-block">
        <div class="stat-item">
          <div class="stat-head">
            <span class="stat-name">CPU</span>
            <span class="stat-val" id="cpu-val">—</span>
          </div>
          <div class="bar-bg"><div class="bar-fill" id="cpu-bar" style="width:0%"></div></div>
        </div>
        <div class="stat-item">
          <div class="stat-head">
            <span class="stat-name">RAM</span>
            <span class="stat-val" id="ram-val">—</span>
          </div>
          <div class="bar-bg"><div class="bar-fill" id="ram-bar" style="width:0%"></div></div>
        </div>
        <div class="stat-item">
          <div class="stat-head">
            <span class="stat-name">Диск</span>
            <span class="stat-val" id="disk-val">—</span>
          </div>
          <div class="bar-bg"><div class="bar-fill" id="disk-bar" style="width:0%"></div></div>
        </div>
      </div>
    </div>

  </div>
</div>

<script>
let activeTab = 'main';
let devicesLoaded = false;

function switchTab(name, btn) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panel-' + name).classList.add('active');
  activeTab = name;
  if (name === 'devices' && !devicesLoaded) loadDevices();
}}

function setBar(id, pct) {{
  const el = document.getElementById(id);
  if (!el) return;
  el.style.width = pct + '%';
  el.className = 'bar-fill' + (pct >= 90 ? ' bar-crit' : pct >= 70 ? ' bar-warn' : '');
}}

function setText(id, val) {{
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}}

async function fetchStatus() {{
  try {{
    const r = await fetch('/api/status');
    const d = await r.json();
    if (!d.ok) return;

    const s = d.system;
    setText('mod-count', d.modules);
    setText('cpu-val', s.cpu_pct + '%');
    setText('ram-val', s.ram_used_mb + ' / ' + s.ram_total_mb + ' MB');
    setText('disk-val', s.disk_used_gb + ' / ' + s.disk_total_gb + ' GB');
    setBar('cpu-bar', s.cpu_pct);
    setBar('ram-bar', s.ram_pct);
    setBar('disk-bar', s.disk_pct);

    const now = new Date();
    setText('last-upd', 'обновлено в ' + now.toLocaleTimeString('ru', {{hour:'2-digit',minute:'2-digit',second:'2-digit'}}));
  }} catch(e) {{ /* silent */ }}
}}

async function loadDevices() {{
  try {{
    const r = await fetch('/api/devices');
    const d = await r.json();
    const list = document.getElementById('devices-list');

    if (!d.ok || !d.devices.length) {{
      list.innerHTML = '<div class="loading-msg">Нет данных</div>';
      return;
    }}

    devicesLoaded = true;
    list.innerHTML = d.devices.map(dev => `
      <div class="device-card ${{dev.current ? 'current' : ''}}">
        <div class="device-name">
          ${{dev.current ? '💻' : '📱'}} ${{escHtml(dev.device)}}
          <span class="chip ${{dev.current ? 'chip-current' : 'chip-other'}}">${{dev.current ? 'текущее' : 'активное'}}</span>
        </div>
        <div class="device-meta">
          <span>👤 ${{escHtml(dev.account)}}</span>
          ${{dev.location ? '<span>🌍 ' + escHtml(dev.location) + '</span>' : ''}}
          ${{dev.ip ? '<span>🔒 ' + escHtml(dev.ip) + '</span>' : ''}}
        </div>
      </div>
    `).join('');

    const count = document.querySelector('.tab:nth-child(2)');
    if (count) count.textContent = '📱 Устройства (' + d.count + ')';
  }} catch(e) {{
    document.getElementById('devices-list').innerHTML = '<div class="loading-msg">Ошибка загрузки</div>';
  }}
}}

function escHtml(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

fetchStatus();
setInterval(fetchStatus, 5000);
</script>
</body>
</html>"""
