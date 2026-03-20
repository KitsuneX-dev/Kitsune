#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Kitsune — одноразовый фикс git для config.toml
#
#  Запусти один раз если видишь ошибку:
#    "Your local changes to config.toml would be overwritten by merge"
#
#  Что делает скрипт:
#    1. Сохраняет твой config.toml в безопасное место
#    2. Убирает config.toml из git-индекса (git rm --cached)
#    3. Возвращает твой config.toml обратно
#    4. После этого git pull работает нормально навсегда
# ═══════════════════════════════════════════════════════════════

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$REPO_DIR/config.toml"
BACKUP="$REPO_DIR/config.toml.bak"

echo "🦊 Kitsune — фикс git для config.toml"
echo ""

# Проверяем что мы в git-репозитории
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "❌ Не найден .git — запусти скрипт из папки с Kitsune."
    exit 1
fi

# Сохраняем config.toml
if [ -f "$CONFIG" ]; then
    cp "$CONFIG" "$BACKUP"
    echo "✅ config.toml сохранён в config.toml.bak"
else
    echo "⚠️  config.toml не найден — продолжаю без бэкапа"
fi

# Убираем из индекса
cd "$REPO_DIR"
git rm --cached config.toml --ignore-unmatch -q
echo "✅ config.toml убран из git-индекса"

# Возвращаем фай