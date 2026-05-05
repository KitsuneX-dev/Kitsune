#!/usr/bin/env bash

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="$REPO_DIR/config.toml"
BACKUP="$REPO_DIR/config.toml.bak"

echo "🦊 Kitsune — фикс git для config.toml"
echo ""

if [ ! -d "$REPO_DIR/.git" ]; then
    echo "❌ Не найден .git — запусти скрипт из папки с Kitsune."
    exit 1
fi

if [ -f "$CONFIG" ]; then
    cp "$CONFIG" "$BACKUP"
    echo "✅ config.toml сохранён в config.toml.bak"
else
    echo "⚠️  config.toml не найден — продолжаю без бэкапа"
fi

cd "$REPO_DIR"
git rm --cached config.toml --ignore-unmatch -q
echo "✅ config.toml убран из git-индекса"

