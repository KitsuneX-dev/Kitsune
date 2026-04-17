<div align="center">

<img src="banner.png" alt="Kitsune Userbot" width="860"/>

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Version](https://img.shields.io/badge/Версия-1.2.9-blueviolet?style=flat-square)](https://github.com/KitsuneX-dev/Kitsune/releases/tag/v1.2.9)
[![License](https://img.shields.io/badge/License-AGPLv3-blue?style=flat-square)](LICENSE)
[![Telegram](https://img.shields.io/badge/Автор-@Mikasu32-2CA5E0?style=flat-square&logo=telegram)](https://t.me/Mikasu32)

**Мощный userbot для Telegram — быстрый, безопасный, расширяемый.**

</div>

---

## О проекте

Kitsune запускается локально на твоём устройстве и расширяет Telegram через простые команды с префиксом. Двойной клиентский стек (Telethon + Hydrogram), AST-сканер модулей, зашифрованные бэкапы и интерактивный конфигуратор — всё из коробки.

---

## ⚠️ О совместимости с Hikka и Heroku

**Модули Hikka и Heroku в данный момент не поддерживаются.**

Попытка загрузить модули, написанные под Hikka/Heroku, приведёт к ошибкам — у них другой API (`from hikka.modules import ...` и т.д.), несовместимый с архитектурой Kitsune.

> **Не переживайте!** В ближайшее время будет создана отдельная библиотека модулей, написанных нативно под Kitsune. Следите за обновлениями в [@Mikasu32](https://t.me/Mikasu32).

---

## Возможности

| | Функция | Описание |
|---|---|---|
| ⚡ | Двойной стек | Telethon (основной) + Hydrogram (вторичный) |
| 🔒 | AST-сканер | Блокирует опасный код модулей до `exec()` |
| 🛡️ | Rate Limiter | Token-bucket алгоритм — защита от флуд-бана |
| 💾 | Async SQLite WAL | Не теряет данные при крэше |
| 🤖 | aiogram 3.x | Встроенный бот для уведомлений и бэкапов |
| 📦 | Авто-бэкап | Зашифрованные резервные копии БД по расписанию |
| ⚙️ | Конфигуратор | Интерактивная настройка модулей через кнопки |
| 📋 | TOML конфиг | Читаемый конфиг с поддержкой MTProto прокси |
| 📱 | Termux + Ubuntu + UserLand | Один установщик для всех окружений |
| 📁 | Папка Kitsune | Все служебные группы собраны в одну папку Telegram |

---

## Встроенные модули

| Модуль | Команды | Описание |
|---|---|---|
| Backup | `.backup` `.restore` | Бэкап и восстановление БД |
| Config | `.config` `.fconfig` | Интерактивная настройка модулей |
| Evaluator | `.e` `.ex` `.sh` | Python / Shell код |
| Health | `.health` `.monitor` | Мониторинг системы |
| Help | `.help` | Список команд |
| Loader | `.dlmod` `.loadmod` `.mods` | Управление модулями |
| Notifier | `.resetbot` `.mybots` `.setbot` | Бот-нотификатор |
| Pastebin | `.paste` | Загрузка текста на pastebin |
| Ping | `.ping` `.me` `.id` | Пинг, аптайм, информация |
| Security | `.addsudo` `.delsudo` | Права доступа |
| Settings | `.prefix` `.lang` `.autodel` `.info` | Настройки |
| Updater | `.update` `.restart` | Обновление и перезапуск |

---

## Установка

### Termux (Android)
```bash
curl -s https://raw.githubusercontent.com/KitsuneX-dev/Kitsune/main/termux.sh | bash
```

### Ubuntu / Debian / UserLand
```bash
curl -s https://raw.githubusercontent.com/KitsuneX-dev/Kitsune/main/install.sh | bash
```

> Установщик автоматически определяет среду: обычный Ubuntu, Termux или UserLand — и настраивает всё под неё.

### Вручную
```bash
git clone https://github.com/KitsuneX-dev/Kitsune
cd Kitsune
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m kitsune
```

После запуска открой `http://localhost:8080` в браузере и введи `api_id` / `api_hash` с [my.telegram.org](https://my.telegram.org).

---

## Запуск

### Termux
```bash
python -m kitsune
```

### Ubuntu / Debian — через виртуальное окружение *(рекомендуется)*
```bash
# Вариант 1 — активировать и запустить
source venv/bin/activate
python -m kitsune

# Вариант 2 — напрямую без активации
venv/bin/python -m kitsune
```

### UserLand (Ubuntu на Android)
```bash
bash ~/start_kitsune.sh
```

> **Порт 8080 занят?**
> Укажи другой в `config.toml` → `web_port = 8081`, затем открой `http://localhost:8081`.

---

## ⚠️ Блокировки РКН

Если после запуска в консоли **тишина** (нет ошибок, но бот не загружается) — соединение с Telegram блокируется провайдером.

**Вариант 1 — VPN**
Включи любой VPN перед запуском. При смене локации бот автоматически переподключится.

**Вариант 2 — MTProto прокси** *(без VPN)*

Создай `config.toml` в папке проекта:
```toml
[proxy]
type   = "MTPROTO"
host   = "АДРЕС_ПРОКСИ"
port   = 443
secret = "СЕКРЕТ_ПРОКСИ"
```

Рабочие MTProto прокси: [@MTProxyT](https://t.me/MTProxyT), [@proxyme](https://t.me/proxyme).

---

## Конфигурация

Файл `config.toml` создаётся в папке проекта (`~/Kitsune/config.toml`):

```toml
api_id   = 123456
api_hash = "abcdef..."
prefix   = "."
lang     = "ru"
web_port = 8080

[proxy]
type   = "MTPROTO"
host   = "127.0.0.1"
port   = 443
secret = "00000000000000000000000000000000"
```

`api_id` и `api_hash` — на [my.telegram.org](https://my.telegram.org). Блок `[proxy]` опционален.

---

## Модули

### Загрузка
```
.dlmod https://raw.githubusercontent.com/someone/repo/main/mymodule.py
```
Все модули проходят AST-сканирование перед выполнением и восстанавливаются после перезапуска.

### Настройка через .config
```
.config                                    — конфигуратор с выбором модуля через кнопки
.config <модуль>                           — сразу к настройкам конкретного модуля
.fconfig <модуль> <параметр> <значение>   — быстрая установка без UI
```

---

## Бэкапы

При первом запуске бот предложит выбрать интервал авто-бэкапа: **2ч / 4ч / 6ч / 12ч / 24ч**.
Бэкапы отправляются в группу **KitsuneBackup**, сообщения пишет встроенный бот (не ты).
Восстановление — ответь на файл бэкапа командой `.restore`.

> Группа **KitsuneBackup** и все служебные группы автоматически собираются в папку **🦊 Kitsune** у тебя в Telegram.

---

## Служебные группы Telegram

После старта Kitsune автоматически создаёт и организует:

| Группа | Назначение |
|---|---|
| `KitsuneBackup` | Зашифрованные бэкапы базы данных |
| `Kitsune-logs` | Системные логи и стартовый баннер |
| `kitsune-assets` | Служебные файлы |

Все группы собираются в папку **🦊 Kitsune** и уходят в архив Telegram (не засоряют список чатов). Сообщения в них отправляет встроенный бот — не твой аккаунт.

---

## Лицензия

AGPLv3 © Yushi ([@Mikasu32](https://t.me/Mikasu32)), 2024–2026
