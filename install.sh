#!/usr/bin/env bash
# ============================================================
#  Kitsune Userbot — Universal Installer
#  Developer: Yushi (@Mikasu32)
#  Supports: Ubuntu / Debian / Termux (Android)
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; MAGENTA='\033[1;35m'; RESET='\033[0m'
BOLD='\033[1m'

ok()   { echo -e "${GREEN}✅ $*${RESET}"; }
info() { echo -e "${CYAN}ℹ️  $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠️  $*${RESET}"; }
err()  { echo -e "${RED}❌ $*${RESET}"; exit 1; }
step() { echo -e "\n${MAGENTA}${BOLD}── $* ──${RESET}"; }

clear
echo -e "${MAGENTA}${BOLD}"
cat << 'EOF'
  ██╗  ██╗██╗████████╗███████╗██╗   ██╗███╗   ██╗███████╗
  ██║ ██╔╝██║╚══██╔══╝██╔════╝██║   ██║████╗  ██║██╔════╝
  █████╔╝ ██║   ██║   ███████╗██║   ██║██╔██╗ ██║█████╗
  ██╔═██╗ ██║   ██║   ╚════██║██║   ██║██║╚██╗██║██╔══╝
  ██║  ██╗██║   ██║   ███████║╚██████╔╝██║ ╚████║███████╗
  ╚═╝  ╚═╝╚═╝   ╚═╝   ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝
EOF
echo -e "${RESET}${CYAN}           Userbot by Yushi (@Mikasu32)${RESET}\n"

IS_TERMUX=false
IS_UBUNTU=false

if [[ -n "${PREFIX:-}" && "$PREFIX" == *"com.termux"* ]]; then
    IS_TERMUX=true
    info "Обнаружена среда: Termux"
elif command -v apt-get &>/dev/null; then
    IS_UBUNTU=true
    info "Обнаружена среда: Ubuntu / Debian"
else
    warn "Неизвестная среда. Попытка продолжить..."
fi

step "Проверка Python"
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        VER=$($cmd -c "import sys; print(sys.version_info[:2])")
        if $cmd -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
            PYTHON="$cmd"
            ok "Python найден: $cmd ($VER)"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    warn "Python 3.10+ не найден. Устанавливаю..."
    if $IS_TERMUX; then
        pkg install python -y
        PYTHON="python3"
    elif $IS_UBUNTU; then
        sudo apt-get update -qq
        sudo apt-get install -y python3.11 python3.11-venv python3-pip
        PYTHON="python3.11"
    else
        err "Установи Python 3.10+ вручную: https://python.org"
    fi
    ok "Python установлен: $PYTHON"
fi

step "Системные зависимости"
if $IS_TERMUX; then
    pkg install -y git libjpeg-turbo openssl libffi 2>/dev/null || true
    # Pillow flags for Termux
    ARCH=$(uname -m)
    if [[ "$ARCH" == "aarch64" ]]; then
        export LDFLAGS="-L/system/lib64/"
    else
        export LDFLAGS="-L/system/lib/"
    fi
    export CFLAGS="-I${PREFIX}/include/"
    ok "Termux-пакеты установлены"
elif $IS_UBUNTU; then
    sudo apt-get update -qq
    sudo apt-get install -y --no-install-recommends \
        git curl build-essential libssl-dev libffi-dev \
        libjpeg-dev zlib1g-dev libpq-dev 2>/dev/null || true
    ok "Системные пакеты установлены"
fi

step "Исходный код"
INSTALL_DIR="$HOME/Kitsune"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Репозиторий уже существует, обновляю..."
    cd "$INSTALL_DIR"
    git pull --ff-only origin main 2>/dev/null || warn "git pull не удался, продолжаю с текущей версией"
    ok "Код обновлён"
else
    info "Клонирую репозиторий..."
    git clone https://github.com/KitsuneX-dev/Kitsune "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    ok "Репозиторий склонирован: $INSTALL_DIR"
fi

step "Виртуальное окружение"
VENV_DIR="$INSTALL_DIR/venv"
if [[ ! -d "$VENV_DIR" ]]; then
    $PYTHON -m venv "$VENV_DIR"
    ok "venv создан: $VENV_DIR"
else
    ok "venv существует, пропускаю"
fi

PIP="$VENV_DIR/bin/pip"
PYTHON_VENV="$VENV_DIR/bin/python"

step "Python зависимости"
"$PIP" install --upgrade pip --quiet
"$PIP" install --no-cache-dir -r requirements.txt \
    --no-warn-script-location --disable-pip-version-check \
    --quiet
ok "Зависимости установлены"

"$PIP" install --no-cache-dir hydrogram tgcrypto --quiet 2>/dev/null && ok "Hydrogram установлен" || warn "Hydrogram не удалось установить, продолжаю без него"

step "Директория данных и права"
mkdir -p "$HOME/.kitsune/modules" "$HOME/.kitsune/logs"
chmod 755 "$HOME/.kitsune"
chmod 755 "$HOME/.kitsune/modules"
chmod 755 "$HOME/.kitsune/logs"
[[ -f "$HOME/.kitsune/kitsune.session" ]]     && chmod 644 "$HOME/.kitsune/kitsune.session"     || true
[[ -f "$HOME/.kitsune/kitsune.session.enc" ]] && chmod 600 "$HOME/.kitsune/kitsune.session.enc" || true
ok "Директории созданы, права выставлены: ~/.kitsune/"

step "Автозапуск"
if $IS_TERMUX; then
    if [[ -z "${NO_AUTOSTART:-}" ]]; then
        cat > "$HOME/.bash_profile" << PROFILE
# Kitsune autostart
clear
echo -e "\033[1;35mKitsune Userbot\033[0m"
cd "$INSTALL_DIR" && "$PYTHON_VENV" -m kitsune
PROFILE
        ok "Автозапуск настроен (Termux)"
    fi
elif $IS_UBUNTU; then
    if [[ -z "${NO_AUTOSTART:-}" && -d "/etc/systemd/system" ]]; then
        SERVICE_FILE="/etc/systemd/system/kitsune.service"
        sudo tee "$SERVICE_FILE" > /dev/null << SERVICE
[Unit]
Description=Kitsune Userbot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYTHON_VENV -m kitsune
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
        sudo systemctl daemon-reload
        sudo systemctl enable kitsune
        ok "systemd сервис создан: sudo systemctl start kitsune"
    fi
fi

echo ""
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${GREEN}${BOLD}🦊 Kitsune установлен!${RESET}"
echo -e "  ${CYAN}Директория:${RESET} $INSTALL_DIR"
echo -e "  ${CYAN}Запуск:${RESET}"
echo -e "    cd $INSTALL_DIR"
echo -e "    $PYTHON_VENV -m kitsune"
echo -e ""
echo -e "  ${YELLOW}Перед запуском добавь в config.toml:${RESET}"
echo -e "    api_id   = <твой api_id>"
echo -e "    api_hash = \"<твой api_hash>\""
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
