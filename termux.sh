#!/usr/bin/env bash
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
MAGENTA='\033[1;35m'; YELLOW='\033[1;33m'; RESET='\033[0m'; BOLD='\033[1m'

ok()   { echo -e "${GREEN}✅  $*${RESET}"; }
info() { echo -e "${CYAN}ℹ️   $*${RESET}"; }
warn() { echo -e "${YELLOW}⚠️   $*${RESET}"; }
err()  { echo -e "${RED}❌  $*${RESET}"; exit 1; }
step() { echo -e "\n${MAGENTA}${BOLD}── $* ──${RESET}"; }

pip_cmd() {
    if [[ -n "${PYTHON:-}" ]]; then
        "$PYTHON" -m pip "$@"
    else
        pip "$@"
    fi
}

pip_install() {
    local pkg="$1"
    pip_cmd install --prefer-binary --no-cache-dir -q "$pkg" 2>/dev/null && return 0
    pip_cmd install --no-build-isolation --no-cache-dir -q "$pkg" 2>/dev/null && return 0
    pip_cmd install --no-cache-dir -q "$pkg" 2>/dev/null && return 0
    return 1
}

if [[ -z "${PREFIX:-}" || "$PREFIX" != *"com.termux"* ]]; then
    err "Этот скрипт предназначен только для Termux!"
fi

clear
echo -e "${MAGENTA}${BOLD}  🦊 Kitsune Userbot — Termux Install${RESET}\n"

step "Обновление пакетов"
pkg update -y -q 2>/dev/null || true
ok "Пакеты обновлены"

step "Базовые зависимости"
pkg install -y git python python-pip libjpeg-turbo openssl libffi zlib build-essential 2>/dev/null || true
ok "Базовые пакеты установлены"

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
    local cmd path fallback="" fallback_ver=""
    while read -r cmd; do
        command -v "$cmd" &>/dev/null || continue
        path=$(command -v "$cmd")
        py_version_ok "$path" || continue
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
        return 0
    fi
    return 1
}

step "Проверка версии Python"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo ".")"
for _pp in "$SCRIPT_DIR/pyproject.toml" "$HOME/Kitsune/pyproject.toml" "./pyproject.toml"; do
    if read_requires_python "$_pp"; then
        info "requires-python: ${REQ_PY_MAJOR}.${REQ_PY_MINOR}+"
        break
    fi
done
REQ_PY="${REQ_PY_MAJOR}.${REQ_PY_MINOR}"

PYTHON=""
PYTHON_VER=""
if ! pick_python; then
    warn "Python ${REQ_PY}+ не найден — обновляю Termux-пакеты..."
    pkg upgrade -y -q 2>/dev/null || true
    pkg install -y python python-pip 2>/dev/null || true
    pick_python || err "В Termux нет Python ${REQ_PY}+ (текущий: $(python3 -V 2>&1)).
    Обнови Termux из F-Droid/GitHub и выполни: pkg upgrade && pkg install python
    Зависимость cryptg>=0.6.0 требует Python ${REQ_PY}+ и понижена не будет."
fi
ok "Python: $PYTHON ($PYTHON_VER), требуется ${REQ_PY}+"
export PATH="$(dirname "$PYTHON"):$PATH"

step "Нативные Python-пакеты (без компиляции)"
pkg install -y python-psutil 2>/dev/null && ok "psutil установлен (нативный)" || \
    warn "psutil недоступен — мониторинг ресурсов отключён"
pkg install -y python-cryptography 2>/dev/null && ok "cryptography установлена (нативная)" || {
    warn "python-cryptography через pkg недоступен — пробую pip..."
    pip_install "cryptography" && ok "cryptography установлена (pip)" || \
        warn "cryptography не установилась — используется встроенный fallback"
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
pip_install "Pillow" && ok "Pillow установлен" || warn "Pillow не установился"

step "Клонирование репозитория"
INSTALL_DIR="$HOME/Kitsune"

mkdir -p "$HOME" 2>/dev/null || true

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Обновляю существующий репозиторий..."
    cd "$INSTALL_DIR" && git pull --ff-only origin main || \
        warn "git pull не удался, продолжаю с текущей версией"
else
    if [[ -e "$INSTALL_DIR" ]]; then
        warn "Папка $INSTALL_DIR существует, но без .git — удаляю и пересоздаю..."
        rm -rf "$INSTALL_DIR" || err "Не удалось удалить $INSTALL_DIR (проверь права)"
    fi

    info "Клонирую в $INSTALL_DIR ..."
    git clone https://github.com/KitsuneX-dev/Kitsune "$INSTALL_DIR" \
        || err "Не удалось клонировать репозиторий. Проверь интернет-соединение."

    if [[ ! -d "$INSTALL_DIR" ]]; then
        warn "Папка $INSTALL_DIR не создана — создаю вручную и повторяю клон..."
        mkdir -p "$INSTALL_DIR" || err "Не удалось создать $INSTALL_DIR"
        git clone https://github.com/KitsuneX-dev/Kitsune "$INSTALL_DIR" \
            || err "Повторный клон не удался."
    fi
fi

if [[ ! -d "$INSTALL_DIR" ]]; then
    err "Критическая ошибка: папка $INSTALL_DIR не создана."
fi
cd "$INSTALL_DIR" || err "Не удалось перейти в $INSTALL_DIR"
ok "Репозиторий готов: $INSTALL_DIR"

step "Telethon (основная библиотека)"
pip_install "telethon>=1.36.0" && ok "Telethon установлен" || \
    err "Telethon не установился — без него бот не запустится!"

step "Python зависимости"
REQ_FILE="requirements-termux.txt"
[[ ! -f "$REQ_FILE" ]] && REQ_FILE="requirements.txt"
info "Устанавливаю из $REQ_FILE..."

FAILED_PKGS=()
ORJSON_OK=false
while IFS= read -r pkg || [[ -n "$pkg" ]]; do
    [[ -z "$pkg" || "${pkg:0:1}" == "#" ]] && continue
    [[ "$pkg" == telethon* ]] && continue
    [[ "$pkg" == aiogram* ]] && continue
    [[ "$pkg" == pydantic* ]] && continue
    if [[ "$pkg" == orjson* ]]; then
        if pip_cmd install --prefer-binary --only-binary=:all: --no-cache-dir -q "$pkg" 2>/dev/null; then
            ORJSON_OK=true
            ok "orjson установлен (prebuilt wheel)"
        else
            info "orjson официально не поддерживает Android/Termux — Kitsune использует стандартный json"
        fi
        continue
    fi
    if pip_install "$pkg"; then
        true
    else
        warn "Не удалось установить: $pkg"
        FAILED_PKGS+=("$pkg")
    fi
done < "$REQ_FILE"

if ! $ORJSON_OK; then
    info "JSON-бэкенд: стандартный json (фолбэк kitsune/_json.py, работает без orjson)"
fi

if [[ ${#FAILED_PKGS[@]} -gt 0 ]]; then
    warn "Не установились пакеты: ${FAILED_PKGS[*]}"
else
    ok "Все зависимости установлены"
fi

step "aiogram + pydantic"

PYDANTIC_OK=false
NOTIFIER_DISABLED_REASON=""

pydantic2_present() {
    "$PYTHON" - <<'PYCHECK' 2>/dev/null
import sys
try:
    import pydantic
except Exception:
    sys.exit(1)
major = int(str(pydantic.VERSION).split(".")[0])
sys.exit(0 if major >= 2 else 1)
PYCHECK
}

ensure_rust_toolchain() {
    if command -v cargo >/dev/null 2>&1; then
        return 0
    fi
    info "Для сборки pydantic-core нужен Rust — устанавливаю через pkg (это долго)"
    pkg install -y rust binutils build-essential 2>/dev/null || true
    command -v cargo >/dev/null 2>&1
}

if pydantic2_present; then
    PYDANTIC_OK=true
    ok "pydantic 2.x уже установлен"
elif pip_cmd install --prefer-binary --only-binary=:all: --no-cache-dir -q "pydantic>=2.7.0" 2>/dev/null && pydantic2_present; then
    PYDANTIC_OK=true
    ok "pydantic 2.x установлен (prebuilt wheel)"
else
    info "Готового wheel для pydantic-core под Android нет — пробую собрать из исходников"
    if ensure_rust_toolchain; then
        if CARGO_BUILD_JOBS=1 pip_cmd install --no-cache-dir -q "pydantic>=2.7.0" 2>/dev/null && pydantic2_present; then
            PYDANTIC_OK=true
            ok "pydantic 2.x установлен (pydantic-core собран через cargo)"
        elif CARGO_BUILD_JOBS=1 pip_cmd install --no-build-isolation --no-cache-dir -q "pydantic>=2.7.0" 2>/dev/null && pydantic2_present; then
            PYDANTIC_OK=true
            ok "pydantic 2.x установлен (сборка без изоляции)"
        else
            NOTIFIER_DISABLED_REASON="сборка pydantic-core (Rust) в Termux не удалась"
        fi
    else
        NOTIFIER_DISABLED_REASON="Rust-тулчейн (cargo) недоступен, а pydantic-core собирается только из исходников"
    fi
fi

if $PYDANTIC_OK; then
    if pip_install "aiogram>=3.7.0"; then
        ok "aiogram установлен"
    elif pip_cmd install --prefer-binary --no-cache-dir -q "aiogram" 2>/dev/null; then
        ok "aiogram установлен (последняя доступная версия)"
    else
        NOTIFIER_DISABLED_REASON="aiogram не установился"
    fi
else
    warn "aiogram требует pydantic>=2.7.0 — пропускаю установку aiogram"
    warn "Понижение до pydantic 1.x запрещено: оно ломает aiogram 3.x"
fi

if [[ -n "$NOTIFIER_DISABLED_REASON" ]]; then
    echo ""
    warn "Бот-нотификатор ОТКЛЮЧЁН: $NOTIFIER_DISABLED_REASON"
    info "Kitsune запустится и будет работать полностью, кроме inline-бота и уведомлений."
    info "Чтобы включить нотификатор позже, выполни в Termux:"
    info "    pkg install rust binutils build-essential"
    info "    pip install 'pydantic>=2.7.0' 'aiogram>=3.7.0'"
fi

step "Hydrogram"
pip_install "hydrogram" && \
    ok "Hydrogram установлен" || warn "Hydrogram не установился — продолжаю без него"

if pip_cmd install --prefer-binary --no-cache-dir -q "tgcrypto>=1.2.5" 2>/dev/null; then
    ok "tgcrypto установлен (prebuilt wheel)"
else
    info "Prebuilt wheel не найден — собираю tgcrypto из исходников..."
    _BUILD_OK=false

    if pip_cmd install --no-cache-dir -q "tgcrypto>=1.2.5" 2>/dev/null; then
        _BUILD_OK=true

    elif pip_cmd install --no-build-isolation --no-cache-dir -q "tgcrypto>=1.2.5" 2>/dev/null; then
        _BUILD_OK=true
    fi
    if $_BUILD_OK; then
        ok "tgcrypto установлен (собран из исходников)"
    else
        warn "tgcrypto не установился — Hydrogram будет работать без C-ускорения"
    fi
fi

step "cryptg (ускорение AES-IGE для Telethon)"
if python3 -c "import cryptg" 2>/dev/null; then
    ok "cryptg уже установлен"
else
    _CRYPTG_OK=false
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
        _CRYPTG_SPEC="cryptg>=0.6.0"
    else
        _CRYPTG_SPEC="cryptg>=0.4.0,<0.6.0"
        info "cryptg 0.6+ требует Python 3.11+ — использую совместимую ветку 0.5.x"
    fi
    if pip_cmd install --prefer-binary --only-binary=:all: --no-cache-dir -q "$_CRYPTG_SPEC" 2>/dev/null; then
        _CRYPTG_OK=true
        ok "cryptg установлен (prebuilt wheel)"
    elif command -v cargo >/dev/null 2>&1; then
        warn "prebuilt wheel для cryptg нет — пробую собрать через cargo (это долго)"
        if pip_cmd install --no-cache-dir -q "$_CRYPTG_SPEC" 2>/dev/null; then
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
pkg install -y libuv 2>/dev/null && ok "libuv установлен (нативный)" || \
    warn "libuv через pkg недоступен — пробую собрать uvloop с вендорным libuv"
if UVLOOP_USE_SYSTEM_LIBUV=1 pip_cmd install --prefer-binary --no-cache-dir -q "uvloop>=0.19.0" 2>/dev/null; then
    ok "uvloop установлен (system libuv)"
elif pip_install "uvloop>=0.19.0"; then
    ok "uvloop установлен"
else
    warn "uvloop не установился — бот будет работать на стандартном asyncio"
fi

step "Директории и права"
mkdir -p "$HOME/.kitsune/modules" "$HOME/.kitsune/logs"
chmod 700 "$HOME/.kitsune"
chmod 755 "$HOME/.kitsune/modules"
chmod 755 "$HOME/.kitsune/logs"
[[ -f "$HOME/.kitsune/kitsune.session" ]]     && chmod 600 "$HOME/.kitsune/kitsune.session"     || true
[[ -f "$HOME/.kitsune/kitsune.session.enc" ]] && chmod 600 "$HOME/.kitsune/kitsune.session.enc" || true
ok "Директории созданы, права выставлены"

step "Проверка установки"
python3 -c "import telethon"      2>/dev/null && ok "telethon ✓"      || err "telethon не найден — установка не удалась!"
python3 -c "import aiohttp"       2>/dev/null && ok "aiohttp ✓"       || warn "aiohttp не найден"
python3 -c "import aiogram"       2>/dev/null && ok "aiogram ✓"       || warn "aiogram не найден — нотификатор недоступен"
python3 -c "import cryptography"  2>/dev/null && ok "cryptography ✓"  || warn "cryptography не найдена (fallback активен)"
python3 -c "import psutil"        2>/dev/null && ok "psutil ✓"        || warn "psutil не найден (мониторинг отключён)"
if pydantic2_present; then
    ok "pydantic 2.x ✓"
else
    warn "pydantic 2.x не найден — нотификатор отключён (см. подсказку выше)"
fi
python3 -c "import orjson"        2>/dev/null && ok "orjson ✓"        || info "orjson не найден — используется стандартный json (это нормально для Termux)"
python3 -c "import uvloop"        2>/dev/null && ok "uvloop ✓"        || warn "uvloop не найден (стандартный asyncio)"
python3 -c "import cryptg"        2>/dev/null && ok "cryptg ✓"        || warn "cryptg не найден (фолбэк на tgcrypto)"

step "Прекомпиляция байткода"
unset PYTHONDONTWRITEBYTECODE
python3 -m compileall -q -j 0 "$INSTALL_DIR/kitsune" 2>/dev/null && ok "Байткод скомпилирован" || \
    warn "Не удалось прекомпилировать байткод — первый запуск будет медленнее"
SITE_PACKAGES=$(python3 -c "import site; print(site.getsitepackages()[0])" 2>/dev/null || true)
if [[ -n "$SITE_PACKAGES" && -d "$SITE_PACKAGES" ]]; then
    python3 -m compileall -q -j 0 "$SITE_PACKAGES" 2>/dev/null && ok "Байткод зависимостей скомпилирован" || \
        info "Прекомпиляция зависимостей пропущена"
fi

step "Режим экономии ресурсов (KITSUNE_LOW_POWER)"

LOW_POWER_TRUE_VALUE="1"
LOW_POWER_FALSE_VALUE="0"

if [[ -n "${KITSUNE_LOW_POWER:-}" ]]; then
    LOW_POWER_SOURCE="переменная окружения"
    info "KITSUNE_LOW_POWER уже задан в окружении: ${KITSUNE_LOW_POWER} — не меняю"
else
    KITSUNE_LOW_POWER="$LOW_POWER_TRUE_VALUE"
    LOW_POWER_SOURCE="по умолчанию для Termux"
    info "Termux — включаю режим экономии ресурсов по умолчанию"
fi

export KITSUNE_LOW_POWER
ok "KITSUNE_LOW_POWER=$KITSUNE_LOW_POWER ($LOW_POWER_SOURCE)"

persist_low_power_rc() {
    local _rc="$1"
    local _line="export KITSUNE_LOW_POWER=\"$KITSUNE_LOW_POWER\""
    [[ -e "$_rc" ]] || touch "$_rc" 2>/dev/null || return 1
    if grep -q '^[[:space:]]*export[[:space:]]\+KITSUNE_LOW_POWER=' "$_rc" 2>/dev/null; then
        sed -i "s|^[[:space:]]*export[[:space:]]\\+KITSUNE_LOW_POWER=.*|$_line|" "$_rc" \
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

step "Автозапуск"
if [[ -z "${NO_AUTOSTART:-}" ]]; then
    echo '' > "${PREFIX}/etc/motd" 2>/dev/null || true
    cat > "$HOME/.bash_profile" << PROFILE
clear
echo -e "\033[1;35m  🦊 Kitsune Userbot\033[0m"
export KITSUNE_LOW_POWER="$KITSUNE_LOW_POWER"
cd "\$HOME/Kitsune" && "$PYTHON" -m kitsune
PROFILE
    ok "Автозапуск настроен (~/.bash_profile), KITSUNE_LOW_POWER=$KITSUNE_LOW_POWER"
fi

echo ""
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  ${GREEN}${BOLD}🦊 Готово!${RESET}"
echo -e "  ${CYAN}Запуск:${RESET} cd ~/Kitsune && $PYTHON -m kitsune"
echo -e "  ${YELLOW}Конфиг:${RESET} ~/Kitsune/config.toml"
echo -e "  ${CYAN}KITSUNE_LOW_POWER:${RESET} $KITSUNE_LOW_POWER  ${YELLOW}($LOW_POWER_SOURCE)${RESET}"
echo -e "${MAGENTA}${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"

"$PYTHON" -m kitsune
