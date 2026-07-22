<div align="center">

<img src="banner.png" alt="Kitsune Userbot" width="860"/>

<br/>

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Version](https://img.shields.io/badge/Версия-1.4.3-blueviolet?style=flat-square)](https://github.com/KitsuneX-dev/Kitsune/releases/tag/v1.4.3)
[![License](https://img.shields.io/badge/License-AGPLv3-blue?style=flat-square)](LICENSE)
[![Telegram](https://img.shields.io/badge/Автор-@Mikasu32-2CA5E0?style=flat-square&logo=telegram)](https://t.me/Mikasu32)

*Быстрый · Безопасный · Расширяемый*

</div>

---

## 🦊 О проекте

Kitsune — userbot для Telegram, который живёт прямо на твоём устройстве. Никаких облаков, никаких посредников. Двойной клиентский стек (Telethon + Hydrogram), AST-сканер модулей, авто-бэкапы и интерактивный конфигуратор — всё из коробки.

> **Hikka / Heroku модули не поддерживаются.** У них другой API, несовместимый с архитектурой Kitsune. Нативная библиотека модулей скоро появится — следите за обновлениями.

---

## ✨ Возможности

| | Функция | Описание |
|:---:|---|---|
| ⚡ | Двойной стек | Telethon (основной) + Hydrogram (вторичный) |
| 🔒 | AST-сканер | Блокирует опасный код до `exec()` |
| 🛡️ | Rate Limiter | Token-bucket алгоритм — защита от флуд-бана |
| 💾 | Async SQLite WAL | Не теряет данные при крэше |
| 🤖 | aiogram 3.x | Встроенный бот для уведомлений и бэкапов |
| 📦 | Авто-бэкап | Автоматические резервные копии по расписанию |
| ⚙️ | Конфигуратор | Интерактивная настройка через веб-интерфейс |
| 📋 | TOML конфиг | Читаемый конфиг с поддержкой прокси |
| 📱 | Мультиплатформа | Termux, Ubuntu, UserLand — один установщик |

---

## 📋 Требования

- **Python 3.13**
- Учётные данные API с [my.telegram.org/apps](https://my.telegram.org/apps)
- VPN или SOCKS5-прокси **обязателен для пользователей из РФ** *(подробнее ниже)*

---

## 🚀 Установка

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

> **Порт 8080 занят?** Укажи другой в `config.toml` → `web_port = 8081`

---

## ▶️ Запуск

```bash
# Termux
python -m kitsune

# Ubuntu / Debian
source venv/bin/activate && python -m kitsune

# UserLand
python -m kitsune
# или без активации venv:
venv/bin/python -m kitsune
```

---

## 🌐 Прокси и VPN

> 🚨 **Пользователям из РФ:** без VPN или работающего прокси бот не запустится — Telegram заблокирован на уровне провайдера.

### Вариант 1 — VPN *(рекомендуется)*
Просто включи VPN перед запуском. При смене IP бот переподключится автоматически.

### Вариант 2 — MTProxy + SOCKS5

Оба прокси подключаются одновременно:

- **Кнопки не нужны** — достаточно одного MTProxy. Рабочие прокси: [@MTProxyT](https://t.me/MTProxyT), [@proxyme](https://t.me/proxyme).
- **Нужны inline-кнопки** — должны работать **оба**: MTProxy + SOCKS5. Бесплатный SOCKS5 найти сложно — рассмотри платный или используй VPN.

```toml
[proxy]
type   = "MTPROTO"
host   = "АДРЕС_ПРОКСИ"
port   = 443
secret = "СЕКРЕТ_ПРОКСИ"

[proxy_socks5]
host     = "АДРЕС_ПРОКСИ"
port     = 1080
username = "USER"
password = "PASS"
```

> 💡 В будущем на сайте появится возможность управлять конфигами модулей и прокси прямо через интерфейс.

---

## ⚙️ Конфигурация

Файл `config.toml` создаётся автоматически (`~/Kitsune/config.toml`):

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

---

## 💾 Бэкапы

При первом запуске выбери интервал авто-бэкапа: **2ч / 4ч / 6ч / 12ч / 24ч**.
Бэкапы отправляются в группу **KitsuneBackup** через встроенного бота.
Восстановление: ответь на файл бэкапа командой `.restore`.

---

## ⚠️ Отказ от ответственности

Проект предоставляется **«как есть»**. Разработчик **не несёт ответственности** за:

- блокировки или ограничения аккаунта
- удаление сообщений со стороны Telegram
- проблемы безопасности, вызванные сторонними модулями
- утечки сессий из-за вредоносных модулей

**Рекомендации по безопасности:**

- Включи `.api_fw_protection`
- Не устанавливай слишком много модулей одновременно
- Используй только проверенные источники модулей
- Ознакомься с [Telegram TOS](https://core.telegram.org/api/terms)

---

## 📄 Лицензия

AGPLv3 © Yushi ([@Mikasu32](https://t.me/Mikasu32)), 2024–2026
