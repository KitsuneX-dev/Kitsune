#!/usr/bin/env bash
# ============================================================
#  Kitsune Userbot — Universal Installer
#  Developer: Yushi (@Mikasu32)
#  Supports: Ubuntu / Debian / Termux / UserLand (Android)
# ============================================================
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; MAGENTA='\033[1;35m'; RESET='\033[0m'
BOLD='\033[1m'

ok()   { echo -e "${GREEN}✅ $*${RESET}"; }
info() { echo -e "${CYAN}ℹ️  $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠️  $*${RESET}"; }
err()  { echo -e "${RED}❌ $*${RESET}"; exit 1; }
step() { echo -e "\n${MAGENTA}${BOLD}── $* ──${RESET}"; }

trap 'echo -e "${RED}❌ Ошибка на строке $LINENO — установка прервана${RESET}" >&2' ERR

clear 2>/dev/null || true
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
IS_USERLAND=false
SUDO="sudo"

# Определяем среду
if [[ -n "${PREFIX:-}" && "$PREFIX" == *"com.termux"* ]]; then
    IS_TERMUX=true
    info "Обнаружена среда: Termux"
elif [[ -d "/data/user/0/tech.ula" \
     || -n "${USERLAND_VERSION:-}" \
     || -f "/etc/userland-release" \
     || "$(cat /proc/version 2>/dev/null)" == *"android"* \
     || "$(uname -r 2>/dev/null)" == *"android"* ]]; then
    IS_USERLAND=true
    IS_UBUNTU=true
    info "Обнаружена среда: UserLand (Ubuntu on Android)"
elif command -v apt-get &>/dev/null; then
    IS_UBUNTU=true
    info "Обнаружена среда: Ubuntu / Debian"
else
    warn "Неизвестная среда — попытка продолжить..."
fi

# Выбираем sudo
if [[ "$(id -u)" == "0" ]]; then
    SUDO=""
    info "Запуск от root — sudo не нужен"
elif $IS_USERLAND; then
    # В UserLand есть кастомный /usr/local/bin/sudo — используем его напрямую
    if [[ -x "/usr/local/bin/sudo" ]]; then
        SUDO="/usr/local/bin/sudo"
        info "UserLand: используем /usr/local/bin/sudo"
    elif command -v sudo &>/dev/null; then
        SUDO="sudo"
    else
        SUDO=""
        warn "sudo не найден в UserLand — продолжаю без него"
    fi
elif ! command -v sudo &>/dev/null; then
    SUDO=""
    warn "sudo не найден — пробуем без него"
fi

# Хелпер: apt-get с подавлением fatal-ошибок прав
apt_install() {
    # В UserLand кастомный sudo работает без пароля — не пропускаем пакеты
    if [[ -z "$SUDO" && "$(id -u)" != "0" ]]; then
        warn "Нет прав для apt-get — пропускаю системные пакеты (установи вручную при необходимости)"
        return 0
    fi
    $SUDO apt-get update -qq 2>/dev/null || true
    $SUDO apt-get install -y --no-install-recommends "$@" 2>/dev/null \
        || warn "Не удалось установить: $* — попробуй вручную: apt install $*"
}

# Проверяем git отдельно — без него установка невозможна
if ! command -v git &>/dev/null; then
    warn "git не найден — устанавливаю..."
    if $IS_TERMUX; then
        pkg install -y git || err "Не удалось установить git. Запусти: pkg install git"
    elif $IS_UBUNTU; then
        if [[ -n "$SUDO" || "$(id -u)" == "0" ]]; then
            $SUDO apt-get update -qq 2>/dev/null || true
            $SUDO apt-get install -y --no-install-recommends git 2>/dev/null \
                || err "Не удалось установить git. Запусти вручную: apt install git"
        else
            err "git не найден и нет прав для установки. Запусти: apt install git"
        fi
    fi
    command -v git &>/dev/null && ok "git установлен" || err "git всё ещё не найден — установи вручную"
fi

step "Проверка Python"
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &>/dev/null; then
        if $cmd -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
            VER=$($cmd -c "import sys; print('.'.join(map(str,sys.version_info[:2])))")
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
        apt_install python3.11 python3.11-venv python3-pip
        PYTHON="python3.11"
    else
        err "Установи Python 3.10+ вручную: https://python.org"
    fi
    ok "Python установлен: $PYTHON"
fi

step "Системные зависимости"
if $IS_TERMUX; then
    pkg install -y git libjpeg-turbo openssl libffi 2>/dev/null || true
    ARCH=$(uname -m)
    if [[ "$ARCH" == "aarch64" ]]; then
        export LDFLAGS="-L/system/lib64/"
    else
        export LDFLAGS="-L/system/lib/"
    fi
    export CFLAGS="-I${PREFIX}/include/"
    ok "Termux-пакеты установлены"
elif $IS_UBUNTU; then
    apt_install git curl build-essential libssl-dev libffi-dev \
        libjpeg-dev zlib1g-dev libpq-dev
    ok "Системные пакеты — готово"
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

"$PIP" install --no-cache-dir hydrogram tgcrypto --quiet 2>/dev/null \
    && ok "Hydrogram установлен" \
    || warn "Hydrogram не удалось установить, продолжаю без него"

step "Директория данных и права"
mkdir -p "$HOME/.kitsune/modules" "$HOME/.kitsune/logs"
chmod 755 "$HOME/.kitsune" "$HOME/.kitsune/modules" "$HOME/.kitsune/logs"
[[ -f "$HOME/.kitsune/kitsune.session" ]]     && chmod 644 "$HOME/.kitsune/kitsune.session"     || true
[[ -f "$HOME/.kitsune/kitsune.session.enc" ]] && chmod 600 "$HOME/.kitsune/kitsune.session.enc" || true
ok "Директории созданы: ~/.kitsune/"

step "Скрипт запуска"
if $IS_TERMUX; then
    if [[ -z "${NO_AUTOSTART:-}" ]]; then
        cat > "$HOME/.bash_profile" << PROFILE
# Kitsune autostart
clear
echo -e "\033[1;35mKitsune Userbot\033[0m"
cd "$INSTALL_DIR" && "$PYTHON_VENV" -m kitsune
PROFILE
        ok "Автозапуск настроен (Termux ~/.bash_profile)"
    fi
elif $IS_USERLAND; then
    # UserLand не имеет systemd — создаём скрипт запуска
    cat > "$HOME/start_kitsune.sh" << ULSCRIPT
#!/usr/bin/env bash
cd "$INSTALL_DIR"
exec "$PYTHON_VENV" -m kitsune
ULSCRIPT
    chmod +x "$HOME/start_kitsune.sh"
    ok "Скрипт запуска создан: ~/start_kitsune.sh"
elif $IS_UBUNTU && [[ -z "${NO_AUTOSTART:-}" ]] && [[ -d "/etc/systemd/system" ]]; then
    SERVICE_FILE="/etc/systemd/system/kitsune.service"
    $SUDO tee "$SERVICE_FILE" > /dev/null << SERVICE
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
    $SUDO systemctl daemon-reload 2>/dev/null || true
    $SUDO systemctl enable kitsune 2>/dev/null || true
    ok "systemd сервис создан"
fi

echo ""
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${GREEN}${BOLD}🦊 Kitsune установлен!${RESET}"
echo -e "  ${CYAN}Директория:${RESET} $INSTALL_DIR"
echo -e "  ${CYAN}Запуск:${RESET}"
if $IS_USERLAND; then
    echo -e "    bash ~/start_kitsune.sh"
else
    echo -e "    cd $INSTALL_DIR && $PYTHON_VENV -m kitsune"
fi
echo -e ""
echo -e "  ${YELLOW}Перед запуском добавь в config.toml:${RESET}"
echo -e "    api_id   = <твой api_id>"
echo -e "    api_hash = \"<твой api_hash>\""
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"
