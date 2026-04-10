#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
MAGENTA='\033[1;35m'; YELLOW='\033[1;33m'; RESET='\033[0m'; BOLD='\033[1m'

ok()   { echo -e "${GREEN}✅  $*${RESET}"; }
info() { echo -e "${CYAN}ℹ️   $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠️   $*${RESET}"; }
err()  { echo -e "${RED}❌  $*${RESET}"; exit 1; }
step() { echo -e "\n${MAGENTA}${BOLD}── $* ──${RESET}"; }

if [[ -z "${PREFIX:-}" || "$PREFIX" != *"com.termux"* ]]; then
    err "Этот скрипт предназначен только для Termux!"
fi

clear
echo -e "${MAGENTA}${BOLD}  🦊 Kitsune Userbot — Termux Install${RESET}\n"

step "Обновление пакетов"
pkg update -y -q 2>/dev/null || true
ok "Пакеты обновлены"

step "Базовые зависимости"
pkg install -y git python libjpeg-turbo openssl libffi zlib 2>/dev/null || true
ok "Базовые пакеты установлены"

step "Нативные Python-пакеты (без компиляции)"
pkg install -y python-psutil 2>/dev/null && ok "psutil установлен (нативный)" || warn "psutil недоступен — мониторинг ресурсов отключён"
pkg install -y python-cryptography 2>/dev/null && ok "cryptography установлена (нативная)" || {
    warn "python-cryptography через pkg недоступен — пробую pip..."
    pip install cryptography --no-build-isolation --prefer-binary --no-cache-dir -q 2>/dev/null && \
        ok "cryptography установлена (pip)" || \
        warn "cryptography не установилась — шифрование бэкапов будет использовать встроенный fallback"
}

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
pip install Pillow --upgrade --no-cache-dir -q 2>/dev/null && ok "Pillow установлен" || \
    warn "Pillow не установился"

step "Клонирование репозитория"
INSTALL_DIR="$HOME/Kitsune"
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Обновляю существующий репозиторий..."
    cd "$INSTALL_DIR" && git pull --ff-only origin main 2>/dev/null || \
        warn "git pull не удался, продолжаю с текущей версией"
else
    rm -rf "$INSTALL_DIR"
    git clone https://github.com/KitsuneX-dev/Kitsune "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"
ok "Репозиторий готов: $INSTALL_DIR"

step "Python зависимости"
REQ_FILE="requirements-termux.txt"
[[ ! -f "$REQ_FILE" ]] && REQ_FILE="requirements.txt"

pip install --no-cache-dir --prefer-binary -r "$REQ_FILE" \
    --no-warn-script-location --disable-pip-version-check \
    --upgrade -q 2>/dev/null || \
    warn "Некоторые зависимости не установились"
ok "Зависимости установлены"

step "Hydrogram"
pip install hydrogram tgcrypto --no-cache-dir --prefer-binary -q 2>/dev/null && \
    ok "Hydrogram установлен" || warn "Hydrogram не установился — продолжаю без него"

step "Директории и права"
mkdir -p "$HOME/.kitsune/modules" "$HOME/.kitsune/logs"
chmod 755 "$HOME/.kitsune"
chmod 755 "$HOME/.kitsune/modules"
chmod 755 "$HOME/.kitsune/logs"
[[ -f "$HOME/.kitsune/kitsune.session" ]] && chmod 644 "$HOME/.kitsune/kitsune.session" || true
[[ -f "$HOME/.kitsune/kitsune.session.enc" ]] && chmod 600 "$HOME/.kitsune/kitsune.session.enc" || true
ok "Директории созданы, права выставлены"

step "Автозапуск"
if [[ -z "${NO_AUTOSTART:-}" ]]; then
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
