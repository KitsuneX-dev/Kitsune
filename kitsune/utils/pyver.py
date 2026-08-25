from __future__ import annotations

import inspect
import os
import re
import shutil
import subprocess
import sys
import tempfile
import typing

__all__ = [
    "FALLBACK_REQUIRED",
    "REEXEC_ENV_FLAG",
    "parse_version",
    "parse_requires_python",
    "read_requires_python",
    "current_version",
    "version_ok",
    "format_version",
    "candidate_names",
    "excluded_paths",
    "find_interpreters",
    "select_interpreter",
    "probe_interpreter_sync",
    "probe_interpreter_async",
    "venv_available_async",
    "find_interpreters_async",
    "install_python_async",
    "venv_python",
    "default_requirements",
    "requirement_name",
    "is_optional_requirement",
    "read_requirement_lines",
    "pip_install_requirements_async",
    "rebuild_venv_async",
    "ensure_python_async",
    "ensure_startup_python",
    "missing_python_message",
]

FALLBACK_REQUIRED = (3, 12)

REEXEC_ENV_FLAG = "KITSUNE_PYVER_SWITCHED"

_VER_RE = re.compile(r"(\d+)\.(\d+)")

_REQ_RE = re.compile(r"requires-python\s*=\s*[\"']([^\"']+)[\"']")

_SPEC_RE = re.compile(r"^(>=|==|~=|>)(\d+)\.(\d+)")

_CANDIDATE_SPAN = 6

_PROBE_TIMEOUT = 30

_VENV_PROBE_TIMEOUT = 90

_VENV_BUILD_TIMEOUT = 600

_PIP_TIMEOUT = 1800

_PIP_ONE_TIMEOUT = 600

_OPTIONAL_PACKAGES = frozenset({"cryptg", "tgcrypto", "uvloop", "hydrogram"})

_REQ_NAME_SPLIT_RE = re.compile(r"[<>=!~\s]")

_APT_UPDATE_TIMEOUT = 600

_APT_INSTALL_TIMEOUT = 1800

_VERSION_SNIPPET = "import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1]))"


def parse_version(text: typing.Any) -> tuple[int, int] | None:
    if text is None:
        return None
    if isinstance(text, (bytes, bytearray)):
        text = text.decode(errors="replace")
    if isinstance(text, (tuple, list)):
        if len(text) < 2:
            return None
        try:
            return (int(text[0]), int(text[1]))
        except (TypeError, ValueError):
            return None
    m = _VER_RE.search(str(text).strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def parse_requires_python(spec: typing.Any) -> tuple[int, int] | None:
    if not spec:
        return None
    best: tuple[int, int] | None = None
    for raw in str(spec).replace(" ", "").split(","):
        if not raw:
            continue
        m = _SPEC_RE.match(raw)
        if not m:
            continue
        ver = (int(m.group(2)), int(m.group(3)))
        if m.group(1) == ">":
            ver = (ver[0], ver[1] + 1)
        if best is None or ver > best:
            best = ver
    return best


def _repo_root(repo_path: str | None = None) -> str:
    if repo_path:
        return os.path.abspath(repo_path)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def read_requires_python(
    repo_path: str | None = None,
    *,
    default: tuple[int, int] = FALLBACK_REQUIRED,
) -> tuple[int, int]:
    path = os.path.join(_repo_root(repo_path), "pyproject.toml")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return tuple(default)
    m = _REQ_RE.search(text)
    if not m:
        return tuple(default)
    parsed = parse_requires_python(m.group(1))
    return tuple(parsed) if parsed else tuple(default)


def current_version() -> tuple[int, int]:
    return (sys.version_info[0], sys.version_info[1])


def version_ok(
    required: typing.Sequence[int],
    current: typing.Sequence[int] | None = None,
) -> bool:
    cur = tuple(current) if current is not None else current_version()
    return cur >= tuple(required)


def format_version(version: typing.Sequence[int] | None) -> str:
    if not version:
        return "?"
    return ".".join(str(int(part)) for part in version)


def candidate_names(
    required: typing.Sequence[int],
    span: int = _CANDIDATE_SPAN,
) -> list[str]:
    major, minor = int(required[0]), int(required[1])
    names = [f"python{major}.{minor + offset}" for offset in range(span, -1, -1)]
    names.append(f"python{major}")
    names.append("python")
    return names


def _real(path: str) -> str:
    try:
        return os.path.realpath(path)
    except OSError:
        return path


def excluded_paths(executable: str | None = None) -> set[str]:
    exe = executable if executable is not None else sys.executable
    out: set[str] = set()
    if exe:
        out.add(exe)
        out.add(_real(exe))
    return out


def _resolve(name: str, which: typing.Callable[[str], str | None]) -> str | None:
    if os.path.sep in name or (os.path.altsep and os.path.altsep in name):
        return name if os.path.exists(name) or os.path.isabs(name) else None
    return which(name)


def find_interpreters(
    required: typing.Sequence[int],
    *,
    probe: typing.Callable[[str], typing.Mapping[str, typing.Any] | None],
    which: typing.Callable[[str], str | None] = shutil.which,
    names: typing.Sequence[str] | None = None,
    exclude: typing.Iterable[str] | None = None,
) -> list[dict[str, typing.Any]]:
    req = tuple(required)
    name_list = list(names) if names is not None else candidate_names(req)
    skip = set(exclude) if exclude is not None else excluded_paths()
    seen: set[str] = set()
    found: list[dict[str, typing.Any]] = []
    for name in name_list:
        path = _resolve(name, which)
        if not path:
            continue
        real = _real(path)
        if path in skip or real in skip:
            continue
        if real in seen:
            continue
        seen.add(real)
        info = probe(path)
        if not info:
            continue
        version = parse_version(info.get("version"))
        if not version or version < req:
            continue
        found.append({
            "name": name,
            "path": path,
            "real": real,
            "version": version,
            "can_venv": bool(info.get("can_venv")),
        })
    return found


def select_interpreter(
    interpreters: typing.Iterable[typing.Mapping[str, typing.Any]],
    required: typing.Sequence[int] | None = None,
) -> dict[str, typing.Any] | None:
    req = tuple(required) if required is not None else None
    usable: list[dict[str, typing.Any]] = []
    for info in interpreters:
        version = parse_version(info.get("version"))
        if not version:
            continue
        if req is not None and version < req:
            continue
        item = dict(info)
        item["version"] = version
        item["can_venv"] = bool(info.get("can_venv"))
        usable.append(item)
    if not usable:
        return None
    usable.sort(key=lambda i: (1 if i["can_venv"] else 0, i["version"]), reverse=True)
    return usable[0]


def _venv_probe_dir() -> str:
    return tempfile.mkdtemp(prefix="kitsune_pyver_")


def probe_interpreter_sync(
    path: str,
    *,
    venv_check: bool = True,
    timeout: float = _PROBE_TIMEOUT,
) -> dict[str, typing.Any] | None:
    try:
        proc = subprocess.run(
            [path, "-c", _VERSION_SNIPPET],
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    version = parse_version(proc.stdout)
    if not version:
        return None
    can_venv = False
    if venv_check:
        tmp = None
        try:
            tmp = _venv_probe_dir()
            target = os.path.join(tmp, "probe")
            vproc = subprocess.run(
                [path, "-m", "venv", "--without-pip", target],
                capture_output=True,
                timeout=_VENV_PROBE_TIMEOUT,
            )
            can_venv = vproc.returncode == 0
        except (OSError, subprocess.SubprocessError):
            can_venv = False
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
    return {"version": version, "can_venv": can_venv}


async def _run(
    args: typing.Sequence[str],
    timeout: float,
    cwd: str | None = None,
) -> tuple[int, bytes, bytes]:
    from .proc import run_cmd

    return await run_cmd([str(a) for a in args], timeout=timeout, cwd=cwd)


async def venv_available_async(path: str) -> bool:
    tmp = None
    try:
        tmp = _venv_probe_dir()
    except OSError:
        return False
    try:
        target = os.path.join(tmp, "probe")
        rc, _out, _err = await _run(
            [path, "-m", "venv", "--without-pip", target],
            _VENV_PROBE_TIMEOUT,
        )
        return rc == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def probe_interpreter_async(
    path: str,
    *,
    venv_check: bool = True,
) -> dict[str, typing.Any] | None:
    rc, out, _err = await _run([path, "-c", _VERSION_SNIPPET], _PROBE_TIMEOUT)
    if rc != 0:
        return None
    version = parse_version(out)
    if not version:
        return None
    can_venv = await venv_available_async(path) if venv_check else False
    return {"version": version, "can_venv": can_venv}


async def find_interpreters_async(
    required: typing.Sequence[int],
    *,
    names: typing.Sequence[str] | None = None,
    exclude: typing.Iterable[str] | None = None,
    venv_check: bool = True,
) -> list[dict[str, typing.Any]]:
    req = tuple(required)
    name_list = list(names) if names is not None else candidate_names(req)
    skip = set(exclude) if exclude is not None else excluded_paths()
    seen: set[str] = set()
    found: list[dict[str, typing.Any]] = []
    for name in name_list:
        path = _resolve(name, shutil.which)
        if not path:
            continue
        real = _real(path)
        if path in skip or real in skip:
            continue
        if real in seen:
            continue
        seen.add(real)
        info = await probe_interpreter_async(path, venv_check=venv_check)
        if not info:
            continue
        version = parse_version(info.get("version"))
        if not version or version < req:
            continue
        found.append({
            "name": name,
            "path": path,
            "real": real,
            "version": version,
            "can_venv": bool(info.get("can_venv")),
        })
    return found


def is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "") or os.path.isdir("/data/data/com.termux")


def _sudo_prefix() -> list[str]:
    getuid = getattr(os, "geteuid", None)
    if getuid is not None and getuid() == 0:
        return []
    sudo = shutil.which("sudo")
    return [sudo, "-n"] if sudo else []


async def _emit(log: typing.Any, text: str) -> None:
    if not log:
        return
    try:
        result = log(text)
        if inspect.isawaitable(result):
            await result
    except Exception:
        pass


async def install_python_async(
    required: typing.Sequence[int],
    *,
    log: typing.Any = None,
) -> dict[str, typing.Any] | None:
    req = tuple(required)
    if is_termux():
        await _emit(log, "📥 Устанавливаю Python через pkg...")
        await _run(["pkg", "install", "-y", "python"], _APT_INSTALL_TIMEOUT)
    else:
        apt = shutil.which("apt-get") or shutil.which("apt")
        if not apt:
            return None
        sudo = _sudo_prefix()
        await _emit(log, "📥 Устанавливаю Python через apt...")
        await _run(sudo + [apt, "update", "-qq"], _APT_UPDATE_TIMEOUT)
        for offset in range(_CANDIDATE_SPAN, -1, -1):
            tag = f"{req[0]}.{req[1] + offset}"
            rc, _out, _err = await _run(
                sudo + [
                    apt, "install", "-y", "--no-install-recommends",
                    f"python{tag}", f"python{tag}-venv", f"python{tag}-dev",
                ],
                _APT_INSTALL_TIMEOUT,
            )
            if rc != 0:
                rc, _out, _err = await _run(
                    sudo + [
                        apt, "install", "-y", "--no-install-recommends",
                        f"python{tag}", f"python{tag}-venv",
                    ],
                    _APT_INSTALL_TIMEOUT,
                )
            if rc == 0 and shutil.which(f"python{tag}"):
                break
    found = await find_interpreters_async(req)
    return select_interpreter(found, req)


def venv_python(venv_dir: str) -> str:
    if os.name == "nt":
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def default_requirements(repo_path: str | None = None) -> str:
    root = _repo_root(repo_path)
    if is_termux():
        termux_req = os.path.join(root, "requirements-termux.txt")
        if os.path.exists(termux_req):
            return termux_req
    return os.path.join(root, "requirements.txt")


def requirement_name(line: str) -> str:
    text = str(line).split("#", 1)[0].split(";", 1)[0].strip()
    if not text:
        return ""
    if text.startswith("-"):
        return ""
    text = text.split("@", 1)[0].strip()
    text = text.split("[", 1)[0].strip()
    name = _REQ_NAME_SPLIT_RE.split(text, 1)[0].strip()
    return name.lower().replace("_", "-")


def is_optional_requirement(line: str) -> bool:
    return requirement_name(line) in _OPTIONAL_PACKAGES


def read_requirement_lines(req_file: str) -> list[str]:
    try:
        with open(req_file, encoding="utf-8", errors="replace") as fh:
            raw = fh.readlines()
    except OSError:
        return []
    lines: list[str] = []
    for item in raw:
        text = item.strip()
        if not text or text.startswith("#"):
            continue
        lines.append(text)
    return lines


def _pip_base(python: str) -> list[str]:
    return [
        python, "-m", "pip", "install",
        "--prefer-binary",
        "--no-warn-script-location",
        "--disable-pip-version-check",
    ]


async def pip_install_requirements_async(
    python: str,
    req_file: str,
    *,
    cwd: str | None = None,
    log: typing.Any = None,
    timeout: float = _PIP_TIMEOUT,
    one_timeout: float = _PIP_ONE_TIMEOUT,
) -> tuple[bool, list[str]]:
    rc, _out, err = await _run(_pip_base(python) + ["-r", req_file], timeout, cwd)
    if rc == 0:
        return True, []
    bulk_err = err.decode(errors="replace").strip() if err else ""
    await _emit(
        log,
        "⚠️ Массовая установка зависимостей не удалась — "
        "перехожу на поштучную установку...",
    )
    lines = read_requirement_lines(req_file)
    if not lines:
        return False, [bulk_err[:400] or f"pip rc={rc}"]
    errors: list[str] = []
    skipped: list[str] = []
    for line in lines:
        rc_one, _out_one, err_one = await _run(_pip_base(python) + [line], one_timeout, cwd)
        if rc_one == 0:
            continue
        text = err_one.decode(errors="replace").strip() if err_one else ""
        name = requirement_name(line) or line
        if is_optional_requirement(line):
            skipped.append(name)
            await _emit(
                log,
                f"⚠️ Пакет <code>{name}</code> недоступен для этого Python — пропускаю.",
            )
            continue
        errors.append(f"{name}: {text[:160] or f'pip rc={rc_one}'}")
    if errors:
        return False, errors
    if skipped:
        await _emit(log, "ℹ️ Пропущены необязательные пакеты: " + ", ".join(skipped))
    return True, skipped


async def rebuild_venv_async(
    repo_path: str,
    interpreter: str,
    *,
    venv_dir: str | None = None,
    requirements: str | None = None,
    log: typing.Any = None,
) -> str:
    root = _repo_root(repo_path)
    target = venv_dir or os.path.join(root, "venv")
    backup = target + ".old"
    shutil.rmtree(backup, ignore_errors=True)
    moved = False
    if os.path.isdir(target):
        try:
            os.rename(target, backup)
            moved = True
        except OSError:
            shutil.rmtree(target, ignore_errors=True)
    await _emit(log, f"🐍 Создаю окружение на {os.path.basename(interpreter)}...")
    rc, _out, err = await _run([interpreter, "-m", "venv", target], _VENV_BUILD_TIMEOUT)
    if rc != 0:
        shutil.rmtree(target, ignore_errors=True)
        if moved:
            try:
                os.rename(backup, target)
            except OSError:
                pass
        raise RuntimeError(
            f"venv на {interpreter} не создался: "
            + (err.decode(errors="replace").strip()[:300] or f"rc={rc}")
        )
    python = venv_python(target)
    await _run(
        [python, "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"],
        _PIP_TIMEOUT,
    )
    req_file = requirements or default_requirements(root)
    await _emit(log, "📦 Переустанавливаю зависимости на новом Python...")
    ok, errors = await pip_install_requirements_async(
        python, req_file, cwd=root, log=log,
    )
    if not ok:
        raise RuntimeError(
            "pip install на новом Python не удался: "
            + ("\n".join(errors).strip()[:400] or "неизвестная ошибка pip")
        )
    shutil.rmtree(backup, ignore_errors=True)
    return python


def missing_python_message(required: typing.Sequence[int]) -> str:
    need = format_version(required)
    have = format_version(current_version())
    return (
        f"Требуется Python {need}+, установлен {have}. "
        f"Подходящий интерпретатор не найден и автоустановка не удалась. "
        f"Установи Python {need} вручную "
        f"(Ubuntu/Debian: sudo apt install python{need} python{need}-venv, "
        f"Termux: pkg install python) и перезапусти установку."
    )


async def ensure_python_async(
    repo_path: str | None = None,
    *,
    required: typing.Sequence[int] | None = None,
    log: typing.Any = None,
    rebuild: bool = True,
) -> dict[str, typing.Any]:
    root = _repo_root(repo_path)
    req = tuple(required) if required is not None else read_requires_python(root)
    if version_ok(req):
        return {
            "ok": True,
            "changed": False,
            "python": sys.executable,
            "required": req,
            "version": current_version(),
        }
    await _emit(
        log,
        f"🐍 <b>Python {format_version(current_version())} устарел</b>, "
        f"нужен {format_version(req)}+ — ищу подходящий интерпретатор...",
    )
    found = await find_interpreters_async(req)
    best = select_interpreter(found, req)
    if best is None:
        best = await install_python_async(req, log=log)
    if best is None:
        raise RuntimeError(missing_python_message(req))
    if not rebuild:
        return {
            "ok": True,
            "changed": True,
            "python": best["path"],
            "interpreter": best["path"],
            "required": req,
            "version": best["version"],
        }
    python = await rebuild_venv_async(root, best["path"], log=log)
    return {
        "ok": True,
        "changed": True,
        "python": python,
        "interpreter": best["path"],
        "required": req,
        "version": best["version"],
    }


def ensure_startup_python(
    repo_path: str | None = None,
    *,
    argv: typing.Sequence[str] | None = None,
    reexec: bool = True,
    exit_on_fail: bool = True,
) -> tuple[int, int]:
    root = _repo_root(repo_path)
    req = read_requires_python(root)
    if version_ok(req):
        return req
    if reexec and not os.environ.get(REEXEC_ENV_FLAG):
        candidate = select_interpreter(
            find_interpreters(req, probe=probe_interpreter_sync),
            req,
        )
        if candidate:
            print(
                f"[Kitsune] Python {format_version(current_version())} устарел "
                f"(нужен {format_version(req)}+).\n"
                f"[Kitsune] Перезапуск через {candidate['path']} "
                f"({format_version(candidate['version'])})\n"
            )
            os.environ[REEXEC_ENV_FLAG] = "1"
            args = [candidate["path"], "-m", "kitsune"] + list(
                argv if argv is not None else sys.argv[1:]
            )
            os.execv(candidate["path"], args)
    print(f"[Kitsune] ОШИБКА: {missing_python_message(req)}", file=sys.stderr)
    if exit_on_fail:
        raise SystemExit(1)
    return req
