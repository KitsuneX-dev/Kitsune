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

IS_TERMUX=false
IS_UBUNTU=false
IS_USERLAND=false
SUDO="sudo"

# ── Определяем среду ──────────────────────────────────────────────────────────
if [[ -n "${PREFIX:-}" && "$PREFIX" == *"com.termux"* ]]; then
    IS_TERMUX=true
elif [[ -d "/data/user/0/tech.ula" \
     || -n "${USERLAND_VERSION:-}" \
     || -f "/etc/userland-release" \
     || "$(cat /proc/version 2>/dev/null)" == *"android"* \
     || "$(uname -r 2>/dev/null)" == *"android"* \
     || "$(uname -o 2>/dev/null)" == *"ndroid"* \
     || -f "/proc/1/cmdline" && "$(cat /proc/1/cmdline 2>/dev/null)" == *"bash"* ]]; then
    IS_USERLAND=true
    IS_UBUNTU=true
elif command -v apt-get &>/dev/null; then
    IS_UBUNTU=true
fi

# Очистка экрана только если не в UserLand (чтобы не терять вывод установщика)
if ! $IS_USERLAND; then
    clear 2>/dev/null || true
fi

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

if $IS_TERMUX;   then info "Среда: Termux"
elif $IS_USERLAND; then info "Среда: UserLand (Ubuntu on Android)"
elif $IS_UBUNTU;   then info "Среда: Ubuntu / Debian"
else warn "Неизвестная среда — попытка продолжить..."; fi

# ── Определяем sudo ───────────────────────────────────────────────────────────
if [[ "$(id -u)" == "0" ]]; then
    SUDO=""
    info "Запущен от root — sudo не нужен"
elif $IS_USERLAND; then
    # UserLand: пробуем стандартный sudo, затем /usr/local/bin/sudo, затем proot
    if command -v sudo &>/dev/null && sudo -n true 2>/dev/null; then
        SUDO="sudo"
        info "UserLand: используем sudo"
    elif [[ -x "/usr/local/bin/sudo" ]]; then
        SUDO="/usr/local/bin/sudo"
        info "UserLand: используем /usr/local/bin/sudo"
    else
        # Последняя попытка: запустить с proot (если есть)
        if command -v proot &>/dev/null; then
            SUDO="proot -0"
            info "UserLand: используем proot -0 вместо sudo"
        else
            SUDO=""
            warn "sudo / proot не найдены. Попробуй запустить скрипт через: sudo bash install.sh"
        fi
    fi
elif ! command -v sudo &>/dev/null; then
    SUDO=""
    warn "sudo не найден — попытка без него"
fi

# ── Хелпер: безопасный apt-get ───────────────────────────────────────────────
apt_install() {
    if [[ -z "$SUDO" && "$(id -u)" != "0" ]]; then
        warn "Нет прав root для apt-get. Попробуй: sudo apt install $*"
        warn "После ручной установки запусти скрипт повторно."
        return 1
    fi
    $SUDO apt-get update -qq 2>/dev/null || true
    $SUDO apt-get install -y --no-install-recommends "$@" \
        || { warn "Не удалось установить: $* — попробуй вручную: sudo apt install $*"; return 1; }
}

# ── Git ───────────────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    warn "git не найден — устанавливаю..."
    if $IS_TERMUX; then
        pkg install -y git || err "Не удалось установить git. Запусти: pkg install git"
    elif $IS_UBUNTU; then
        apt_install git || err "Установи git вручную: sudo apt install git, затем перезапусти скрипт"
    fi
    command -v git &>/dev/null && ok "git установлен" \
        || err "git не найден. Установи вручную и перезапусти скрипт."
fi

# ── Python ────────────────────────────────────────────────────────────────────
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
    warn "Python 3.10+ не найден — устанавливаю..."
    if $IS_TERMUX; then
        pkg install python -y; PYTHON="python3"
    elif $IS_UBUNTU; then
        apt_install python3.11 python3.11-venv python3-pip \
            || err "Установи Python вручную: sudo apt install python3.11 python3.11-venv"
        PYTHON="python3.11"
    else
        err "Установи Python 3.10+ вручную: https://python.org"
    fi
    ok "Python: $PYTHON"
fi

# ── Системные зависимости (включая python3-venv — всегда явно) ───────────────
step "Системные зависимости"
if $IS_TERMUX; then
    pkg install -y git libjpeg-turbo openssl libffi 2>/dev/null || true
    ARCH=$(uname -m)
    export LDFLAGS="-L${ARCH/#aarch64//system/lib64/}"
    export CFLAGS="-I${PREFIX}/include/"
    ok "Termux-пакеты готовы"
elif $IS_UBUNTU; then
    # Определяем точную версию Python чтобы поставить правильный пакет venv
    PYVER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    apt_install git curl build-essential libssl-dev libffi-dev \
        libjpeg-dev zlib1g-dev libpq-dev \
        "python${PYVER}-venv" python3-venv \
        && ok "Системные пакеты — готово" || true
fi

# ── Финальная проверка venv (защитная сетка) ──────────────────────────────────
if $IS_UBUNTU; then
    # Проверяем реальным созданием тестового venv, а не --help (--help врёт)
    _VENV_TEST=$(mktemp -d)
    if ! $PYTHON -m venv "$_VENV_TEST" --without-pip &>/dev/null 2>&1; then
        warn "python${PYVER}-venv всё ещё недоступен — пробую ещё раз..."
        apt_install "python${PYVER}-venv" python3-venv \
            || err "Не удалось установить python${PYVER}-venv. Запусти вручную: sudo apt install python${PYVER}-venv"
        $PYTHON -m venv "$_VENV_TEST" --without-pip &>/dev/null \
            || err "venv недоступен даже после установки. Попробуй перезайти в UserLand и запустить скрипт снова."
    fi
    rm -rf "$_VENV_TEST"
    ok "python${PYVER}-venv: готов"
fi

# ── Исходный код ──────────────────────────────────────────────────────────────
step "Исходный код"
INSTALL_DIR="$HOME/Kitsune"

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Репозиторий уже есть — обновляю..."
    cd "$INSTALL_DIR"
    git pull --ff-only origin main 2>/dev/null || warn "git pull не удался, продолжаю с текущей версией"
    ok "Код обновлён"
else
    info "Клонирую репозиторий..."
    git clone https://github.com/KitsuneX-dev/Kitsune "$INSTALL_DIR" \
        || err "Не удалось клонировать репозиторий. Проверь интернет-соединение."
    cd "$INSTALL_DIR"
    ok "Репозиторий склонирован: $INSTALL_DIR"
fi

# ── Виртуальное окружение ─────────────────────────────────────────────────────
step "Виртуальное окружение"
VENV_DIR="$INSTALL_DIR/venv"
if [[ ! -d "$VENV_DIR" ]]; then
    if ! $PYTHON -m venv "$VENV_DIR"; then
        warn "venv не создался — пробую доустановить python${PYVER:-3.10}-venv..."
        ${SUDO:-} apt-get install -y "python${PYVER:-3.10}-venv" python3-venv 2>/dev/null || true
        $PYTHON -m venv "$VENV_DIR" \
            || err "Не удалось создать venv. Запусти вручную: sudo apt install python3.10-venv"
    fi
    ok "venv создан: $VENV_DIR"
else
    ok "venv существует, пропускаю"
fi

PIP="$VENV_DIR/bin/pip"
PYTHON_VENV="$VENV_DIR/bin/python"

step "Python зависимости"
# UserLand/aarch64: /tmp имеет ограниченные права при сборке wheel из исходников
if $IS_USERLAND || [[ ! -w /tmp ]]; then
    mkdir -p "$HOME/tmp"
    export TMPDIR="$HOME/tmp"
    info "TMPDIR → $HOME/tmp (обход ограничений /tmp)"
fi
"$PIP" install --upgrade pip wheel --quiet

# grapheme: rename() → egg-info.__bkp__ заблокирован ядром Android в UserLand/proot
# pip download тоже затрагивает metadata — качаем tarball напрямую через curl
_GRAPHEME_TMP="$HOME/tmp/grapheme_install"
mkdir -p "$_GRAPHEME_TMP"
curl -sSL "https://files.pythonhosted.org/packages/source/g/grapheme/grapheme-0.6.0.tar.gz" \
    -o "$_GRAPHEME_TMP/grapheme-0.6.0.tar.gz" \
    || err "Не удалось скачать grapheme"
(cd "$_GRAPHEME_TMP" && tar xzf grapheme-0.6.0.tar.gz)
_SITE_PACKAGES=$("$PYTHON_VENV" -c "import site; print(site.getsitepackages()[0])")
cp -r "$_GRAPHEME_TMP/grapheme-0.6.0/grapheme" "$_SITE_PACKAGES/"
rm -rf "$_GRAPHEME_TMP"
ok "grapheme установлен"
"$PIP" install --no-cache-dir -r requirements.txt \
    --no-warn-script-location --disable-pip-version-check --quiet \
    || err "Не удалось установить зависимости. Проверь requirements.txt"
ok "Зависимости установлены"

"$PIP" install --no-cache-dir hydrogram tgcrypto --quiet 2>/dev/null \
    && ok "Hydrogram установлен" \
    || warn "Hydrogram не установлен — продолжаю без него"

# ── Директории ────────────────────────────────────────────────────────────────
step "Директории и права"
mkdir -p "$HOME/.kitsune/modules" "$HOME/.kitsune/logs"
chmod 755 "$HOME/.kitsune" "$HOME/.kitsune/modules" "$HOME/.kitsune/logs"
[[ -f "$HOME/.kitsune/kitsune.session" ]]     && chmod 644 "$HOME/.kitsune/kitsune.session"     || true
[[ -f "$HOME/.kitsune/kitsune.session.enc" ]] && chmod 600 "$HOME/.kitsune/kitsune.session.enc" || true
ok "Директории: ~/.kitsune/"

# ── Скрипт запуска ────────────────────────────────────────────────────────────
step "Скрипт запуска"
if $IS_TERMUX; then
    if [[ -z "${NO_AUTOSTART:-}" ]]; then
        cat > "$HOME/.bash_profile" << PROFILE
# Kitsune autostart
clear
echo -e "\033[1;35mKitsune Userbot\033[0m"
cd "$INSTALL_DIR" && "$PYTHON_VENV" -m kitsune
PROFILE
        ok "Автозапуск настроен (~/.bash_profile)"
    fi
elif $IS_USERLAND; then
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

# ── Итог ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${GREEN}${BOLD}🦊 Kitsune успешно установлен!${RESET}"
echo -e "  ${CYAN}Директория:${RESET} $INSTALL_DIR"
echo ""
if $IS_USERLAND; then
    echo -e "  ${YELLOW}${BOLD}▶ ЗАПУСК (вставь в терминал):${RESET}"
    echo -e "  ${GREEN}bash ~/start_kitsune.sh${RESET}"
else
    echo -e "  ${YELLOW}${BOLD}▶ ЗАПУСК:${RESET}"
    echo -e "  ${GREEN}cd $INSTALL_DIR && $PYTHON_VENV -m kitsune${RESET}"
fi
echo ""
echo -e "  ${YELLOW}Перед запуском добавь в config.toml:${RESET}"
echo -e "    api_id   = <твой api_id>"
echo -e "    api_hash = \"<твой api_hash>\""
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""
