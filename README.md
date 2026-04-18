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

## ⚠️ Совместимость с Hikka и Heroku

**Модули Hikka и Heroku в данный момент не поддерживаются.**

Попытка загрузить модули, написанные под Hikka/Heroku, приведёт к ошибкам — у них другой API (`from hikka.modules import ...` и т.д.), несовместимый с архитектурой Kitsune.

> **Не переживай!** Скоро появится нативная библиотека модулей для Kitsune. Следите за обновлениями.

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
| ⚙️ | Конфигуратор | Интерактивная настройка через веб-интерфейс |
| 📋 | TOML конфиг | Читаемый конфиг с поддержкой MTProto прокси |
| 📱 | Мультиплатформа | Termux, Ubuntu, UserLand — один установщик |

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

### Вручную
```bash
git clone https://github.com/KitsuneX-dev/Kitsune
cd Kitsune
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m kitsune
```

После запуска открой `http://localhost:8080` в браузере и пройди регистрацию — введи `api_id` / `api_hash` с [my.telegram.org](https://my.telegram.org).

---

## Запуск

### Termux
```bash
python -m kitsune
```

### Ubuntu / Debian
```bash
source venv/bin/activate
python -m kitsune
# или без активации:
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

## Бэкапы

При первом запуске бот предложит выбрать интервал авто-бэкапа: **2ч / 4ч / 6ч / 12ч / 24ч**.
Бэкапы отправляются в группу **KitsuneBackup**, сообщения пишет встроенный бот (не ты).
Восстановление — ответь на файл бэкапа командой `.restore`.

---

## Лицензия

AGPLv3 © Yushi ([@Mikasu32](https://t.me/Mikasu32)), 2024–2026
