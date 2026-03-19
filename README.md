# 🦊 Kitsune Userbot

<p align="center">
  <b>Быстрый · Стабильный · Современный Telegram Userbot</b><br>
  <sub>Developer: <a href="https://t.me/Mikasu32">Yushi (@Mikasu32)</a></sub>
</p>

---

## ✨ Особенности

| Функция | Описание |
|---|---|
| **Двойной стек** | Telethon (основной) + Hydrogram (вторичный) |
| **Безопасная загрузка** | AST-сканирование модулей перед exec() |
| **Rate Limiter** | Token-bucket алгоритм — защита от флуд-бана |
| **Async SQLite WAL** | Не теряет данные при крэше |
| **aiogram 3.x** | Современный inline-бот без legacy API |
| **TOML конфиг** | Читаемый, поддерживает комментарии |
| **Hikka-совместимость** | Большинство Hikka-модулей работают без изменений |
| **Termux + Ubuntu** | Один установщик для обоих окружений |

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
# Отредактируй config.toml
docker build -t kitsune .
docker run -d --name kitsune -v $(pwd)/data:/data kitsune
```

### Вручную
```bash
git clone https://github.com/KitsuneX-dev/Kitsune
cd Kitsune
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install hydrogram tgcrypto   # опционально
cp config.toml.example config.toml   # заполни api_id и api_hash
python -m kitsune
```

---

## ⚙️ Конфигурация

Отредактируй `config.toml` перед первым запуском:

```toml
api_id   = 123456          # https://my.telegram.org
api_hash = "abcdef..."
prefix   = "."
lang     = "ru"
```

---

## 🔌 Загрузка сторонних модулей

```
.loadmod https://raw.githubusercontent.com/someone/repo/main/mymodule.py
```

Все загружаемые модули проходят AST-сканирование на безопасность.
Загруженные модули сохраняются и автоматически восстанавливаются после перезапуска.

---

## 📄 Лицензия

AGPLv3 © Yushi (@Mikasu32), 2024-2026
