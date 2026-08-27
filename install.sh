#!/usr/bin/env bash
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
IS_DEBIAN_FAMILY=false
IS_REAL_UBUNTU=false
IS_ALPINE=false
IS_ARCH=false
SUDO="sudo"

if [[ -n "${PREFIX:-}" && "$PREFIX" == *"com.termux"* ]]; then
    IS_TERMUX=true
elif [[ -d "/data/user/0/tech.ula" \
     || -d "/data/data/tech.ula" \
     || -n "${USERLAND_VERSION:-}" \
     || -f "/etc/userland-release" \
     || "$(cat /proc/version 2>/dev/null)" == *"android"* \
     || "$(uname -r 2>/dev/null)" == *"android"* \
     || "$(uname -o 2>/dev/null)" == *"ndroid"* \
     || ( -f "/proc/1/cmdline" && "$(tr -d '\0' < /proc/1/cmdline 2>/dev/null)" == *"bash"* ) ]]; then
    IS_USERLAND=true
    IS_UBUNTU=true
elif command -v apt-get &>/dev/null; then
    IS_UBUNTU=true
fi

if $IS_UBUNTU; then
    IS_DEBIAN_FAMILY=true
    if [[ -r /etc/os-release ]]; then
        . /etc/os-release
        [[ "${ID:-}" == "ubuntu" || " ${ID_LIKE:-} " == *" ubuntu "* ]] && IS_REAL_UBUNTU=true
    fi
elif command -v apk &>/dev/null; then
    IS_ALPINE=true
elif command -v pacman &>/dev/null; then
    IS_ARCH=true
fi

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
elif $IS_USERLAND; then info "Среда: UserLand (${PRETTY_NAME:-Linux} on Android)"
elif $IS_UBUNTU;   then info "Среда: ${PRETTY_NAME:-Ubuntu / Debian}"
elif $IS_ALPINE;   then info "Среда: Alpine Linux (musl)"
elif $IS_ARCH;     then info "Среда: Arch Linux"
else warn "Неизвестная среда — попытка продолжить..."; fi

if [[ "$(id -u)" == "0" ]]; then
    SUDO=""
    info "Запущен от root — sudo не нужен"
elif $IS_USERLAND; then
    if command -v sudo &>/dev/null && sudo -n true 2>/dev/null; then
        SUDO="sudo"
        info "UserLand: используем sudo"
    elif [[ -x "/usr/local/bin/sudo" ]]; then
        SUDO="/usr/local/bin/sudo"
        info "UserLand: используем /usr/local/bin/sudo"
    else
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

apk_install() {
    if [[ -z "$SUDO" && "$(id -u)" != "0" ]]; then
        warn "Нет прав root для apk. Попробуй: sudo apk add $*"
        return 1
    fi
    $SUDO apk add --no-cache "$@" \
        || { warn "Не удалось установить: $* — попробуй вручную: sudo apk add $*"; return 1; }
}

pacman_install() {
    if [[ -z "$SUDO" && "$(id -u)" != "0" ]]; then
        warn "Нет прав root для pacman. Попробуй: sudo pacman -S $*"
        return 1
    fi
    $SUDO pacman -Sy --needed --noconfirm "$@" \
        || { warn "Не удалось установить: $* — попробуй вручную: sudo pacman -S $*"; return 1; }
}

if ! command -v git &>/dev/null; then
    warn "git не найден — устанавливаю..."
    if $IS_TERMUX; then
        pkg install -y git || err "Не удалось установить git. Запусти: pkg install git"
    elif $IS_UBUNTU; then
        apt_install git || err "Установи git вручную: sudo apt install git, затем перезапусти скрипт"
    elif $IS_ALPINE; then
        apk_install git || err "Установи git вручную: sudo apk add git, затем перезапусти скрипт"
    elif $IS_ARCH; then
        pacman_install git || err "Установи git вручную: sudo pacman -S git, затем перезапусти скрипт"
    fi
    command -v git &>/dev/null && ok "git установлен" \
        || err "git не найден. Установи вручную и перезапусти скрипт."
fi

step "Проверка Python"

REQ_PY_MAJOR=3
REQ_PY_MINOR=12

read_requires_python() {
    local file="$1"
    [[ -f "$file" ]] || return 1
    local spec
    spec=$(grep -m1 -E '^[[:space:]]*requires-python[[:space:]]*=' "$file" 2>/dev/null \
        | sed -E 's/.*=[[:space:]]*["'\'']([^"'\'']+)["'\''].*/\1/')
    [[ -n "$spec" ]] || return 1
    local best_major="" best_minor=""
    local IFS=','
    local part
    for part in $(echo "$spec" | tr -d ' '); do
        if [[ "$part" =~ ^(\>=|==|~=)([0-9]+)\.([0-9]+) ]]; then
            local mj="${BASH_REMATCH[2]}" mn="${BASH_REMATCH[3]}"
            if [[ -z "$best_major" ]] || (( mj > best_major )) || { (( mj == best_major )) && (( mn > best_minor )); }; then
                best_major="$mj"; best_minor="$mn"
            fi
        elif [[ "$part" =~ ^\>([0-9]+)\.([0-9]+) ]]; then
            local mj="${BASH_REMATCH[1]}" mn=$(( BASH_REMATCH[2] + 1 ))
            if [[ -z "$best_major" ]] || (( mj > best_major )) || { (( mj == best_major )) && (( mn > best_minor )); }; then
                best_major="$mj"; best_minor="$mn"
            fi
        fi
    done
    [[ -n "$best_major" ]] || return 1
    REQ_PY_MAJOR="$best_major"
    REQ_PY_MINOR="$best_minor"
    return 0
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo ".")"
for _pp in "$SCRIPT_DIR/pyproject.toml" "$HOME/Kitsune/pyproject.toml" "./pyproject.toml"; do
    if read_requires_python "$_pp"; then
        info "requires-python из $_pp: ${REQ_PY_MAJOR}.${REQ_PY_MINOR}+"
        break
    fi
done
REQ_PY="${REQ_PY_MAJOR}.${REQ_PY_MINOR}"

py_version_of() {
    "$1" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null
}

py_version_ok() {
    "$1" -c "import sys; sys.exit(0 if sys.version_info[:2] >= ($REQ_PY_MAJOR, $REQ_PY_MINOR) else 1)" 2>/dev/null
}

py_can_venv() {
    local probe
    probe=$(mktemp -d 2>/dev/null) || return 1
    if "$1" -m venv --without-pip "$probe/probe" &>/dev/null; then
        rm -rf "$probe"
        return 0
    fi
    rm -rf "$probe"
    return 1
}

py_candidate_names() {
    local offset
    for offset in 6 5 4 3 2 1 0; do
        echo "python${REQ_PY_MAJOR}.$(( REQ_PY_MINOR + offset ))"
    done
    echo "python${REQ_PY_MAJOR}"
    echo "python"
}

pick_python() {
    local cmd path found_any="" fallback="" fallback_ver=""
    local self_real=""
    while read -r cmd; do
        command -v "$cmd" &>/dev/null || continue
        path=$(command -v "$cmd")
        [[ -n "$self_real" && "$path" == "$self_real" ]] && continue
        py_version_ok "$path" || continue
        found_any="yes"
        local ver
        ver=$(py_version_of "$path")
        if py_can_venv "$path"; then
            PYTHON="$path"
            PYTHON_VER="$ver"
            return 0
        fi
        if [[ -z "$fallback" ]]; then
            fallback="$path"
            fallback_ver="$ver"
        fi
    done < <(py_candidate_names)
    if [[ -n "$fallback" ]]; then
        PYTHON="$fallback"
        PYTHON_VER="$fallback_ver"
        warn "Найден Python $fallback_ver ($fallback), но модуль venv недоступен — доустановлю его"
        return 0
    fi
    [[ -n "$found_any" ]] && return 1
    return 1
}

PYTHON=""
PYTHON_VER=""
if pick_python; then
    ok "Python найден: $PYTHON ($PYTHON_VER), требуется ${REQ_PY}+"
fi

if [[ -z "$PYTHON" ]]; then
    warn "Python ${REQ_PY}+ не найден — устанавливаю..."
    if $IS_TERMUX; then
        pkg install python -y 2>/dev/null || true
        pick_python || err "В Termux не удалось получить Python ${REQ_PY}+. Обнови Termux: pkg upgrade && pkg install python"
    elif $IS_UBUNTU; then
        if $IS_REAL_UBUNTU && command -v add-apt-repository &>/dev/null; then
            ${SUDO:-} add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null \
                || warn "Не удалось подключить deadsnakes PPA — пробую стоковые репозитории"
            ${SUDO:-} apt-get update -qq 2>/dev/null || true
        elif ! $IS_REAL_UBUNTU; then
            info "Debian-семейство без PPA — ставлю Python из стоковых репозиториев"
        fi
        for _off in 6 5 4 3 2 1 0; do
            _tag="${REQ_PY_MAJOR}.$(( REQ_PY_MINOR + _off ))"
            if apt_install "python${_tag}" "python${_tag}-venv" "python${_tag}-dev" python3-pip 2>/dev/null \
               || apt_install "python${_tag}" "python${_tag}-venv" python3-pip 2>/dev/null; then
                if pick_python; then
                    break
                fi
            fi
        done
        if [[ -z "$PYTHON" ]] && $IS_REAL_UBUNTU; then
            err "Установи Python ${REQ_PY}+ вручную: sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python${REQ_PY} python${REQ_PY}-venv"
        elif [[ -z "$PYTHON" ]]; then
            err "В стандартных репозиториях нет Python ${REQ_PY}+ (у тебя $(python3 -V 2>&1)).
    Варианты:
      1) Обновиться до Debian 13 (trixie): sudo apt install python3.13 python3.13-venv
      2) Поставить через pyenv:  curl https://pyenv.run | bash && pyenv install ${REQ_PY}
      3) Docker-образ проекта (Dockerfile в репозитории)
    PPA deadsnakes на Debian НЕ работает — не используй совет для Ubuntu."
        fi
    elif $IS_ALPINE; then
        apk_install python3 py3-pip || err "Установи Python вручную: sudo apk add python3 py3-pip"
        pick_python || err "Alpine поставил Python ниже ${REQ_PY} — обнови систему или используй Docker-образ проекта"
    elif $IS_ARCH; then
        pacman_install python python-pip || err "Установи Python вручную: sudo pacman -S python"
        pick_python || err "В системе Python ниже ${REQ_PY} — обнови пакеты: sudo pacman -Syu python"
    else
        err "Установи Python ${REQ_PY}+ вручную: https://python.org"
    fi
    [[ -n "$PYTHON" ]] || err "Не удалось получить Python ${REQ_PY}+ автоматически. Установи его вручную и запусти скрипт снова."
    ok "Python: $PYTHON ($PYTHON_VER)"
fi

step "Системные зависимости"
if $IS_TERMUX; then
    pkg install -y git libjpeg-turbo openssl libffi 2>/dev/null || true
    ARCH=$(uname -m)
    export LDFLAGS="-L${ARCH/#aarch64//system/lib64/}"
    export CFLAGS="-I${PREFIX}/include/"
    ok "Termux-пакеты готовы"
elif $IS_UBUNTU; then
    PYVER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

    apt_install git curl build-essential libssl-dev libffi-dev \
        libjpeg-dev zlib1g-dev libpq-dev \
        "python${PYVER}-venv" python3-venv \
        "python${PYVER}-dev" \
        && ok "Системные пакеты — готово" \
        || { apt_install python3-dev && ok "Системные пакеты — готово (с python3-dev fallback)"; } \
        || true
elif $IS_ALPINE; then
    apk_install git curl build-base python3-dev libffi-dev openssl-dev \
        jpeg-dev zlib-dev linux-headers cargo rust \
        && ok "Alpine-пакеты готовы" \
        || warn "Часть пакетов не встала — сборка cryptg может упасть"
elif $IS_ARCH; then
    pacman_install git curl base-devel openssl libffi libjpeg-turbo zlib \
        && ok "Arch-пакеты готовы" \
        || warn "Часть пакетов не встала"
fi

if $IS_UBUNTU; then
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

step "Исходный код"
INSTALL_DIR="$HOME/Kitsune"

mkdir -p "$HOME" 2>/dev/null || true

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Репозиторий уже есть — обновляю..."
    cd "$INSTALL_DIR" || err "Не удалось перейти в $INSTALL_DIR"
    git pull --ff-only origin main 2>/dev/null || warn "git pull не удался, продолжаю с текущей версией"
    ok "Код обновлён"
else
    if [[ -e "$INSTALL_DIR" ]]; then
        warn "Папка $INSTALL_DIR существует, но не является git-репозиторием — пересоздаю..."
        rm -rf "$INSTALL_DIR" || err "Не удалось удалить старую папку $INSTALL_DIR"
    fi

    info "Клонирую репозиторий в $INSTALL_DIR ..."
    git clone https://github.com/KitsuneX-dev/Kitsune "$INSTALL_DIR" \
        || err "Не удалось клонировать репозиторий. Проверь интернет-соединение."

    if [[ ! -d "$INSTALL_DIR" ]]; then
        warn "Папка $INSTALL_DIR не создана git'ом — создаю вручную и повторяю клон..."
        mkdir -p "$INSTALL_DIR" || err "Не удалось создать папку $INSTALL_DIR"
        git clone https://github.com/KitsuneX-dev/Kitsune "$INSTALL_DIR" \
            || err "Повторный клон не удался. Проверь интернет и права доступа к $HOME."
    fi

    if [[ ! -d "$INSTALL_DIR/.git" ]]; then
        err "Папка $INSTALL_DIR создана, но репозиторий внутри не инициализирован."
    fi

    cd "$INSTALL_DIR" || err "Не удалось перейти в $INSTALL_DIR"
    ok "Репозиторий склонирован: $INSTALL_DIR"
fi

if [[ ! -d "$INSTALL_DIR" ]]; then
    err "Критическая ошибка: папка $INSTALL_DIR отсутствует после установки."
fi
ok "Папка Kitsune подтверждена: $INSTALL_DIR"

step "Виртуальное окружение"
VENV_DIR="$INSTALL_DIR/venv"

if read_requires_python "$INSTALL_DIR/pyproject.toml"; then
    REQ_PY="${REQ_PY_MAJOR}.${REQ_PY_MINOR}"
    info "requires-python из репозитория: ${REQ_PY}+"
    if ! py_version_ok "$PYTHON"; then
        warn "Текущий $PYTHON ниже ${REQ_PY} — ищу другой интерпретатор"
        PYTHON=""
        pick_python || err "Нужен Python ${REQ_PY}+, подходящий интерпретатор не найден. Установи его вручную и перезапусти скрипт."
        ok "Использую Python: $PYTHON ($PYTHON_VER)"
    fi
fi

if [[ -d "$VENV_DIR" ]]; then
    _VENV_PY_VER=$(py_version_of "$VENV_DIR/bin/python" || true)
    if [[ -z "$_VENV_PY_VER" ]] || ! py_version_ok "$VENV_DIR/bin/python"; then
        warn "Существующий venv на Python ${_VENV_PY_VER:-неизвестно} несовместим (нужен ${REQ_PY}+) — пересоздаю"
        rm -rf "$VENV_DIR.old"
        mv "$VENV_DIR" "$VENV_DIR.old" 2>/dev/null || rm -rf "$VENV_DIR"
    fi
fi

if [[ ! -d "$VENV_DIR" ]]; then
    if ! $PYTHON -m venv "$VENV_DIR"; then
        if $IS_ALPINE; then
            warn "venv не создался — пробую доустановить python3-dev/py3-virtualenv..."
            apk_install python3-dev py3-virtualenv 2>/dev/null || true
            $PYTHON -m venv "$VENV_DIR" \
                || err "Не удалось создать venv. Запусти вручную: sudo apk add python3 py3-pip"
        elif $IS_ARCH; then
            warn "venv не создался — пробую доустановить python-virtualenv..."
            pacman_install python-virtualenv 2>/dev/null || true
            $PYTHON -m venv "$VENV_DIR" \
                || err "Не удалось создать venv. Запусти вручную: sudo pacman -S python python-pip"
        else
            warn "venv не создался — пробую доустановить python${PYVER:-$REQ_PY}-venv..."
            ${SUDO:-} apt-get install -y "python${PYVER:-$REQ_PY}-venv" python3-venv 2>/dev/null || true
            $PYTHON -m venv "$VENV_DIR" \
                || err "Не удалось создать venv. Запусти вручную: sudo apt install python${REQ_PY}-venv"
        fi
    fi
    ok "venv создан: $VENV_DIR (Python $(py_version_of "$VENV_DIR/bin/python"))"
    rm -rf "$VENV_DIR.old"
else
    ok "venv существует (Python $(py_version_of "$VENV_DIR/bin/python")), пропускаю"
fi

PIP="$VENV_DIR/bin/pip"
PYTHON_VENV="$VENV_DIR/bin/python"

step "Python зависимости"
if $IS_USERLAND || [[ ! -w /tmp ]]; then
    mkdir -p "$HOME/tmp"
    export TMPDIR="$HOME/tmp"
    info "TMPDIR → $HOME/tmp (обход ограничений /tmp)"
fi
"$PIP" install --upgrade pip wheel setuptools --quiet

_DIST_INFO_PY=$("$PYTHON_VENV" -c "
import setuptools, os
print(os.path.join(os.path.dirname(setuptools.__file__), 'command', 'dist_info.py'))
" 2>/dev/null || true)
if [[ -f "$_DIST_INFO_PY" ]]; then
    "$PYTHON_VENV" - "$_DIST_INFO_PY" << 'PYEOF'
import sys
path = sys.argv[1]
with open(path) as f:
    src = f.read()
old = '''    @contextmanager
    def _maybe_bkp_dir(self, dir_path: str, requires_bkp: bool):
        if requires_bkp:
            bkp_name = f"{dir_path}.__bkp__"
            _rm(bkp_name, ignore_errors=True)
            shutil.copytree(dir_path, bkp_name, dirs_exist_ok=True, symlinks=True)
            try:
                yield
            finally:
                _rm(dir_path, ignore_errors=True)
                shutil.move(bkp_name, dir_path)
        else:
            yield'''
new = '''    @contextmanager
    def _maybe_bkp_dir(self, dir_path: str, requires_bkp: bool):
        yield'''
if old in src:
    with open(path, 'w') as f:
        f.write(src.replace(old, new))
PYEOF
    ok "setuptools пропатчен (обход egg-info.__bkp__)"
else
    warn "setuptools dist_info.py не найден — пропускаю патч"
fi

if "$PIP" install --prefer-binary --no-cache-dir --no-warn-script-location \
       --disable-pip-version-check --quiet "tgcrypto>=1.2.5" 2>/dev/null; then
    ok "tgcrypto установлен (prebuilt wheel)"
else
    info "Prebuilt wheel не найден — собираю tgcrypto из исходников..."

    _PY_INC=$("$PYTHON_VENV" -c "import sysconfig; print(sysconfig.get_path('include'))" 2>/dev/null || true)
    _BUILD_OK=false
    if [[ -n "$_PY_INC" && -f "$_PY_INC/Python.h" ]]; then
        CFLAGS="-I$_PY_INC" "$PIP" install --no-cache-dir --no-warn-script-location \
            --disable-pip-version-check --quiet "tgcrypto>=1.2.5" 2>/dev/null \
            && _BUILD_OK=true
    fi
    if ! $_BUILD_OK; then
        "$PIP" install --no-build-isolation --no-cache-dir --no-warn-script-location \
            --disable-pip-version-check --quiet "tgcrypto>=1.2.5" 2>/dev/null \
            && _BUILD_OK=true
    fi
    if $_BUILD_OK; then
        ok "tgcrypto установлен (собран из исходников)"
    else
        warn "tgcrypto не установился — Hydrogram будет работать без C-ускорения"
    fi
fi

if ! "$PIP" install --prefer-binary --no-cache-dir -r requirements.txt \
        --no-warn-script-location --disable-pip-version-check; then
    warn "Первая попытка не удалась — повторяю установку зависимостей..."
    "$PIP" install --no-cache-dir -r requirements.txt \
        --no-warn-script-location --disable-pip-version-check \
        || err "Не удалось установить зависимости. Проверь requirements.txt"
fi
ok "Зависимости установлены"

step "Telethon (основная библиотека)"
if ! "$PYTHON_VENV" -c "import telethon" 2>/dev/null; then
    "$PIP" install --prefer-binary --no-cache-dir "telethon>=1.36.0,<2.0.0" \
        --no-warn-script-location --disable-pip-version-check 2>/dev/null \
        || "$PIP" install --no-cache-dir "telethon>=1.36.0,<2.0.0" \
            --no-warn-script-location --disable-pip-version-check
fi
"$PYTHON_VENV" -c "import telethon" 2>/dev/null \
    && ok "Telethon установлен и импортируется" \
    || err "Telethon не установился — без него бот не запустится. Запусти вручную: $PIP install 'telethon>=1.36.0'"

"$PIP" install --no-cache-dir --no-warn-script-location --disable-pip-version-check --quiet \
    "python-socks[asyncio]>=2.4.4" PySocks \
    && ok "python-socks[asyncio] установлен (нужен для прокси и обхода РКН)" \
    || warn "python-socks не установился — прокси/RKNBypass работать не будут"

"$PIP" install --prefer-binary --no-cache-dir hydrogram \
    --no-warn-script-location --disable-pip-version-check --quiet \
    && ok "Hydrogram установлен" \
    || warn "Hydrogram не установлен (необязательный пакет)"

step "cryptg (ускорение AES-IGE для Telethon)"
if "$PYTHON_VENV" -c "import cryptg" 2>/dev/null; then
    ok "cryptg уже установлен"
else
    _CRYPTG_OK=false
    if "$PYTHON_VENV" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        _CRYPTG_SPEC="cryptg>=0.6.0"
    else
        _CRYPTG_SPEC="cryptg>=0.4.0,<0.6.0"
        info "cryptg 0.6+ требует Python 3.11+ — использую совместимую ветку 0.5.x"
    fi
    if "$PIP" install --prefer-binary --only-binary=:all: --no-cache-dir \
           --no-warn-script-location --disable-pip-version-check --quiet "$_CRYPTG_SPEC" 2>/dev/null; then
        _CRYPTG_OK=true
        ok "cryptg установлен (prebuilt wheel)"
    elif command -v cargo >/dev/null 2>&1; then
        warn "prebuilt wheel для cryptg нет — пробую собрать через cargo (это долго)"
        if "$PIP" install --no-cache-dir --no-warn-script-location \
               --disable-pip-version-check --quiet "$_CRYPTG_SPEC" 2>/dev/null; then
            _CRYPTG_OK=true
            ok "cryptg установлен (собран из исходников через cargo)"
        fi
    else
        warn "cargo не найден — сборка cryptg из исходников невозможна"
    fi
    if ! $_CRYPTG_OK; then
        warn "cryptg не установился — будет использован фолбэк на tgcrypto (AES-IGE патч Kitsune)"
    fi
fi

step "uvloop (ускорение event loop)"
if "$PYTHON_VENV" -c "import uvloop" 2>/dev/null; then
    ok "uvloop уже установлен"
else
    if $IS_TERMUX; then
        pkg install -y libuv 2>/dev/null || warn "libuv через pkg недоступен"
    else
        apt_install libuv1-dev 2>/dev/null || warn "libuv1-dev недоступен — пробую вендорный libuv"
    fi
    if UVLOOP_USE_SYSTEM_LIBUV=1 "$PIP" install --prefer-binary --no-cache-dir \
           --no-warn-script-location --disable-pip-version-check --quiet "uvloop>=0.19.0" 2>/dev/null; then
        ok "uvloop установлен (system libuv)"
    elif "$PIP" install --no-cache-dir --no-warn-script-location \
             --disable-pip-version-check --quiet "uvloop>=0.19.0" 2>/dev/null; then
        ok "uvloop установлен"
    else
        warn "uvloop не установился — бот будет работать на стандартном asyncio"
    fi
fi

step "Проверка ключевых модулей"
"$PYTHON_VENV" -c "import telethon" 2>/dev/null && ok "telethon ✓" || err "telethon не найден — установка не удалась!"
"$PYTHON_VENV" -c "import aiohttp"  2>/dev/null && ok "aiohttp ✓"  || warn "aiohttp не найден"
"$PYTHON_VENV" -c "import aiogram"  2>/dev/null && ok "aiogram ✓"  || warn "aiogram не найден — нотификатор недоступен"
"$PYTHON_VENV" -c "import pydantic" 2>/dev/null && ok "pydantic ✓" || warn "pydantic не найден"
"$PYTHON_VENV" -c "import cryptography" 2>/dev/null && ok "cryptography ✓" || warn "cryptography не найдена (fallback активен)"
"$PYTHON_VENV" -c "import PIL" 2>/dev/null && ok "Pillow ✓" || warn "Pillow не найден"
"$PYTHON_VENV" -c "import uvloop" 2>/dev/null && ok "uvloop ✓" || warn "uvloop не найден (стандартный asyncio)"
"$PYTHON_VENV" -c "import cryptg" 2>/dev/null && ok "cryptg ✓" || warn "cryptg не найден (фолбэк на tgcrypto)"

step "Прекомпиляция байткода"
unset PYTHONDONTWRITEBYTECODE
"$PYTHON_VENV" -m compileall -q -j 0 "$INSTALL_DIR/kitsune" 2>/dev/null && ok "Байткод скомпилирован" || \
    warn "Не удалось прекомпилировать байткод — первый запуск будет медленнее"
"$PYTHON_VENV" -m compileall -q -j 0 "$VENV_DIR/lib" 2>/dev/null && ok "Байткод зависимостей скомпилирован" || \
    info "Прекомпиляция зависимостей пропущена"

step "Директории и права"
mkdir -p "$HOME/.kitsune/modules" "$HOME/.kitsune/logs"
chmod 700 "$HOME/.kitsune"
chmod 755 "$HOME/.kitsune/modules" "$HOME/.kitsune/logs"
[[ -f "$HOME/.kitsune/kitsune.session" ]]     && chmod 600 "$HOME/.kitsune/kitsune.session"     || true
[[ -f "$HOME/.kitsune/kitsune.session.enc" ]] && chmod 600 "$HOME/.kitsune/kitsune.session.enc" || true
ok "Директории: ~/.kitsune/"

step "Режим экономии ресурсов (KITSUNE_LOW_POWER)"

LOW_POWER_TRUE_VALUE="1"
LOW_POWER_FALSE_VALUE="0"

detect_weak_hardware() {
    if $IS_TERMUX || $IS_USERLAND; then
        LOW_POWER_REASON="мобильное окружение (Termux/UserLand)"
        return 0
    fi
    local _mem_kb=0
    if [[ -r /proc/meminfo ]]; then
        _mem_kb=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo 0)
    fi
    if [[ -n "$_mem_kb" ]] && [[ "$_mem_kb" =~ ^[0-9]+$ ]] && (( _mem_kb > 0 && _mem_kb < 2097152 )); then
        LOW_POWER_REASON="мало RAM (< 2 GB)"
        return 0
    fi
    local _cpus=0
    _cpus=$(nproc 2>/dev/null || echo 0)
    if [[ "$_cpus" =~ ^[0-9]+$ ]] && (( _cpus > 0 && _cpus <= 2 )); then
        LOW_POWER_REASON="мало ядер CPU (<= 2)"
        return 0
    fi
    LOW_POWER_REASON="достаточно ресурсов"
    return 1
}

LOW_POWER_REASON=""
LOW_POWER_SOURCE=""

if [[ -n "${KITSUNE_LOW_POWER:-}" ]]; then
    LOW_POWER_SOURCE="переменная окружения"
    info "KITSUNE_LOW_POWER уже задан в окружении: ${KITSUNE_LOW_POWER} — не меняю"
else
    if detect_weak_hardware; then
        KITSUNE_LOW_POWER="$LOW_POWER_TRUE_VALUE"
        LOW_POWER_SOURCE="автоопределение: $LOW_POWER_REASON"
        info "Обнаружено слабое железо: $LOW_POWER_REASON"
    else
        KITSUNE_LOW_POWER="$LOW_POWER_FALSE_VALUE"
        LOW_POWER_SOURCE="автоопределение: $LOW_POWER_REASON"
        info "Железо выглядит достаточным ($LOW_POWER_REASON)"
    fi

    if [[ -t 0 ]] && [[ -z "${KITSUNE_NONINTERACTIVE:-}" ]]; then
        _default_hint="n"
        [[ "$KITSUNE_LOW_POWER" == "$LOW_POWER_TRUE_VALUE" ]] && _default_hint="y"
        echo ""
        echo -e "${CYAN}Включить режим экономии ресурсов (low power)?${RESET}"
        echo -e "  ${YELLOW}Он снижает частоту записи в БД, уменьшает число ретраев,"
        echo -e "  отключает hydrogram и веб-панель — полезно на слабых устройствах.${RESET}"
        read -r -t 30 -p "  Включить? [y/N] (по умолчанию: $_default_hint) " _lp_answer || _lp_answer=""
        case "$(echo "${_lp_answer:-}" | tr '[:upper:]' '[:lower:]')" in
            y|yes|1|true|on|t)
                KITSUNE_LOW_POWER="$LOW_POWER_TRUE_VALUE"
                LOW_POWER_SOURCE="выбор пользователя"
                ;;
            n|no|0|false|off|f)
                KITSUNE_LOW_POWER="$LOW_POWER_FALSE_VALUE"
                LOW_POWER_SOURCE="выбор пользователя"
                ;;
            *)
                info "Оставляю значение по умолчанию: $KITSUNE_LOW_POWER"
                ;;
        esac
    else
        info "Неинтерактивный режим — оставляю автоопределённое значение"
    fi
fi

export KITSUNE_LOW_POWER
ok "KITSUNE_LOW_POWER=$KITSUNE_LOW_POWER ($LOW_POWER_SOURCE)"

persist_low_power_rc() {
    local _rc="$1"
    local _line="export KITSUNE_LOW_POWER=\"$KITSUNE_LOW_POWER\""
    [[ -e "$_rc" ]] || touch "$_rc" 2>/dev/null || return 1
    if grep -q '^[[:space:]]*export[[:space:]]\+KITSUNE_LOW_POWER=' "$_rc" 2>/dev/null; then
        sed -i "s|^[[:space:]]*export[[:space:]]\+KITSUNE_LOW_POWER=.*|$_line|" "$_rc" \
            && ok "KITSUNE_LOW_POWER обновлён в $_rc" \
            || warn "Не удалось обновить KITSUNE_LOW_POWER в $_rc"
    else
        {
            echo ""
            echo "# Kitsune: режим экономии ресурсов (добавлено установщиком)"
            echo "$_line"
        } >> "$_rc" && ok "KITSUNE_LOW_POWER добавлен в $_rc" \
            || warn "Не удалось записать KITSUNE_LOW_POWER в $_rc"
    fi
}

for _RC in "$HOME/.bashrc" "$HOME/.profile"; do
    persist_low_power_rc "$_RC" || true
done

case "$(echo "$KITSUNE_LOW_POWER" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on|y|t)
        touch "$INSTALL_DIR/config.toml" 2>/dev/null || true
        if [[ -f "$INSTALL_DIR/config.toml" ]]; then
            if grep -q '^[[:space:]]*low_power[[:space:]]*=' "$INSTALL_DIR/config.toml" 2>/dev/null; then
                info "low_power уже задан в config.toml — не меняю"
            else
                echo 'low_power = true' >> "$INSTALL_DIR/config.toml"
                ok "Режим экономии ресурсов записан в config.toml (low_power = true)"
            fi
        fi
        ;;
    *)
        info "low_power в config.toml не пишу (KITSUNE_LOW_POWER=$KITSUNE_LOW_POWER)"
        ;;
esac

step "Настройка PATH"
_PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
for _RC in "$HOME/.bashrc" "$HOME/.profile"; do
    if [[ -f "$_RC" ]] && ! grep -qF '.local/bin' "$_RC" 2>/dev/null; then
        echo "" >> "$_RC"
        echo "# Kitsune: добавлено установщиком" >> "$_RC"
        echo "$_PATH_LINE" >> "$_RC"
        ok "PATH: добавлено ~/.local/bin → $_RC"
    fi
done
export PATH="$HOME/.local/bin:$PATH"

step "Скрипт запуска"
if $IS_TERMUX; then
    if [[ -z "${NO_AUTOSTART:-}" ]]; then
        cat > "$HOME/.bash_profile" << PROFILE
clear
echo -e "\033[1;35mKitsune Userbot\033[0m"
export KITSUNE_LOW_POWER="$KITSUNE_LOW_POWER"
export LANG="\${LANG:-C.UTF-8}"
export LC_ALL="\${LC_ALL:-C.UTF-8}"
export PYTHONIOENCODING="utf-8"
export PYTHONUTF8=1
cd "$INSTALL_DIR" && "$PYTHON_VENV" -m kitsune
PROFILE
        ok "Автозапуск настроен (~/.bash_profile), KITSUNE_LOW_POWER=$KITSUNE_LOW_POWER"
    fi
elif $IS_USERLAND; then
    cat > "$HOME/start_kitsune.sh" << ULSCRIPT
mkdir -p "\$HOME/tmp"
export TMPDIR="\$HOME/tmp"
export KITSUNE_LOW_POWER="$KITSUNE_LOW_POWER"
export LANG="\${LANG:-C.UTF-8}"
export LC_ALL="\${LC_ALL:-C.UTF-8}"
export PYTHONIOENCODING="utf-8"
export PYTHONUTF8=1
cd "$INSTALL_DIR"
if [[ -r /dev/tty ]]; then
    exec "$PYTHON_VENV" -m kitsune < /dev/tty
else
    exec "$PYTHON_VENV" -m kitsune
fi
ULSCRIPT
    chmod +x "$HOME/start_kitsune.sh"
    ok "Скрипт запуска создан: ~/start_kitsune.sh (KITSUNE_LOW_POWER=$KITSUNE_LOW_POWER)"
elif $IS_ALPINE; then
    cat > "$HOME/start_kitsune.sh" << ALPSCRIPT
#!/bin/sh
export KITSUNE_LOW_POWER="$KITSUNE_LOW_POWER"
export LANG="\${LANG:-C.UTF-8}"
export LC_ALL="\${LC_ALL:-C.UTF-8}"
export PYTHONIOENCODING="utf-8"
export PYTHONUTF8=1
cd "$INSTALL_DIR"
if [ -r /dev/tty ]; then
    exec "$PYTHON_VENV" -m kitsune < /dev/tty
else
    exec "$PYTHON_VENV" -m kitsune
fi
ALPSCRIPT
    chmod +x "$HOME/start_kitsune.sh"
    ok "Скрипт запуска создан: ~/start_kitsune.sh (в Alpine нет systemd — автозапуск не настраивается)"
elif ( $IS_UBUNTU || $IS_ARCH ) && [[ -z "${NO_AUTOSTART:-}" ]] && [[ -d "/etc/systemd/system" ]]; then
    SERVICE_FILE="/etc/systemd/system/kitsune.service"
    $SUDO tee "$SERVICE_FILE" > /dev/null << SERVICE
[Unit]
Description=Kitsune Userbot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
Environment=KITSUNE_LOW_POWER=$KITSUNE_LOW_POWER
Environment=PYTHONIOENCODING=utf-8
Environment=PYTHONUTF8=1
Environment=LANG=C.UTF-8
ExecStart=$PYTHON_VENV -m kitsune
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE
    $SUDO systemctl daemon-reload 2>/dev/null || true
    $SUDO systemctl enable kitsune 2>/dev/null || true
    ok "systemd сервис создан (Environment=KITSUNE_LOW_POWER=$KITSUNE_LOW_POWER)"
fi

echo ""
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${GREEN}${BOLD}🦊 Kitsune успешно установлен!${RESET}"
echo -e "  ${CYAN}Директория:${RESET} $INSTALL_DIR"
echo -e "  ${CYAN}KITSUNE_LOW_POWER:${RESET} $KITSUNE_LOW_POWER  ${YELLOW}($LOW_POWER_SOURCE)${RESET}"
echo -e "  ${CYAN}Вход:${RESET} KITSUNE_LOGIN=qr — вход по QR-коду, KITSUNE_LOGIN=web — вход через веб-страницу"
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""

cd "$INSTALL_DIR"
if [[ -r /dev/tty ]]; then
    exec "$PYTHON_VENV" -m kitsune < /dev/tty
else
    exec "$PYTHON_VENV" -m kitsune
fi
