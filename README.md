<div align="center">

<img src="banner.png" alt="Kitsune Userbot" width="860"/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-AGPLv3-blue?style=flat-square)](LICENSE)
[![Telegram](https://img.shields.io/badge/Developer-@Mikasu32-2CA5E0?style=flat-square&logo=telegram)](https://t.me/Mikasu32)

</div>

---

## Что такое Kitsune?

Kitsune — это userbot для Telegram, написанный на Python. Он запускается локально на твоём устройстве и значительно расширяет возможности Telegram: автоматизация, утилиты, управление группами, резервные копии и многое другое — всё через простые команды с префиксом.

---

## Возможности

| Функция | Описание |
|---|---|
| Двойной стек | Telethon (основной) + Hydrogram (вторичный) |
| AST-сканер | Безопасная загрузка модулей — блокирует опасный код до `exec()` |
| Rate Limiter | Token-bucket алгоритм — защита от флуд-бана |
| Async SQLite WAL | Не теряет данные при крэше, WAL journal mode |
| aiogram 3.x | Встроенный бот для уведомлений и бэкапов |
| Авто-бэкап | Зашифрованные резервные копии БД в группу KitsuneBackup |
| Авто-удаление | Сервисные сообщения удаляются через заданное время |
| Прогресс-бар | Визуальный прогресс для длинных операций |
| TOML конфиг | Читаемый конфиг с кэшированием |
| Termux + Ubuntu | Один установщик для обоих окружений |

---

## Встроенные модули

| Модуль | Команды | Описание |
|---|---|---|
| Backup | `.backup` `.restore` | Зашифрованные резервные копии БД, авто-бэкап по расписанию |
| Evaluator | `.e` `.ex` `.sh` | Выполнение Python / Shell кода |
| Health | `.health` `.monitor` | Мониторинг системы |
| Help | `.help` | Список команд и модулей |
| Loader | `.dlmod` `.loadmod` `.mods` | Управление модулями |
| Notifier | `.resetbot` `.mybots` `.setbot` | Бот-нотификатор |
| Pastebin | `.paste` | Загрузка текста на pastebin |
| Ping | `.ping` `.me` `.id` | Пинг, аптайм, информация |
| Security | `.addsudo` `.delsudo` | Управление правами доступа |
| Settings | `.prefix` `.lang` `.autodel` `.info` | Настройки юзербота |
| Updater | `.update` `.restart` | Обновление и перезапуск |

---

## Установка

### Termux (Android)
```bash
curl -s https://raw.githubusercontent.com/KitsuneX-dev/Kitsune/main/termux.sh | bash
```

### Ubuntu / Debian
```bash
curl -s https://raw.githubusercontent.com/KitsuneX-dev/Kitsune/main/install.sh | bash
```

### Docker
```bash
git clone https://github.com/KitsuneX-dev/Kitsune
cd Kitsune
docker build -t kitsune .
docker run -d --name kitsune -v $(pwd)/data:/data kitsune
```

### Вручную
```bash
git clone https://github.com/KitsuneX-dev/Kitsune
cd Kitsune
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m kitsune
```

После запуска открой `http://localhost:8080` в браузере, введи `api_id` и `api_hash` — и готово.

---

## Запуск

### Termux (Android)
В Termux виртуальное окружение не нужно — просто:
```bash
python -m kitsune
```

### Ubuntu / Debian — без виртуального окружения
Если зависимости установлены глобально:
```bash
python3 -m kitsune
```

### Ubuntu / Debian — через виртуальное окружение (рекомендуется)
Виртуальное окружение изолирует зависимости и предотвращает конфликты пакетов:
```bash
# Активировать окружение и запустить
source venv/bin/activate
python -m kitsune

# Или без активации — напрямую через venv
venv/bin/python -m kitsune
```

> **Если порт 8080 уже занят** — укажи другой в `config.toml`:
> ```toml
> web_port = 8081
> ```
> Затем открой `http://localhost:8081` вместо 8080.

---

## ⚠️ Важно: блокировки РКН (Россия и СНГ)

Telegram заблокирован на территории России и ряда стран СНГ на уровне провайдера. Если при запуске в консоли **тишина** (нет ошибок, но бот не загружается) — это означает что соединение с серверами Telegram блокируется.

**Решение 1 — VPN (простой способ)**
Включи любой VPN перед запуском. Бот подключится через него автоматически.

**Решение 2 — MTProto прокси в config.toml (без VPN)**
Создай файл `config.toml` в папке проекта (`~/Kitsune/config.toml`) и пропиши MTProto прокси:

```toml
web_port = 8081

[proxy]
type   = "MTPROTO"
host   = "АДРЕС_ПРОКСИ"
port   = 443
secret = "СЕКРЕТ_ПРОКСИ"
```

Бесплатные рабочие MTProto прокси можно найти в Telegram:
- [@MTProxyT](https://t.me/MTProxyT)
- [@proxyme](https://t.me/proxyme)

Из ссылки вида `tg://proxy?server=...&port=...&secret=...` берёшь:
- `server` → `host`
- `port` → `port`
- `secret` → `secret`

> Без VPN или настроенного прокси бот **не запустится** в заблокированных регионах — это не баг, а блокировка на уровне провайдера.

---

## Конфигурация

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

`api_id` и `api_hash` получи на [my.telegram.org](https://my.telegram.org). Блок `[proxy]` опционален.

---

## Загрузка модулей

```
.dlmod https://raw.githubusercontent.com/someone/repo/main/mymodule.py
```

Все загружаемые модули проходят AST-сканирование перед выполнением. Загружённые модули восстанавливаются автоматически после перезапуска.

---

## Резервные копии

При первом запуске бот предложит выбрать интервал авто-бэкапа (2ч / 4ч / 6ч / 12ч / 24ч). Бэкапы отправляются в группу **KitsuneBackup**.

Восстановление — ответь на файл бэкапа командой `.restore`.

---

## Лицензия

AGPLv3 © Yushi ([@Mikasu32](https://t.me/Mikasu32)), 2024–2026
