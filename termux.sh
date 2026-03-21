#!/usr/bin/env bash
# ============================================================
#  Kitsune Userbot — Termux Installer
#  Developer: Yushi (@Mikasu32)
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
MAGENTA='\033[1;35m'; YELLOW='\033[1;33m'; RESET='\033[0m'; BOLD='\033[1m'

ok()   { echo -e "${GREEN}✅  $*${RESET}"; }
info() { echo -e "${CYAN}ℹ️   $*${RESET}"; }
err()  { echo -e "${RED}❌  $*${RESET}"; exit 1; }
step() { echo -e "\n${MAGENTA}${BOLD}── $* ──${RESET}"; }

if [[ -z "${PREFIX:-}" || "$PREFIX" != *"com.termux"* ]]; then
    err "Этот скрипт предназначен только для Termux!"
fi

clear
echo -e "${MAGENTA}${BOLD}  🦊 Kitsune Userbot — Termux Install${RESET}\n"

step "Базовые пакеты"
pkg update -y -q
pkg install -y git python libjpeg-turbo openssl libffi zlib 2>/dev/null
ok "Пакеты установлены"

step "Переменные окружения для сборки"
ARCH=$(uname -m)
if [[ "$ARCH" == "aarch64" ]]; then
    export LDFLAGS="-L/system/lib64/"
else
    export LDFLAGS="-L/system/lib/"
fi
export CFLAGS="-I${PREFIX}/include/"
ok "LDFLAGS / CFLAGS настроены (arch: $ARCH)"

step "Pillow"
pip install Pillow --upgrade --no-cache-dir -q
ok "Pillow установлен"

step "Клонирование репозитория"
INSTALL_DIR="$HOME/Kitsune"
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Обновляю существующий репозиторий..."
    cd "$INSTALL_DIR" && git pull --ff-only origin main
else
    rm -rf "$INSTALL_DIR"
    git clone https://github.com/KitsuneX-dev/Kitsune "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"
ok "Репозиторий готов: $INSTALL_DIR"

step "Python зависимости"
pip install --no-cache-dir -r requirements.txt \
    --no-warn-script-location --disable-pip-version-check \
    --upgrade -q
ok "Зависимости установлены"

step "Hydrogram"
pip install hydrogram tgcrypto --no-cache-dir -q 2>/dev/null && ok "Hydrogram установлен" \
    || echo -e "${YELLOW}⚠️  Hydrogram не установился — продолжаю без него${RESET}"

step "Директории данных"
mkdir -p "$HOME/.kitsune/modules" "$HOME/.kitsune/logs"
ok "Директории созданы"

step "Автозапуск"
if [[ -z "${NO_AUTOSTART:-}" ]]; then
    # Silence default motd
    echo '' > "${PREFIX}/etc/motd" 2>/dev/null || true
    cat > "$HOME/.bash_profile" << 'PROFILE'
clear
echo -e "\033[1;35m  🦊 Kitsune Userbot\033[0m"
cd "$HOME/Kitsune" && python3 -m kitsune
PROFILE
    ok "Автозапуск настроен (~/.bash_profile)"
fi

echo ""
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${GREEN}${BOLD}🦊 Готово!${RESET}"
echo -e "  ${CYAN}Запуск:${RESET} cd ~/Kitsune && python3 -m kitsune"
echo -e "  ${YELLOW}Конфиг:${RESET} ~/Kitsune/config.toml"
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"

python3 -m kitsune
