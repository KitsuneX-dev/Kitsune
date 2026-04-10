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
        app.router.add_get("/",                 self._handle_root)
        app.router.add_get("/api/status",       self._handle_status)
        app.router.add_get("/api/users",        self._handle_users)
        app.router.add_post("/api/save_config", self._handle_save_config)
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

    async def _handle_root(self, request):
        from ..version import __version_str__
        me = self._client.tg_me
        name     = me.first_name if me else "—"
        uid      = me.id if me else "—"
        username = f"@{me.username}" if me and getattr(me, "username", None) else ""
        html = _build_html(name=name, uid=uid, username=username, version=__version_str__)
        return aiohttp.web.Response(text=html, content_type="text/html")

    async def _handle_status(self, request):
        import psutil, time
        from ..version import __version_str__
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        try:
            cpu = psutil.cpu_percent(interval=0.2)
        except PermissionError:
            cpu = 0.0
        loader    = getattr(self._client, "_kitsune_loader", None)
        mod_count = len(loader.modules) if loader else 0
        data = {
            "ok": True, "version": __version_str__,
            "timestamp": int(time.time()),
            "account": {
                "name":     self._client.tg_me.first_name if self._client.tg_me else "—",
                "id":       self._client.tg_me.id if self._client.tg_me else 0,
                "username": getattr(self._client.tg_me, "username", "") or "",
            },
            "modules": mod_count,
            "system": {
                "cpu_pct":       round(cpu, 1),
                "ram_used_mb":   mem.used // 1024 // 1024,
                "ram_total_mb":  mem.total // 1024 // 1024,
                "ram_pct":       round(mem.percent, 1),
                "disk_used_gb":  round(disk.used / 1024 ** 3, 1),
                "disk_total_gb": round(disk.total / 1024 ** 3, 1),
                "disk_pct":      round(disk.percent, 1),
            },
        }
        return aiohttp.web.Response(
            text=json.dumps(data), content_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def _handle_users(self, request):
        me = self._client.tg_me
        users = []
        if me:
            username = f"@{me.username}" if getattr(me, "username", None) else ""
            users.append({"name": me.first_name or "—", "username": username, "id": me.id, "owner": True})
        return aiohttp.web.Response(
            text=json.dumps({"ok": True, "users": users}),
            content_type="application/json",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    async def _handle_save_config(self, request):
        try:
            body = await request.json()
        except Exception:
            return aiohttp.web.Response(status=400, text='{"ok":false,"error":"bad json"}')
        from ..main import set_config_key
        for k, v in body.items():
            set_config_key(k, v)
        return aiohttp.web.Response(text='{"ok":true}', content_type="application/json")


def _build_html(*, name, uid, username, version):
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kitsune {version}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#0a0a0f;--surface:#111118;--surface2:#16161f;
  --border:rgba(255,255,255,0.06);--border2:rgba(255,255,255,0.1);
  --text:#f0f0f8;--muted:#6b6b80;
  --accent:#7c4dff;--accent2:#a278ff;--accent-glow:rgba(124,77,255,0.25);
  --green:#3dffa0;--green-dim:rgba(61,255,160,0.12);
  --orange:#ff9f4a;--red:#ff4a6b;--gold:#ffd166;
}}
html,body{{height:100%}}
body{{
  font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);
  min-height:100vh;display:flex;align-items:center;justify-content:center;
  padding:24px 16px;overflow-x:hidden;
}}
body::before,body::after{{
  content:'';position:fixed;border-radius:50%;filter:blur(80px);pointer-events:none;z-index:0;
}}
body::before{{
  width:500px;height:500px;top:-120px;left:-120px;
  background:radial-gradient(circle,rgba(124,77,255,0.13) 0%,transparent 70%);
}}
body::after{{
  width:400px;height:400px;bottom:-80px;right:-80px;
  background:radial-gradient(circle,rgba(61,255,160,0.06) 0%,transparent 70%);
}}
.shell{{
  width:100%;max-width:460px;position:relative;z-index:1;
  display:flex;flex-direction:column;border-radius:24px;overflow:hidden;
  border:1px solid var(--border2);
  box-shadow:0 0 0 1px rgba(124,77,255,0.08),0 32px 80px rgba(0,0,0,0.6),0 0 60px rgba(124,77,255,0.08);
  background:var(--surface);
}}
.topbar{{
  padding:22px 24px 18px;
  background:linear-gradient(160deg,rgba(124,77,255,0.1) 0%,transparent 60%);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:16px;position:relative;overflow:hidden;
}}
.topbar::after{{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,rgba(124,77,255,0.5),transparent);
}}
.logo-wrap{{
  width:48px;height:48px;flex-shrink:0;
  background:linear-gradient(135deg,#6030e0,#9060ff);
  border-radius:16px;display:flex;align-items:center;justify-content:center;
  font-size:1.5rem;
  box-shadow:0 0 24px rgba(124,77,255,0.4),0 4px 12px rgba(0,0,0,0.4);
  position:relative;
}}
.logo-wrap::after{{
  content:'';position:absolute;inset:0;border-radius:16px;
  background:linear-gradient(135deg,rgba(255,255,255,0.15),transparent);
}}
.topbar-info{{flex:1;min-width:0}}
.topbar-title{{
  font-family:'Syne',sans-serif;font-size:1.15rem;font-weight:800;
  color:var(--text);letter-spacing:-.02em;white-space:nowrap;
}}
.topbar-sub{{font-size:.72rem;color:var(--muted);margin-top:2px}}
.status-pill{{
  display:inline-flex;align-items:center;gap:5px;
  background:var(--green-dim);border:1px solid rgba(61,255,160,0.2);
  border-radius:20px;padding:5px 11px;
  font-size:.72rem;font-weight:600;color:var(--green);white-space:nowrap;
}}
.pulse{{
  width:6px;height:6px;border-radius:50%;
  background:var(--green);box-shadow:0 0 8px var(--green);
  animation:pulse 2s ease-in-out infinite;
}}
@keyframes pulse{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.5;transform:scale(.8)}}}}
.tab-bar{{
  display:flex;padding:0 12px;background:var(--surface);
  border-bottom:1px solid var(--border);
}}
.tab-btn{{
  flex:1;padding:12px 8px;background:none;border:none;
  font-family:'Inter',sans-serif;font-size:.78rem;font-weight:500;
  color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;
  transition:color .2s,border-color .2s;white-space:nowrap;
}}
.tab-btn.active{{color:var(--accent2);border-bottom-color:var(--accent);}}
.tab-btn:hover:not(.active){{color:rgba(240,240,248,.6)}}
.panel-area{{min-height:300px}}
.panel{{display:none;padding:20px;animation:fadeUp .22s ease both}}
.panel.active{{display:block}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(6px)}}to{{opacity:1;transform:none}}}}
.sec-title{{
  font-family:'Syne',sans-serif;font-size:.78rem;font-weight:700;
  color:var(--muted);letter-spacing:.08em;text-transform:uppercase;margin-bottom:12px;
}}
.row-list{{display:flex;flex-direction:column;gap:2px}}
.row{{
  display:flex;justify-content:space-between;align-items:center;
  padding:10px 12px;border-radius:10px;transition:background .15s;
}}
.row:hover{{background:rgba(124,77,255,0.06)}}
.row-key{{font-size:.8rem;color:var(--muted);font-weight:500}}
.row-val{{font-size:.85rem;color:var(--text);font-weight:500;text-align:right;max-width:220px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.row-val.accent{{color:var(--accent2)}}
.row-val.mono{{font-family:monospace;font-size:.8rem;color:var(--muted)}}
.divider{{height:1px;background:var(--border);margin:12px 0}}
.stat-list{{display:flex;flex-direction:column;gap:14px}}
.stat-head{{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:7px}}
.stat-name{{font-size:.8rem;font-weight:600;color:var(--text)}}
.stat-val{{font-size:.78rem;color:var(--muted);font-family:monospace}}
.bar-track{{height:6px;border-radius:3px;background:rgba(255,255,255,0.05);overflow:hidden}}
.bar-fill{{
  height:100%;border-radius:3px;
  background:linear-gradient(90deg,var(--accent),var(--accent2));
  transition:width .7s cubic-bezier(.4,0,.2,1);
  position:relative;overflow:hidden;
}}
.bar-fill::after{{
  content:'';position:absolute;top:0;left:-100%;width:100%;height:100%;
  background:linear-gradient(90deg,transparent,rgba(255,255,255,0.15),transparent);
  animation:shimmer 2s infinite;
}}
@keyframes shimmer{{to{{left:200%}}}}
.bar-fill.warn{{background:linear-gradient(90deg,var(--orange),#ffbb6b)}}
.bar-fill.crit{{background:linear-gradient(90deg,var(--red),#ff8080)}}
.users-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}}
.add-btn{{
  display:inline-flex;align-items:center;gap:6px;padding:7px 13px;
  background:rgba(124,77,255,0.12);border:1px solid rgba(124,77,255,0.25);
  border-radius:10px;font-size:.76rem;font-weight:600;color:var(--accent2);
  cursor:pointer;transition:all .2s;font-family:'Inter',sans-serif;
}}
.add-btn:hover{{background:rgba(124,77,255,0.2);border-color:rgba(124,77,255,0.45);box-shadow:0 0 16px rgba(124,77,255,0.2)}}
.toast{{
  position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(20px);
  background:var(--surface2);border:1px solid var(--border2);border-radius:14px;
  padding:12px 20px;font-size:.82rem;color:var(--text);
  box-shadow:0 8px 32px rgba(0,0,0,0.5);opacity:0;pointer-events:none;
  transition:all .3s cubic-bezier(.4,0,.2,1);z-index:999;
  display:flex;align-items:center;gap:8px;white-space:nowrap;
}}
.toast.show{{opacity:1;transform:translateX(-50%) translateY(0)}}
.user-card{{
  background:var(--surface2);border:1px solid var(--border);border-radius:14px;
  padding:14px 16px;display:flex;align-items:center;gap:14px;
  transition:border-color .2s,transform .15s;
}}
.user-card:hover{{border-color:rgba(124,77,255,0.3);transform:translateY(-1px)}}
.user-avatar{{
  width:42px;height:42px;flex-shrink:0;border-radius:50%;
  background:linear-gradient(135deg,#6030e0,#9060ff);
  display:flex;align-items:center;justify-content:center;font-size:1.2rem;
  box-shadow:0 0 16px rgba(124,77,255,0.3);
}}
.user-info{{flex:1;min-width:0}}
.user-name{{font-size:.9rem;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.user-meta{{font-size:.75rem;color:var(--muted);margin-top:3px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}}
.tag{{display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:8px;font-size:.68rem;font-weight:600}}
.tag-owner{{background:rgba(255,209,102,0.12);color:var(--gold);border:1px solid rgba(255,209,102,0.2)}}
.tag-active{{background:var(--green-dim);color:var(--green);border:1px solid rgba(61,255,160,0.2)}}
.empty-state{{text-align:center;padding:40px 20px}}
.empty-icon{{font-size:2.5rem;margin-bottom:10px;opacity:.4}}
.empty-text{{font-size:.85rem;color:var(--muted)}}
.footer-bar{{
  border-top:1px solid var(--border);padding:12px 20px;
  display:flex;justify-content:space-between;align-items:center;
}}
.footer-dot{{
  width:5px;height:5px;border-radius:50%;background:var(--accent);
  display:inline-block;margin-right:6px;animation:pulse 2s infinite;
}}
.footer-ts{{font-size:.7rem;color:var(--muted)}}
.footer-ver{{font-size:.7rem;color:rgba(124,77,255,0.5);font-family:monospace}}
.spinner{{
  display:inline-block;width:16px;height:16px;
  border:2px solid var(--border2);border-top-color:var(--accent);
  border-radius:50%;animation:spin .6s linear infinite;
  vertical-align:middle;margin-right:8px;
}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.loading-msg{{text-align:center;padding:40px 20px;font-size:.85rem;color:var(--muted)}}
</style>
</head>
<body>
<div class="shell">

  <div class="topbar">
    <div class="logo-wrap">🦊</div>
    <div class="topbar-info">
      <div class="topbar-title">Kitsune Userbot</div>
      <div class="topbar-sub">v{version} &nbsp;·&nbsp; by Yushi @Mikasu32</div>
    </div>
    <div class="status-pill"><div class="pulse"></div>Online</div>
  </div>

  <div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab('main',this)">🏠 Главная</button>
    <button class="tab-btn" onclick="switchTab('users',this)">👥 Устройства</button>
    <button class="tab-btn" onclick="switchTab('info',this)">📊 Инфо</button>
  </div>

  <div class="panel-area">

    <div class="panel active" id="panel-main">
      <div class="sec-title">Аккаунт</div>
      <div class="row-list">
        <div class="row">
          <span class="row-key">Имя</span>
          <span class="row-val accent" id="acc-name">{name}</span>
        </div>
        <div class="row">
          <span class="row-key">Username</span>
          <span class="row-val" id="acc-username">{username or '—'}</span>
        </div>
        <div class="row">
          <span class="row-key">ID</span>
          <span class="row-val mono">{uid}</span>
        </div>
        <div class="row">
          <span class="row-key">Модули</span>
          <span class="row-val accent" id="mod-count">—</span>
        </div>
        <div class="row">
          <span class="row-key">Разработчик</span>
          <span class="row-val">Yushi · @Mikasu32</span>
        </div>
      </div>
      <div class="divider"></div>
      <div class="footer-bar">
        <span><span class="footer-dot"></span><span class="footer-ts" id="last-upd">обновляется...</span></span>
        <span class="footer-ver">v{version}</span>
      </div>
    </div>

    <div class="panel" id="panel-users">
      <div class="users-header">
        <div class="sec-title" style="margin-bottom:0">Подключённые аккаунты</div>
        <button class="add-btn" onclick="showComingSoon()">＋ Добавить</button>
      </div>
      <div id="users-list">
        <div class="loading-msg"><span class="spinner"></span>Загружаю...</div>
      </div>
    </div>

    <div class="panel" id="panel-info">
      <div class="sec-title">Ресурсы системы</div>
      <div class="stat-list">
        <div class="stat-item">
          <div class="stat-head"><span class="stat-name">CPU</span><span class="stat-val" id="cpu-val">—</span></div>
          <div class="bar-track"><div class="bar-fill" id="cpu-bar" style="width:0%"></div></div>
        </div>
        <div class="stat-item">
          <div class="stat-head"><span class="stat-name">RAM</span><span class="stat-val" id="ram-val">—</span></div>
          <div class="bar-track"><div class="bar-fill" id="ram-bar" style="width:0%"></div></div>
        </div>
        <div class="stat-item">
          <div class="stat-head"><span class="stat-name">Диск</span><span class="stat-val" id="disk-val">—</span></div>
          <div class="bar-track"><div class="bar-fill" id="disk-bar" style="width:0%"></div></div>
        </div>
      </div>
    </div>

  </div>
</div>

<div class="toast" id="toast">
  <span>🚧</span>
  <span>Ожидается в дальнейших обновлениях</span>
</div>

<script>
let usersLoaded = false, toastTimer = null;

function switchTab(name, btn) {{
  document.querySelectorAll('.tab-btn').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('panel-' + name).classList.add('active');
  if (name === 'users' && !usersLoaded) loadUsers();
}}
function setText(id, v) {{ const el = document.getElementById(id); if (el) el.textContent = v; }}
function setBar(id, pct) {{
  const el = document.getElementById(id); if (!el) return;
  el.style.width = pct + '%';
  el.className = 'bar-fill' + (pct >= 90 ? ' crit' : pct >= 70 ? ' warn' : '');
}}
function showComingSoon() {{
  const t = document.getElementById('toast');
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3000);
}}
function escHtml(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}
async function fetchStatus() {{
  try {{
    const r = await fetch('/api/status'); const d = await r.json(); if (!d.ok) return;
    const s = d.system;
    setText('mod-count', d.modules);
    setText('cpu-val',  s.cpu_pct + '%');
    setText('ram-val',  s.ram_used_mb + ' / ' + s.ram_total_mb + ' MB');
    setText('disk-val', s.disk_used_gb + ' / ' + s.disk_total_gb + ' GB');
    setBar('cpu-bar', s.cpu_pct); setBar('ram-bar', s.ram_pct); setBar('disk-bar', s.disk_pct);
    const now = new Date();
    setText('last-upd', 'обновлено ' + now.toLocaleTimeString('ru',{{hour:'2-digit',minute:'2-digit',second:'2-digit'}}));
  }} catch(e) {{}}
}}
async function loadUsers() {{
  const list = document.getElementById('users-list');
  try {{
    const r = await fetch('/api/users'); const d = await r.json();
    usersLoaded = true;
    if (!d.ok || !d.users || !d.users.length) {{
      list.innerHTML = '<div class="empty-state"><div class="empty-icon">👤</div><div class="empty-text">Нет подключённых аккаунтов</div></div>';
      return;
    }}
    list.innerHTML = d.users.map(u => `
      <div class="user-card">
        <div class="user-avatar">🦊</div>
        <div class="user-info">
          <div class="user-name">${{escHtml(u.name)}}</div>
          <div class="user-meta">
            ${{u.username ? '<span>' + escHtml(u.username) + '</span>' : ''}}
            <span class="tag tag-owner">👑 Владелец</span>
            <span class="tag tag-active">● Активен</span>
          </div>
        </div>
      </div>
    `).join('');
  }} catch(e) {{
    list.innerHTML = '<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-text">Ошибка загрузки</div></div>';
  }}
}}
fetchStatus();
setInterval(fetchStatus, 5000);
</script>
</body>
</html>"""
