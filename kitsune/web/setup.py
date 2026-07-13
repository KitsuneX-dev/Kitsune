from __future__ import annotations
import asyncio
import logging
import webbrowser
from typing import Any, Callable
from aiohttp import web
import os
from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent / "static"

logger = logging.getLogger(__name__)

_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Kitsune · Настройка</title>
<link rel="icon" type="image/png" href="/static/favicon-32.png">
<link rel="apple-touch-icon" href="/static/favicon-180.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:opsz,wght@9..40,300;9..40,500;9..40,700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/theme.css">
<style>
body {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: clamp(10px, 3vw, 20px);
  padding-left: max(clamp(10px, 3vw, 20px), env(safe-area-inset-left));
  padding-right: max(clamp(10px, 3vw, 20px), env(safe-area-inset-right));
  padding-top: max(clamp(10px, 3vw, 20px), env(safe-area-inset-top));
  padding-bottom: max(clamp(10px, 3vw, 20px), env(safe-area-inset-bottom));
  min-height: 100vh;
  min-height: 100dvh;
}

.card {
  width: 100%;
  max-width: 440px;
  background: var(--glass);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--bd3);
  border-radius: 22px;
  padding: clamp(22px, 6vw, 34px) clamp(16px, 5vw, 30px);
  box-shadow: 0 0 70px var(--violet-glow), 0 24px 60px rgba(0, 0, 0, 0.55);
  position: relative;
  animation: card-in .6s cubic-bezier(.22, .8, .3, 1) both;
}
@keyframes card-in {
  from { opacity: 0; transform: translateY(18px) scale(.98); }
  to   { opacity: 1; transform: none; }
}
/* neon top edge on the card */
.card::before {
  content: '';
  position: absolute;
  top: -1px; left: 24px; right: 24px;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--violet2), var(--fox2), transparent);
  opacity: .8;
  filter: drop-shadow(0 0 6px var(--violet-glow));
  pointer-events: none;
}
@media (max-width: 480px) { .card { border-radius: 18px; } }
@media (max-width: 360px) {
  .brand-mark.lg { width: 68px !important; height: 68px !important; }
  h1 { font-size: 1rem; }
}
/* на низких экранах (ландшафт телефона) карточка не центрируется жёстко, а скроллится */
@media (max-height: 700px) {
  body { align-items: flex-start; }
}

.brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 8px;
}
.brand .brand-orbit { margin-bottom: 14px; }
.brand-mark.lg {
  width: 84px;
  height: 84px;
  box-shadow: 0 0 0 1px var(--bd3), 0 0 34px var(--violet-glow), 0 0 20px var(--fox-glow);
  animation: logo-breathe 5s ease-in-out infinite;
}
@keyframes logo-breathe {
  0%, 100% { box-shadow: 0 0 0 1px var(--bd3), 0 0 30px var(--violet-glow), 0 0 16px var(--fox-glow); }
  50%      { box-shadow: 0 0 0 1px var(--bd3), 0 0 48px var(--violet-glow), 0 0 30px var(--fox-glow); }
}

h1 {
  text-align: center;
  font-family: var(--mono);
  font-size: 1.12rem;
  font-weight: 700;
  background: linear-gradient(100deg, var(--tx) 20%, var(--violet2) 55%, var(--fox2) 85%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  letter-spacing: -.01em;
}
.sub {
  text-align: center;
  font-size: .74rem;
  color: var(--mu);
  margin: 4px 0 18px;
  font-family: var(--mono);
}

/* Stage badge — Telethon / Hydrogram */
.stage-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 18px;
  padding: 8px 14px;
  border-radius: 10px;
  font-family: var(--mono);
  font-size: clamp(.62rem, 2.6vw, .72rem);
  font-weight: 700;
  letter-spacing: .03em;
  text-align: center;
  flex-wrap: wrap;
}
.stage-badge .num { flex-shrink: 0; }
.stage-badge.tele { background: rgba(74, 168, 255, 0.10); border: 1px solid rgba(74, 168, 255, 0.28); color: var(--blue); }
.stage-badge.hydro { background: rgba(255, 90, 43, 0.10); border: 1px solid rgba(255, 90, 43, 0.28); color: var(--fox2); }
.stage-badge .num {
  display: inline-flex;
  width: 20px; height: 20px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
  align-items: center;
  justify-content: center;
  font-size: .65rem;
}

.steps-bar { display: flex; gap: 6px; justify-content: center; margin-bottom: 24px; flex-wrap: wrap; }
.step-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--bd3); transition: all .3s; }
.step-dot.active { background: var(--violet); box-shadow: 0 0 10px var(--violet-glow); transform: scale(1.25); }
.step-dot.active.tele { background: var(--blue); box-shadow: 0 0 10px rgba(74, 168, 255, 0.55); }
.step-dot.done { background: var(--green); box-shadow: 0 0 8px rgba(56, 255, 176, 0.45); }

.step { display: none; animation: step-in .22s ease both; }
.step.active { display: block; }
@keyframes step-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.step-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: clamp(.8rem, 3.2vw, .92rem);
  font-weight: 700;
  color: var(--tx);
  margin-bottom: 14px;
  font-family: var(--mono);
  flex-wrap: wrap;
}
.step-title .icon { flex-shrink: 0; }
.step-title .icon { color: var(--violet2); }
.step-desc { font-size: .78rem; color: var(--mu2); line-height: 1.5; margin-bottom: 18px; }

label {
  display: block;
  font-size: .7rem;
  color: var(--mu2);
  margin-bottom: 5px;
  margin-top: 14px;
  letter-spacing: .04em;
  text-transform: uppercase;
}
input {
  width: 100%;
  padding: 11px 14px;
  background: var(--s2);
  border: 1px solid var(--bd2);
  border-radius: 10px;
  color: var(--tx);
  font-size: .88rem;
  font-family: var(--mono);
  outline: none;
  transition: border-color var(--ease), box-shadow var(--ease);
}
/* iOS не будет масштабировать страницу при фокусе, если шрифт >= 16px */
@media (max-width: 560px) {
  input { font-size: 16px; }
}
input:focus { border-color: var(--violet); box-shadow: 0 0 0 3px var(--violet-glow); }
input::placeholder { color: var(--mu); }
.hint { font-size: .72rem; color: var(--mu); margin-top: 7px; line-height: 1.4; }

.note {
  margin-top: 14px;
  padding: 11px 14px;
  background: rgba(74, 168, 255, 0.07);
  border: 1px solid rgba(74, 168, 255, 0.2);
  border-radius: 10px;
  font-size: .76rem;
  color: var(--mu2);
  line-height: 1.45;
  display: flex;
  gap: 9px;
}
.note .icon { flex-shrink: 0; margin-top: 1px; color: var(--blue); }
.note.warn { background: rgba(255, 200, 87, 0.07); border-color: rgba(255, 200, 87, 0.22); color: #ffd486; }
.note.warn .icon { color: var(--yellow); }
.note b { color: var(--tx); }

.step > button.primary {
  width: 100%;
  margin-top: 22px;
  padding: 13px 10px;
  font-size: clamp(.78rem, 3.2vw, .9rem);
  flex-wrap: wrap;
  text-align: center;
  line-height: 1.3;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: linear-gradient(135deg, var(--violet), var(--fox));
  border: none;
  border-radius: 11px;
  color: #fff;
  font-family: var(--body);
  font-weight: 700;
  cursor: pointer;
  letter-spacing: .2px;
  transition: filter var(--ease), transform .1s, box-shadow var(--ease);
  box-shadow: 0 4px 22px var(--violet-glow);
  position: relative;
  overflow: hidden;
}
/* moving sheen on primary buttons */
.step > button.primary::after {
  content: '';
  position: absolute;
  top: 0; left: -60%;
  width: 40%; height: 100%;
  background: linear-gradient(100deg, transparent, rgba(255, 255, 255, 0.22), transparent);
  transform: skewX(-20deg);
  animation: sheen 3.4s ease-in-out infinite;
  pointer-events: none;
}
@keyframes sheen {
  0%, 60% { left: -60%; }
  100%    { left: 130%; }
}
.step > button.primary:hover { filter: brightness(1.1); box-shadow: 0 4px 34px var(--violet-glow), 0 0 20px var(--fox-glow); transform: translateY(-1px); }
.step > button.primary:active { transform: scale(.98); }
.step > button.primary:disabled { opacity: .35; cursor: not-allowed; box-shadow: none; filter: none; }

.error {
  display: none;
  margin-top: 13px;
  padding: 10px 14px;
  background: rgba(255, 77, 109, 0.1);
  border: 1px solid rgba(255, 77, 109, 0.3);
  border-radius: 9px;
  font-size: .8rem;
  color: var(--red);
  line-height: 1.4;
  gap: 8px;
  align-items: flex-start;
}
.error.show { display: flex; }
.error .icon { flex-shrink: 0; margin-top: 1px; }

.done-wrap { text-align: center; padding: 6px 0; }
.done-icon {
  width: 66px; height: 66px;
  margin: 0 auto 16px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--green-dim);
  border: 1px solid rgba(56, 255, 176, 0.35);
  box-shadow: 0 0 26px rgba(56, 255, 176, 0.35);
}
.done-icon .icon { width: 32px; height: 32px; color: var(--green); }
.done-title { font-family: var(--mono); font-size: 1.15rem; font-weight: 700; color: var(--green); margin-bottom: 8px; }
.done-sub { font-size: .84rem; color: var(--mu2); line-height: 1.5; }
.done-info {
  margin-top: 18px;
  padding: 12px 16px;
  background: rgba(255, 90, 43, 0.10);
  border: 1px solid rgba(255, 90, 43, 0.35);
  border-radius: 11px;
  font-size: clamp(.72rem, 2.8vw, .82rem);
  color: var(--fox2);
  font-family: var(--mono);
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
  overflow-wrap: anywhere;
  text-align: center;
}

.transition-card { text-align: center; padding: 16px 0; }
.transition-icons {
  display: flex; align-items: center; justify-content: center; gap: 12px;
  margin-bottom: 14px;
}
.transition-icons .icon-circle {
  width: 46px; height: 46px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid var(--bd3);
}
.transition-icons .icon-circle.done { background: var(--green-dim); border-color: rgba(56,255,176,.35); color: var(--green); }
.transition-icons .icon-circle.next { background: rgba(255,90,43,.10); border-color: rgba(255,90,43,.3); color: var(--fox2); }
.transition-icons .icon-circle .icon { width: 22px; height: 22px; }
.transition-icons .arrow { color: var(--mu); width: 18px; height: 18px; }
</style>
</head>
<body>
<div class="bg-scene" aria-hidden="true"></div>
<div class="bg-grid" aria-hidden="true"></div>
<canvas id="fx" aria-hidden="true"></canvas>

<main class="card" id="setup-card">
  <div class="brand">
    <span class="brand-orbit"><img class="brand-mark lg" src="/static/kitsune_logo.png" alt="Kitsune"></span>
    <h1 id="setup_title">Kitsune Userbot</h1>
    <p class="sub" id="setup_sub">первоначальная настройка</p>
  </div>

  <!-- Stage badge: показывает к чему относятся текущие данные (Telethon vs Hydrogram) -->
  <div class="stage-badge tele" id="stage_badge">
    <span class="num">1</span>
    <span id="stage_text">Шаг 1 из 2 · регистрация Telethon</span>
  </div>

  <!-- Прогресс по 7 шагам (3 telethon + transit + 3 hydrogram) -->
  <div class="steps-bar" id="dots_bar"></div>

  <!-- ============================================================ -->
  <!-- STEP 1: Telethon — API + телефон                              -->
  <!-- ============================================================ -->
  <div class="step active" id="step1">
    <div class="step-title"><svg class="icon"><use href="#icon-key"/></svg> API-данные Telegram (для Telethon)</div>
    <div class="step-desc">
      Эти данные будут использованы для основного клиента — <b style="color:var(--blue)">Telethon</b>.
    </div>

    <div id="api_block">
      <label>API ID</label>
      <input type="number" id="api_id" placeholder="1234567" autocomplete="off">
      <label>API Hash</label>
      <input type="text" id="api_hash" placeholder="0abc123def456..." autocomplete="off">
      <p class="hint">Получи на <a href="https://my.telegram.org" target="_blank">my.telegram.org</a> → API development tools</p>
    </div>

    <label>Номер телефона</label>
    <input type="tel" id="phone1" placeholder="+79001234567">
    <p class="hint">В международном формате, с символом +</p>

    <div class="error" id="err1"></div>
    <button class="primary" id="btn1" onclick="sendCode1()">Получить код Telegram <svg class="icon"><use href="#icon-arrow-right"/></svg></button>
  </div>

  <!-- ============================================================ -->
  <!-- STEP 2: Telethon — Код подтверждения                          -->
  <!-- ============================================================ -->
  <div class="step" id="step2">
    <div class="step-title"><svg class="icon"><use href="#icon-phone"/></svg> Код подтверждения · Telethon</div>
    <div class="step-desc">Введи код из Telegram (придёт в личные сообщения).</div>

    <label>Код из Telegram</label>
    <input type="text" id="code1" placeholder="12345" maxlength="10" autocomplete="one-time-code">
    <p class="hint">Telethon-сессия будет создана с этим кодом</p>

    <div class="error" id="err2"></div>
    <button class="primary" id="btn2" onclick="signIn1()">Войти (Telethon) <svg class="icon"><use href="#icon-arrow-right"/></svg></button>
  </div>

  <!-- ============================================================ -->
  <!-- STEP 3: Telethon — 2FA                                        -->
  <!-- ============================================================ -->
  <div class="step" id="step3">
    <div class="step-title"><svg class="icon"><use href="#icon-lock"/></svg> Облачный пароль · Telethon</div>
    <div class="step-desc">У тебя включена двухфакторная аутентификация. Введи облачный пароль Telegram.</div>

    <label>Облачный пароль</label>
    <input type="password" id="password1" placeholder="••••••••">

    <div class="error" id="err3"></div>
    <button class="primary" id="btn3" onclick="check2fa1()">Подтвердить (Telethon) <svg class="icon"><use href="#icon-arrow-right"/></svg></button>
  </div>

  <!-- ============================================================ -->
  <!-- STEP 4: Переход между Telethon и Hydrogram                    -->
  <!-- ============================================================ -->
  <div class="step" id="step4">
    <div class="transition-card">
      <div class="transition-icons">
        <span class="icon-circle done"><svg class="icon"><use href="#icon-check"/></svg></span>
        <svg class="icon arrow"><use href="#icon-arrow-right"/></svg>
        <span class="icon-circle next"><svg class="icon"><use href="#icon-refresh"/></svg></span>
      </div>
      <div class="step-title" style="justify-content:center">Telethon-сессия создана!</div>
      <div class="done-info" id="t1_info" style="margin-top:12px"></div>

      <div class="note" style="margin-top:18px;text-align:left">
        <svg class="icon"><use href="#icon-refresh"/></svg>
        <span><b>Теперь нужно создать вторую сессию — для Hydrogram.</b><br>
        Hydrogram отвечает за работу с медиа (фото, видео, голосовые)
        и работает параллельно с Telethon.</span>
      </div>

      <div class="note warn" style="text-align:left">
        <svg class="icon"><use href="#icon-alert"/></svg>
        <span>Сейчас Telegram пришлёт <b>новый код</b> в Saved Messages —
        он будет нужен для Hydrogram. Введи те же самые данные ещё раз
        (API ID, API Hash и номер телефона уже сохранены, тебе нужно будет ввести только код и пароль).</span>
      </div>
    </div>

    <button class="primary" id="btn4" onclick="startHydro()">Продолжить · создать Hydrogram-сессию <svg class="icon"><use href="#icon-arrow-right"/></svg></button>
  </div>

  <!-- ============================================================ -->
  <!-- STEP 5: Hydrogram — телефон (повторный ввод)                  -->
  <!-- ============================================================ -->
  <div class="step" id="step5">
    <div class="step-title"><svg class="icon"><use href="#icon-phone"/></svg> Подтверждение номера · Hydrogram</div>
    <div class="step-desc">
      Подтверди номер для <b style="color:var(--fox2)">Hydrogram-клиента</b>.
      Это вторая, независимая сессия (для медиа).
    </div>

    <label>Номер телефона</label>
    <input type="tel" id="phone2" placeholder="+79001234567">
    <p class="hint">Тот же самый номер. По умолчанию подставлен.</p>

    <div class="error" id="err5"></div>
    <button class="primary" id="btn5" onclick="sendCode2()">Получить код для Hydrogram <svg class="icon"><use href="#icon-arrow-right"/></svg></button>
  </div>

  <!-- ============================================================ -->
  <!-- STEP 6: Hydrogram — код                                       -->
  <!-- ============================================================ -->
  <div class="step" id="step6">
    <div class="step-title"><svg class="icon"><use href="#icon-phone"/></svg> Код подтверждения · Hydrogram</div>
    <div class="step-desc">
      Telegram прислал <b>новый код</b> для Hydrogram. Введи его сюда.
    </div>

    <label>Код из Telegram</label>
    <input type="text" id="code2" placeholder="12345" maxlength="10" autocomplete="one-time-code">
    <p class="hint">Это <b>другой код</b>, не тот, что был для Telethon</p>

    <div class="error" id="err6"></div>
    <button class="primary" id="btn6" onclick="signIn2()">Войти (Hydrogram) <svg class="icon"><use href="#icon-arrow-right"/></svg></button>
  </div>

  <!-- ============================================================ -->
  <!-- STEP 7: Hydrogram — 2FA                                       -->
  <!-- ============================================================ -->
  <div class="step" id="step7">
    <div class="step-title"><svg class="icon"><use href="#icon-lock"/></svg> Облачный пароль · Hydrogram</div>
    <div class="step-desc">Введи тот же облачный пароль Telegram (это нормально, Hydrogram его не сохранил).</div>

    <label>Облачный пароль</label>
    <input type="password" id="password2" placeholder="••••••••">

    <div class="error" id="err7"></div>
    <button class="primary" id="btn7" onclick="check2fa2()">Подтвердить (Hydrogram) <svg class="icon"><use href="#icon-arrow-right"/></svg></button>
  </div>

  <!-- ============================================================ -->
  <!-- STEP 8 (final): Готово                                        -->
  <!-- ============================================================ -->
  <div class="step" id="step8">
    <div class="done-wrap">
      <div class="done-icon"><svg class="icon"><use href="#icon-check-circle"/></svg></div>
      <div class="done-title">Готово!</div>
      <div class="done-sub">
        Обе сессии успешно созданы.<br>
        Kitsune запускается… можешь закрыть это окно.
      </div>
      <div class="done-info" id="done_info"></div>
    </div>
  </div>
</main>

<!-- inline icon sprite -->
<svg aria-hidden="true" style="position:absolute;width:0;height:0;overflow:hidden">
  <symbol id="icon-key" viewBox="0 0 24 24"><path d="M14.5 6.5a4 4 0 1 1-5.66 5.66L4 17v3h3l4.84-4.84A4 4 0 0 1 14.5 6.5Z"/><circle cx="16" cy="8" r="1.2" fill="currentColor" stroke="none"/></symbol>
  <symbol id="icon-phone" viewBox="0 0 24 24"><rect x="7" y="2" width="10" height="20" rx="2"/><line x1="11" y1="18" x2="13" y2="18"/></symbol>
  <symbol id="icon-lock" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></symbol>
  <symbol id="icon-check" viewBox="0 0 24 24"><polyline points="4 13 9 18 20 6"/></symbol>
  <symbol id="icon-check-circle" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><polyline points="8 12.5 11 15.5 16 9"/></symbol>
  <symbol id="icon-arrow-right" viewBox="0 0 24 24"><line x1="4" y1="12" x2="19" y2="12"/><polyline points="13 6 19 12 13 18"/></symbol>
  <symbol id="icon-alert" viewBox="0 0 24 24"><path d="M12 3 2 20h20L12 3Z"/><line x1="12" y1="10" x2="12" y2="14"/><circle cx="12" cy="17" r=".6" fill="currentColor" stroke="none"/></symbol>
  <symbol id="icon-refresh" viewBox="0 0 24 24"><path d="M4 4v6h6"/><path d="M20 20v-6h-6"/><path d="M5 13a7 7 0 0 1 12-4.6L20 10"/><path d="M19 11a7 7 0 0 1-12 4.6L4 14"/></symbol>
</svg>

<script src="/static/fx.js" defer></script>

<script>
let HYDRO_ONLY = false;     // режим повторной регистрации только Hydrogram
let SAVED_PHONE = '';        // номер с шага 1 (подставится в шаге 5)

// ============================================================
// Карта шагов:
//   step1: telethon - api + phone
//   step2: telethon - code
//   step3: telethon - 2fa (опционально)
//   step4: TRANSITION (Telethon готов → начинаем Hydrogram)
//   step5: hydrogram - phone confirm (по умолчанию = SAVED_PHONE)
//   step6: hydrogram - code
//   step7: hydrogram - 2fa (опционально)
//   step8: ALL DONE
// ============================================================

// Конфиг прогресса (8 точек)
const STAGE_MAP = {
  1: {stage:'tele', label:'Шаг 1 из 2 · регистрация Telethon'},
  2: {stage:'tele', label:'Шаг 1 из 2 · регистрация Telethon'},
  3: {stage:'tele', label:'Шаг 1 из 2 · регистрация Telethon'},
  4: {stage:'transit', label:'Переход → Hydrogram'},
  5: {stage:'hydro', label:'Шаг 2 из 2 · регистрация Hydrogram'},
  6: {stage:'hydro', label:'Шаг 2 из 2 · регистрация Hydrogram'},
  7: {stage:'hydro', label:'Шаг 2 из 2 · регистрация Hydrogram'},
  8: {stage:'done', label:'Готово'},
};

// Спрашиваем у бэка режим, ещё до взаимодействия с пользователем.
(async()=>{
  try{
    const r = await fetch('/api/mode');
    const j = await r.json();
    HYDRO_ONLY = !!(j && j.hydrogram_only);
    if(HYDRO_ONLY){
      // В режиме hydrogram_only сразу показываем шаг 5 (телефон Hydrogram).
      document.getElementById('setup_title').textContent = 'Kitsune · повторная регистрация';
      document.getElementById('setup_sub').textContent = 'Только Hydrogram (Telethon уже настроен)';
      // прячем шаги 1-4
      // показываем сразу step5, в нём префилл телефона из cfg, если есть
      if (j.phone) {
        SAVED_PHONE = j.phone;
        document.getElementById('phone2').value = j.phone;
      }
      show(5);
    } else {
      buildDots();
      show(1);
    }
  }catch(_){
    // offline / 404 → считаем что обычный режим
    buildDots();
    show(1);
  }
})();

function buildDots(){
  const total = HYDRO_ONLY ? 3 : 7;  // step4 (transit) не считаем точкой
  const bar = document.getElementById('dots_bar');
  let html = '';
  for(let i=0;i<total;i++){
    html += '<div class="step-dot" id="d'+(i+1)+'"></div>';
  }
  bar.innerHTML = html;
}

function setProgress(stepNum){
  // Маппим step -> dot index (без transit-step4)
  let dotIdx = stepNum;
  if (HYDRO_ONLY) {
    dotIdx = stepNum - 4;  // step5->1, step6->2, step7->3
  } else {
    if (stepNum === 4) dotIdx = 4;       // переход = после 3-й точки
    else if (stepNum >= 5) dotIdx = stepNum - 1; // step5->4, step6->5, step7->6, step8->7
  }
  const total = HYDRO_ONLY ? 3 : 7;
  for(let i=1;i<=total;i++){
    const d = document.getElementById('d'+i);
    if(!d) continue;
    d.className='step-dot';
    const stage = HYDRO_ONLY ? 'hydro' : (i<=3 ? 'tele' : 'hydro');
    if(i < dotIdx) d.classList.add('done');
    else if(i === dotIdx) {
      d.classList.add('active');
      if(stage === 'tele') d.classList.add('tele');
    }
  }
}

function setStageBadge(stepNum){
  const cfg = STAGE_MAP[stepNum];
  if(!cfg) return;
  const el = document.getElementById('stage_badge');
  const txt = document.getElementById('stage_text');
  el.classList.remove('tele','hydro');
  if(cfg.stage === 'tele'){
    el.classList.add('tele');
    el.querySelector('.num').textContent = '1';
  } else if(cfg.stage === 'hydro'){
    el.classList.add('hydro');
    el.querySelector('.num').textContent = HYDRO_ONLY ? '!' : '2';
  } else if(cfg.stage === 'transit'){
    el.classList.add('hydro');
    el.querySelector('.num').textContent = '→';
  } else {
    el.style.display = 'none';
    return;
  }
  el.style.display = 'flex';
  txt.textContent = cfg.label;
}

function show(n){
  document.querySelectorAll('.step').forEach(s=>s.classList.remove('active'));
  const target = document.getElementById('step'+n);
  if(target) target.classList.add('active');
  setStageBadge(n);
  setProgress(n);
}

function showErr(n,msg){
  const el=document.getElementById('err'+n);
  if(!el) return;
  el.innerHTML = msg ? '<svg class="icon"><use href="#icon-alert"/></svg><span>'+msg+'</span>' : '';
  el.classList.toggle('show', !!msg);
}

function setBtn(id,text,disabled){
  const b=document.getElementById(id);
  if(!b) return;
  b.textContent=text;
  b.disabled=disabled;
}

async function post(url,data){
  const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  return r.json();
}

// ============================================================
// Telethon flow (steps 1..3)
// ============================================================

async function sendCode1(){
  const phone=document.getElementById('phone1').value.trim();
  if(!phone){showErr(1,'Введи номер телефона');return;}
  const api_id=document.getElementById('api_id').value.trim();
  const api_hash=document.getElementById('api_hash').value.trim();
  if(!api_id||!api_hash){showErr(1,'Заполни API ID и API Hash');return;}

  SAVED_PHONE = phone;

  setBtn('btn1','Отправляем код Telegram…',true);
  const res=await post('/api/sendcode',{api_id:parseInt(api_id), api_hash, phone, stage:'telethon'});
  setBtn('btn1','Получить код Telegram →',false);

  if(res.ok){
    showErr(1,'');
    show(2);
  } else {
    showErr(1,res.error||'Ошибка');
  }
}

async function signIn1(){
  const code=document.getElementById('code1').value.trim();
  if(!code){showErr(2,'Введи код');return;}

  setBtn('btn2','Проверяем…',true);
  const res=await post('/api/signin',{code, stage:'telethon'});
  setBtn('btn2','Войти (Telethon) →',false);

  if(res.ok){
    showErr(2,'');
    document.getElementById('t1_info').textContent = res.message || 'Telethon: OK';
    show(4);  // переход к Hydrogram
  } else if(res.need_2fa){
    showErr(2,'');
    show(3);
  } else {
    showErr(2,res.error||'Неверный код');
  }
}

async function check2fa1(){
  const pwd=document.getElementById('password1').value;
  if(!pwd){showErr(3,'Введи пароль');return;}

  setBtn('btn3','Проверяем…',true);
  const res=await post('/api/2fa',{password:pwd, stage:'telethon'});
  setBtn('btn3','Подтвердить (Telethon) →',false);

  if(res.ok){
    showErr(3,'');
    document.getElementById('t1_info').textContent = res.message || 'Telethon: OK';
    show(4);
  } else {
    showErr(3,res.error||'Неверный пароль');
  }
}

// ============================================================
// Transition (step 4) → начинаем Hydrogram
// ============================================================

function startHydro(){
  // Префилл телефона
  if(SAVED_PHONE){
    document.getElementById('phone2').value = SAVED_PHONE;
  }
  show(5);
}

// ============================================================
// Hydrogram flow (steps 5..7)
// ============================================================

async function sendCode2(){
  const phone=document.getElementById('phone2').value.trim();
  if(!phone){showErr(5,'Введи номер телефона');return;}

  SAVED_PHONE = phone;

  setBtn('btn5','Отправляем код Telegram…',true);
  const res=await post('/api/sendcode',{phone, stage:'hydrogram'});
  setBtn('btn5','Получить код для Hydrogram →',false);

  if(res.ok){
    showErr(5,'');
    show(6);
  } else {
    showErr(5,res.error||'Ошибка');
  }
}

async function signIn2(){
  const code=document.getElementById('code2').value.trim();
  if(!code){showErr(6,'Введи код');return;}

  setBtn('btn6','Проверяем…',true);
  const res=await post('/api/signin',{code, stage:'hydrogram'});
  setBtn('btn6','Войти (Hydrogram) →',false);

  if(res.ok){
    showErr(6,'');
    document.getElementById('done_info').textContent = res.message || 'Hydrogram: OK';
    show(8);
  } else if(res.need_2fa){
    showErr(6,'');
    show(7);
  } else {
    showErr(6,res.error||'Неверный код');
  }
}

async function check2fa2(){
  const pwd=document.getElementById('password2').value;
  if(!pwd){showErr(7,'Введи пароль');return;}

  setBtn('btn7','Проверяем…',true);
  const res=await post('/api/2fa',{password:pwd, stage:'hydrogram'});
  setBtn('btn7','Подтвердить (Hydrogram) →',false);

  if(res.ok){
    showErr(7,'');
    document.getElementById('done_info').textContent = res.message || 'Hydrogram: OK';
    show(8);
  } else {
    showErr(7,res.error||'Неверный пароль');
  }
}
</script>
</body>
</html>
"""

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
        self._hydrogram_only: bool = bool(hydrogram_only)
        self._telethon_success: bool = False
        self._hydrogram_success: bool = False
        self._hydro_client: Any = None
        self._hydro_phone: str | None = None
        self._hydro_phone_code_hash: str | None = None
    async def start(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_post("/api/sendcode", self._api_sendcode)
        app.router.add_post("/api/signin", self._api_signin)
        app.router.add_post("/api/2fa", self._api_2fa)
        app.router.add_get("/api/mode", self._api_mode)
        app.router.add_get("/static/{filename}", self._static)
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
        if self._hydro_client is not None:
            try:
                await self._hydro_client.disconnect()
            except Exception:
                pass
            self._hydro_client = None
        if self._runner:
            await self._runner.cleanup()
    def get_client(self) -> Any:
        return self._client
    def hydrogram_only_success(self) -> bool:
        return bool(self._hydrogram_success)
    async def _static(self, request: web.Request) -> web.Response:
        filename = request.match_info.get("filename", "")
        if (not filename) or ("/" in filename) or ("\\" in filename) or (".." in filename):
            return web.Response(status=404, text="not found")
        path = (_STATIC_DIR / filename).resolve()
        try:
            path.relative_to(_STATIC_DIR)
        except ValueError:
            return web.Response(status=404, text="not found")
        if not path.is_file():
            return web.Response(status=404, text="not found")
        return web.FileResponse(path)
    async def _index(self, _: web.Request) -> web.Response:
        return web.Response(text=_HTML, content_type="text/html")
    async def _api_mode(self, _: web.Request) -> web.Response:
        cfg = self._get_config() or {}
        return web.json_response({
            "hydrogram_only": bool(self._hydrogram_only),
            "api_id": cfg.get("api_id") if self._hydrogram_only else None,
            "api_hash": cfg.get("api_hash") if self._hydrogram_only else None,
            "phone": cfg.get("phone") if self._hydrogram_only else None,
        })
    async def _api_sendcode(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return self._err("Невалидный JSON")
        stage = str(data.get("stage", "")).strip().lower()
        if not stage:
            stage = "hydrogram" if self._hydrogram_only else "telethon"
        if stage == "hydrogram":
            return await self._api_sendcode_hydrogram(data)
        return await self._api_sendcode_telethon(data)
    async def _api_signin(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return self._err("Невалидный JSON")
        stage = str(data.get("stage", "")).strip().lower()
        if not stage:
            stage = "hydrogram" if self._hydrogram_only else "telethon"
        if stage == "hydrogram":
            return await self._api_signin_hydrogram(data)
        return await self._api_signin_telethon(data)
    async def _api_2fa(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return self._err("Невалидный JSON")
        stage = str(data.get("stage", "")).strip().lower()
        if not stage:
            stage = "hydrogram" if self._hydrogram_only else "telethon"
        if stage == "hydrogram":
            return await self._api_2fa_hydrogram(data)
        return await self._api_2fa_telethon(data)
    async def _build_proxy(self, cfg: dict) -> tuple[Any, dict]:
        proxy_cfg = cfg.get("proxy") or {}
        proxy = None
        extra: dict = {}
        if not (proxy_cfg.get("host") and proxy_cfg.get("port")):
            return proxy, extra
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
            return proxy, extra
        if ptype == "MTPROTO":
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
            logger.info(
                "setup: using MTProto proxy → %s:%s (%s)",
                proxy_cfg["host"], proxy_cfg["port"],
                (conn_cls.__name__ if conn_cls else "auto"),
            )
        else:
            try:
                import socks as _socks
                _type_map = {
                    "SOCKS5": _socks.SOCKS5,
                    "SOCKS4": _socks.SOCKS4,
                    "HTTP": _socks.HTTP,
                    "HTTPS": _socks.HTTP,
                }
                proxy = (
                    _type_map.get(ptype, _socks.SOCKS5),
                    str(proxy_cfg["host"]),
                    int(proxy_cfg["port"]),
                    True,
                    proxy_cfg.get("username") or None,
                    proxy_cfg.get("password") or None,
                )
                logger.info(
                    "setup: using %s proxy → %s:%s",
                    ptype, proxy_cfg["host"], proxy_cfg["port"],
                )
            except ImportError:
                logger.warning("setup: PySocks not installed, proxy disabled")
        return proxy, extra
    async def _api_sendcode_telethon(self, data: dict) -> web.Response:
        try:
            api_id = int(data["api_id"])
            api_hash = str(data["api_hash"]).strip()
            self._phone = str(data["phone"]).strip()
            cfg = self._get_config()
            cfg["api_id"] = api_id
            cfg["api_hash"] = api_hash
            cfg["phone"] = self._phone
            self._save_config(cfg)
            from ..tl_cache import KitsuneTelegramClient
            from telethon.sessions import MemorySession
            from pathlib import Path
            DATA_DIR = Path.home() / ".kitsune"
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            proxy, extra = await self._build_proxy(cfg)
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
            logger.exception("setup: /api/sendcode (telethon) error")
            return self._err(str(exc))
    async def _api_signin_telethon(self, data: dict) -> web.Response:
        try:
            code = str(data["code"]).strip()
            self._last_code = code
            from telethon.errors import SessionPasswordNeededError
            try:
                me = await self._client.sign_in(
                    self._phone, code, phone_code_hash=self._phone_hash
                )
                await self._save_telethon_session(me)
                return web.json_response({
                    "ok": True,
                    "message": f"👤 {me.first_name}  |  id: {me.id}",
                })
            except SessionPasswordNeededError:
                return web.json_response({"ok": False, "need_2fa": True})
        except Exception as exc:
            logger.exception("setup: /api/signin (telethon) error")
            return self._err(str(exc))
    async def _api_2fa_telethon(self, data: dict) -> web.Response:
        try:
            password = str(data.get("password", "")).strip()
            if not password:
                return self._err("Пароль не может быть пустым")
            self._last_password = password
            from telethon.errors import PasswordHashInvalidError, FloodWaitError
            try:
                me = await self._client.sign_in(password=password)
            except PasswordHashInvalidError:
                return web.json_response({
                    "ok": False,
                    "error": "Неверный пароль. Попробуй ещё раз.",
                    "wrong_password": True,
                })
            except FloodWaitError as e:
                return web.json_response({
                    "ok": False,
                    "error": f"Слишком много попыток. Подожди {e.seconds} секунд.",
                    "flood": True,
                })
            await self._save_telethon_session(me)
            return web.json_response({
                "ok": True,
                "message": f"👤 {me.first_name}  |  id: {me.id}",
            })
        except Exception as exc:
            logger.exception("setup: /api/2fa (telethon) error")
            return self._err(str(exc))
    async def _save_telethon_session(self, me: Any) -> None:
        from telethon.sessions import SQLiteSession
        from pathlib import Path
        DATA_DIR = Path.home() / ".kitsune"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        session_file = DATA_DIR / "kitsune.session"
        for _suf in ("", "-wal", "-shm", "-journal"):
            _p = Path(str(session_file) + _suf)
            try:
                if _p.exists():
                    _p.unlink()
            except Exception:
                pass
        session = SQLiteSession(str(DATA_DIR / "kitsune"))
        session.set_dc(
            self._client.session.dc_id,
            self._client.session.server_address,
            self._client.session.port,
        )
        session.auth_key = self._client.session.auth_key
        session.save()
        try:
            import os as _os
            if session_file.exists():
                _os.chmod(session_file, 0o644)
        except Exception:
            pass
        self._client.session = session
        self._client.tg_id = me.id
        self._client.tg_me = me
        self._telethon_success = True
        logger.info("setup: Telethon session создана и сохранена")
    async def _api_sendcode_hydrogram(self, data: dict) -> web.Response:
        try:
            self._hydro_phone = str(data.get("phone", "")).strip() or self._phone or ""
            if not self._hydro_phone:
                return self._err("Введи номер телефона")
            cfg = self._get_config() or {}
            api_id = int(cfg.get("api_id") or 0)
            api_hash = str(cfg.get("api_hash") or "")
            if not api_id or not api_hash:
                return self._err(
                    "В config.toml не найдены api_id / api_hash. "
                    "Сначала пройди регистрацию Telethon."
                )
            from pathlib import Path as _Path
            DATA_DIR = _Path.home() / ".kitsune"
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            hydro_session_file = DATA_DIR / "kitsune_hydro.session"
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
                phone_number=self._hydro_phone,
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
            if self._hydro_client is not None:
                try:
                    await self._hydro_client.disconnect()
                except Exception:
                    pass
                self._hydro_client = None
            self._hydro_client = HydroClient(**kwargs)
            await self._hydro_client.connect()
            sent = await asyncio.wait_for(
                self._hydro_client.send_code(self._hydro_phone), timeout=30.0,
            )
            self._hydro_phone_code_hash = sent.phone_code_hash
            return web.json_response({"ok": True})
        except asyncio.TimeoutError:
            return self._err("Не удалось подключиться к Telegram (timeout). Проверь связь.")
        except Exception as exc:
            logger.exception("setup: /api/sendcode (hydrogram) error")
            return self._err(str(exc))
    async def _api_signin_hydrogram(self, data: dict) -> web.Response:
        try:
            code = str(data.get("code", "")).strip()
            if not code:
                return self._err("Введи код")
            if (
                self._hydro_client is None
                or not self._hydro_phone
                or not self._hydro_phone_code_hash
            ):
                return self._err(
                    "Сессия потеряна. Перезапусти мастер и запроси код заново."
                )
            try:
                from hydrogram.errors import (
                    SessionPasswordNeeded as _HydroSessionPasswordNeeded,
                )
            except Exception:
                _HydroSessionPasswordNeeded = Exception                            
            try:
                me = await self._hydro_client.sign_in(
                    self._hydro_phone,
                    self._hydro_phone_code_hash,
                    code,
                )
            except _HydroSessionPasswordNeeded:
                return web.json_response({"ok": False, "need_2fa": True})
            await self._finalize_hydrogram()
            first_name = getattr(me, "first_name", "") or "Готово"
            user_id = getattr(me, "id", 0)
            return web.json_response({
                "ok": True,
                "message": f"👤 {first_name}  |  id: {user_id}",
            })
        except Exception as exc:
            logger.exception("setup: /api/signin (hydrogram) error")
            return self._err(str(exc))
    async def _api_2fa_hydrogram(self, data: dict) -> web.Response:
        try:
            password = str(data.get("password", "")).strip()
            if not password:
                return self._err("Пароль не может быть пустым")
            if self._hydro_client is None:
                return self._err(
                    "Сессия потеряна. Перезапусти мастер и запроси код заново."
                )
            try:
                from hydrogram.errors import (
                    PasswordHashInvalid as _HydroPasswordHashInvalid,
                )
            except Exception:
                _HydroPasswordHashInvalid = Exception                            
            try:
                me = await self._hydro_client.check_password(password)
            except _HydroPasswordHashInvalid:
                return web.json_response({
                    "ok": False,
                    "error": "Неверный пароль. Попробуй ещё раз.",
                    "wrong_password": True,
                })
            await self._finalize_hydrogram()
            first_name = getattr(me, "first_name", "") or "Готово"
            user_id = getattr(me, "id", 0)
            return web.json_response({
                "ok": True,
                "message": f"👤 {first_name}  |  id: {user_id}",
            })
        except Exception as exc:
            logger.exception("setup: /api/2fa (hydrogram) error")
            return self._err(str(exc))
    async def _finalize_hydrogram(self) -> None:
        if self._hydro_client is not None:
            try:
                await self._hydro_client.disconnect()
            except Exception:
                logger.debug("setup: hydro disconnect failed", exc_info=True)
            self._hydro_client = None
        self._hydrogram_success = True
        logger.info(
            "setup: Hydrogram-сессия успешно создана и сохранена на диск"
        )
        if not self._hydrogram_only:
            pass
        self._done.set()
    @staticmethod
    def _err(msg: str) -> web.Response:
        return web.json_response({"ok": False, "error": msg})
