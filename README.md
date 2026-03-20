# 🦊 Kitsune Userbot

<p align="center">
  <b>Быстрый · Стабильный · Современный Telegram Userbot</b><br>
  <sub>Developer: <a href="https://t.me/Mikasu32">Yushi (@Mikasu32)</a> · v1.2.0 Beta (Stable)</sub>
</p>

---

## ✨ Особенности

| Функция | Описание |
|---|---|
| **Двойной стек** | Telethon (основной) + Hydrogram (вторичный) |
| **AST-сканер** | Безопасная загрузка модулей — блокирует опасный код до exec() |
| **Rate Limiter** | Token-bucket алгоритм — защита от флуд-бана |
| **Async SQLite WAL** | Не теряет данные при крэше, WAL journal mode |
| **aiogram 3.x** | Встроенный бот для уведомлений и бэкапов |
| **Авто-бэкап** | Автоматические резервные копии БД в группу KitsuneBackup |
| **Авто-удаление** | Сервисные сообщения удаляются через заданное время |
| **Прогресс-бар** | Визуальный прогресс для длинных операций |
| **TOML конфиг** | Читаемый конфиг с комментариями, кэширование |
| **Termux + Ubuntu** | Один установщик для обоих окружений |

---

## 📦 Встроенные модули

| Модуль | Команды | Описание |
|---|---|---|
| **Backup** | `.backup` `.restore` | Резервные копии БД, авто-бэкап по расписанию |
| **Evaluator** | `.e` `.ex` `.sh` | Выполнение Python/Shell кода |
| **Health** | `.health` `.monitor` | Мониторинг системы |
| **Help** | `.help` | Список команд и модулей |
| **Loader** | `.dlmod` `.loadmod` `.mods` | Управление модулями |
| **Notifier** | `.resetbot` `.mybots` `.setbot` | Бот-нотификатор |
| **Pastebin** | `.paste` | Загрузка текста на pastebin |
| **Ping** | `.ping` `.me` `.id` | Пинг, аптайм, информация |
| **Security** | `.addsudo` `.delsudo` | Управление правами |
| **Settings** | `.prefix` `.lang` `.autodel` `.info` | Настройки юзербота |
| **Updater** | `.update` `.restart` | Обновление и перезапуск |

---

## 🚀 Установка

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
cp config.toml.example config.toml  # заполни api_id и api_hash
python -m kitsune
```

---

## ⚙️ Конфигурация

```toml
api_id   = 123456       # https://my.telegram.org
api_hash = "abcdef..."
prefix   = "."
lang     = "ru"

# Опционально — прокси если Telegram недоступен напрямую
# [proxy]
# type = "SOCKS5"
# host = "127.0.0.1"
# port = 1080
```

---

## 🔌 Загрузка модулей

```
.dlmod https://raw.githubusercontent.com/someone/repo/main/mymodule.py
```

Все загружаемые модули проходят AST-сканирование. Загруженные модули восстанавливаются после перезапуска.

---

## 🗂 Авто-бэкап

При первом запуске бот предложит выбрать интервал резервного копирования (2ч / 4ч / 6ч / 12ч / 24ч). Бэкапы отправляются в группу **KitsuneBackup** и через бота.

Восстановление: ответь на файл бэкапа командой `.restore`.

---

## 📄 Лицензия

AGPLv3 © Yushi (@Mikasu32), 2024-2026
