
from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_manager():
    from kitsune.inline.core import InlineManager

    client = MagicMock()
    client.tg_id = 777
    client.delete_messages = AsyncMock()
    return InlineManager(client, MagicMock(), "123:token")


def _reset_aiogram_warnings() -> None:
    from kitsune.inline.core import common

    common.reset_optional_dep_warnings()


def _aiogram_warnings(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.WARNING and "aiogram" in r.getMessage()
    ]


def _lowpower_warnings(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.WARNING
        and r.name == "kitsune.low_power"
    ]


@pytest.fixture()
def clean_aiogram_warnings():
    _reset_aiogram_warnings()
    yield
    _reset_aiogram_warnings()


@pytest.fixture()
def clean_lowpower_warnings():
    from kitsune import low_power

    low_power.reset_optional_dep_warnings()
    low_power.reset_cache()
    yield
    low_power.reset_optional_dep_warnings()
    low_power.reset_cache()


def test_common_exposes_warn_helpers():
    from kitsune.inline.core import common

    assert callable(common.warn_no_aiogram_once)
    assert callable(common.reset_optional_dep_warnings)


def test_common_warn_helper_is_idempotent_per_feature(caplog, clean_aiogram_warnings):
    from kitsune.inline.core import common

    with caplog.at_level(logging.WARNING, logger="kitsune.inline.core"):
        common.warn_no_aiogram_once("featureA", "A disabled")
        common.warn_no_aiogram_once("featureA", "A disabled")
        common.warn_no_aiogram_once("featureB", "B disabled")

    msgs = _aiogram_warnings(caplog)
    assert len(msgs) == 2
    assert sum("featureA" in m for m in msgs) == 1
    assert sum("featureB" in m for m in msgs) == 1
    assert all("pip install aiogram" in m for m in msgs)


def test_generate_markup_warns_when_aiogram_missing(
    caplog, monkeypatch, clean_aiogram_warnings
):
    from kitsune.inline.core import markup

    monkeypatch.setattr(markup, "AIOGRAM_AVAILABLE", False)
    im = _make_manager()

    with caplog.at_level(logging.WARNING, logger="kitsune.inline.core"):
        result = im.generate_markup([{"text": "x", "data": "y"}])

    assert result is None, "деградация должна оставаться мягкой (None, без исключений)"
    msgs = _aiogram_warnings(caplog)
    assert msgs, "generate_markup() не должен молча возвращать None"
    assert any("aiogram" in m for m in msgs)
    assert any("generate_markup" in m for m in msgs)


def test_generate_markup_warns_exactly_once(
    caplog, monkeypatch, clean_aiogram_warnings
):
    from kitsune.inline.core import markup

    monkeypatch.setattr(markup, "AIOGRAM_AVAILABLE", False)
    im = _make_manager()

    with caplog.at_level(logging.WARNING, logger="kitsune.inline.core"):
        for _ in range(5):
            assert im.generate_markup([{"text": "x", "data": "y"}]) is None

    msgs = [m for m in _aiogram_warnings(caplog) if "generate_markup" in m]
    assert len(msgs) == 1, f"ожидалось ровно одно предупреждение, получено: {msgs}"


def test_generate_markup_does_not_warn_when_aiogram_available(
    caplog, clean_aiogram_warnings
):
    from kitsune.inline.core import markup

    if not markup.AIOGRAM_AVAILABLE:
        pytest.skip("aiogram не установлен — контрольный тест неприменим")

    im = _make_manager()
    with caplog.at_level(logging.WARNING, logger="kitsune.inline.core"):
        result = im.generate_markup([{"text": "x", "data": "y"}])

    assert result is not None
    assert _aiogram_warnings(caplog) == [], "не должно быть лишнего шума в логе"


def test_inline_manager_start_warns_when_aiogram_missing(
    caplog, monkeypatch, clean_aiogram_warnings
):
    from kitsune.inline import core as core_pkg

    monkeypatch.setattr(core_pkg, "AIOGRAM_AVAILABLE", False)
    im = _make_manager()

    with caplog.at_level(logging.WARNING, logger="kitsune.inline.core"):
        asyncio.run(im.start())
        asyncio.run(im.start())

    msgs = [m for m in _aiogram_warnings(caplog) if "start" in m]
    assert len(msgs) == 1, f"ожидалось ровно одно предупреждение, получено: {msgs}"
    assert im._started is False, "мягкая деградация: менеджер просто не стартует"


def test_dispatch_edit_warns_when_aiogram_missing(
    caplog, monkeypatch, clean_aiogram_warnings
):
    from kitsune.inline.core import dispatch

    monkeypatch.setattr(dispatch, "AIOGRAM_AVAILABLE", False)
    im = _make_manager()

    with caplog.at_level(logging.WARNING, logger="kitsune.inline.core"):
        asyncio.run(im.edit(MagicMock(inline_message_id="iid"), "text"))
        asyncio.run(im.edit(MagicMock(inline_message_id="iid"), "text"))

    msgs = [m for m in _aiogram_warnings(caplog) if "edit" in m]
    assert len(msgs) == 1, f"ожидалось ровно одно предупреждение, получено: {msgs}"


def test_each_degradation_point_warns_separately(
    caplog, monkeypatch, clean_aiogram_warnings
):
    from kitsune.inline import core as core_pkg
    from kitsune.inline.core import dispatch, markup

    monkeypatch.setattr(markup, "AIOGRAM_AVAILABLE", False)
    monkeypatch.setattr(dispatch, "AIOGRAM_AVAILABLE", False)
    monkeypatch.setattr(core_pkg, "AIOGRAM_AVAILABLE", False)
    im = _make_manager()

    with caplog.at_level(logging.WARNING, logger="kitsune.inline.core"):
        im.generate_markup([{"text": "x", "data": "y"}])
        asyncio.run(im.start())
        asyncio.run(im.edit(MagicMock(inline_message_id="iid"), "text"))

    msgs = _aiogram_warnings(caplog)
    assert len(msgs) == 3, msgs
    assert any("generate_markup" in m for m in msgs)
    assert any("start" in m for m in msgs)
    assert any("edit" in m for m in msgs)


def _write_config(tmp_path, text: str = "low_power = true\n"):
    cfg = tmp_path / "config.toml"
    cfg.write_text(text, encoding="utf-8")
    return cfg


def _patch_config_path(monkeypatch, path):
    import kitsune.paths as paths

    monkeypatch.setattr(paths, "effective_config_path", lambda: path)


def test_load_config_warns_when_toml_missing(
    caplog, monkeypatch, tmp_path, clean_lowpower_warnings
):
    from kitsune import low_power

    cfg = _write_config(tmp_path)
    _patch_config_path(monkeypatch, cfg)
    monkeypatch.setitem(sys.modules, "toml", None)

    with caplog.at_level(logging.WARNING, logger="kitsune.low_power"):
        data = low_power.load_config()

    assert data == {}, "деградация должна оставаться мягкой (пустой конфиг)"
    msgs = _lowpower_warnings(caplog)
    assert msgs, "load_config() не должен молча возвращать {}"
    assert any("toml" in m for m in msgs)


def test_load_config_warns_about_missing_toml_exactly_once(
    caplog, monkeypatch, tmp_path, clean_lowpower_warnings
):
    from kitsune import low_power

    cfg = _write_config(tmp_path)
    _patch_config_path(monkeypatch, cfg)
    monkeypatch.setitem(sys.modules, "toml", None)

    with caplog.at_level(logging.WARNING, logger="kitsune.low_power"):
        for _ in range(4):
            assert low_power.load_config() == {}

    msgs = [m for m in _lowpower_warnings(caplog) if "toml" in m and "install" in m]
    assert len(msgs) == 1, f"ожидалось ровно одно предупреждение, получено: {msgs}"


def test_load_config_does_not_warn_when_toml_available(
    caplog, monkeypatch, tmp_path, clean_lowpower_warnings
):
    pytest.importorskip("toml")
    from kitsune import low_power

    cfg = _write_config(tmp_path)
    _patch_config_path(monkeypatch, cfg)

    with caplog.at_level(logging.WARNING, logger="kitsune.low_power"):
        data = low_power.load_config()
        data_again = low_power.load_config()

    assert data.get("low_power") is True
    assert data_again.get("low_power") is True
    assert _lowpower_warnings(caplog) == [], "не должно быть лишнего шума в логе"


def test_load_config_warns_when_config_path_raises(
    caplog, monkeypatch, clean_lowpower_warnings
):
    import kitsune.paths as paths
    from kitsune import low_power

    def _boom():
        raise RuntimeError("no config path")

    monkeypatch.setattr(paths, "effective_config_path", _boom)

    with caplog.at_level(logging.WARNING, logger="kitsune.low_power"):
        for _ in range(3):
            assert low_power.load_config() == {}

    msgs = _lowpower_warnings(caplog)
    assert len(msgs) == 1, f"ожидалось ровно одно предупреждение, получено: {msgs}"
    assert "config.toml" in msgs[0]


def test_load_config_warns_when_file_missing(
    caplog, monkeypatch, tmp_path, clean_lowpower_warnings
):
    from kitsune import low_power

    _patch_config_path(monkeypatch, tmp_path / "nope" / "config.toml")

    with caplog.at_level(logging.WARNING, logger="kitsune.low_power"):
        for _ in range(3):
            assert low_power.load_config() == {}

    msgs = _lowpower_warnings(caplog)
    assert len(msgs) == 1, f"ожидалось ровно одно предупреждение, получено: {msgs}"


def test_load_config_warns_when_content_is_broken(
    caplog, monkeypatch, tmp_path, clean_lowpower_warnings
):
    pytest.importorskip("toml")
    from kitsune import low_power

    cfg = _write_config(tmp_path, "this is = = not toml [[[\n")
    _patch_config_path(monkeypatch, cfg)

    with caplog.at_level(logging.WARNING, logger="kitsune.low_power"):
        for _ in range(3):
            assert low_power.load_config() == {}

    msgs = _lowpower_warnings(caplog)
    assert len(msgs) == 1, f"ожидалось ровно одно предупреждение, получено: {msgs}"
    assert "parse" in msgs[0] or "config.toml" in msgs[0]


def test_unreadable_config_and_missing_toml_warn_separately(
    caplog, monkeypatch, tmp_path, clean_lowpower_warnings
):
    from kitsune import low_power

    _patch_config_path(monkeypatch, tmp_path / "absent.toml")
    with caplog.at_level(logging.WARNING, logger="kitsune.low_power"):
        low_power.load_config()

        cfg = _write_config(tmp_path)
        _patch_config_path(monkeypatch, cfg)
        monkeypatch.setitem(sys.modules, "toml", None)
        low_power.load_config()

    msgs = _lowpower_warnings(caplog)
    assert len(msgs) == 2, msgs


def test_low_power_enabled_still_works_without_toml(
    monkeypatch, tmp_path, clean_lowpower_warnings
):
    from kitsune import low_power

    _patch_config_path(monkeypatch, tmp_path / "absent.toml")
    monkeypatch.setitem(sys.modules, "toml", None)
    monkeypatch.setenv("KITSUNE_LOW_POWER", "1")

    assert low_power.enabled() is True


import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

_INSTALLERS = ("install.sh", "termux.sh")

_ENV_NAME = "KITSUNE_LOW_POWER"


def _installer_text(name: str) -> str:
    path = _REPO_ROOT / name
    assert path.is_file(), f"{name} не найден в корне репозитория"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("script", _INSTALLERS)
def test_installer_mentions_low_power_env(script):
    text = _installer_text(script)
    assert _ENV_NAME in text, f"{script}: {_ENV_NAME} вообще не упоминается"


@pytest.mark.parametrize("script", _INSTALLERS)
def test_installer_exports_low_power_env(script):
    text = _installer_text(script)
    assert re.search(rf"^\s*export\s+{_ENV_NAME}\b", text, re.M), (
        f"{script}: {_ENV_NAME} не экспортируется в сессию установщика"
    )


@pytest.mark.parametrize("script", _INSTALLERS)
def test_installer_persists_low_power_to_rc_files(script):
    text = _installer_text(script)
    assert ".bashrc" in text, f"{script}: нет записи в ~/.bashrc"
    assert ".profile" in text, f"{script}: нет записи в ~/.profile"
    assert "persist_low_power_rc" in text, (
        f"{script}: нет хелпера, сохраняющего {_ENV_NAME} в rc-файлы"
    )
    for rc in (".bashrc", ".profile"):
        assert re.search(
            rf'persist_low_power_rc\s+"\$_RC"|\$HOME/{re.escape(rc)}', text
        ), f"{script}: {rc} не передаётся в persist_low_power_rc"


@pytest.mark.parametrize("script", _INSTALLERS)
def test_installer_updates_rc_line_instead_of_duplicating(script):
    text = _installer_text(script)
    assert re.search(rf"sed -i .*{_ENV_NAME}", text), (
        f"{script}: существующая строка {_ENV_NAME} должна обновляться через sed"
    )


@pytest.mark.parametrize("script", _INSTALLERS)
def test_installer_respects_preset_env_value(script):
    text = _installer_text(script)
    assert re.search(rf'\[\[\s*-n\s+"\$\{{{_ENV_NAME}:-\}}"\s*\]\]', text), (
        f"{script}: заданное в окружении значение {_ENV_NAME} должно уважаться"
    )


@pytest.mark.parametrize("script", _INSTALLERS)
def test_installer_writes_config_toml_only_when_truthy(script):
    text = _installer_text(script)
    assert "low_power = true" in text, f"{script}: нет дублирования в config.toml"
    idx_case = text.index(f'case "$(echo "${_ENV_NAME}"')
    idx_cfg = text.index("low_power = true")
    assert idx_case < idx_cfg, (
        f"{script}: запись low_power в config.toml должна быть под проверкой truthy"
    )


@pytest.mark.parametrize("script", _INSTALLERS)
def test_installer_truthy_literals_match_low_power_module(script):
    from kitsune import low_power

    text = _installer_text(script)
    match = re.search(
        rf'case "\$\(echo "\${_ENV_NAME}" \| tr .*?\)" in\s*\n\s*([^)]+)\)',
        text,
    )
    assert match, f"{script}: не найден case-блок сверки truthy-значений"
    literals = [lit.strip() for lit in match.group(1).split("|") if lit.strip()]
    assert literals, f"{script}: пустой список truthy-литералов"
    assert set(literals) <= set(low_power._TRUTHY), (
        f"{script}: литералы {literals} расходятся с "
        f"kitsune.low_power._TRUTHY={sorted(low_power._TRUTHY)}"
    )


@pytest.mark.parametrize("script", _INSTALLERS)
def test_installer_true_value_is_truthy_for_low_power_module(script):
    from kitsune import low_power

    text = _installer_text(script)
    match = re.search(r'LOW_POWER_TRUE_VALUE="([^"]+)"', text)
    assert match, f"{script}: LOW_POWER_TRUE_VALUE не задан"
    value = match.group(1)
    assert value in low_power._TRUTHY, (
        f"{script}: LOW_POWER_TRUE_VALUE={value!r} не входит в _TRUTHY"
    )
    assert low_power._as_bool(value) is True

    false_match = re.search(r'LOW_POWER_FALSE_VALUE="([^"]+)"', text)
    assert false_match, f"{script}: LOW_POWER_FALSE_VALUE не задан"
    false_value = false_match.group(1)
    assert false_value not in low_power._TRUTHY
    assert low_power._as_bool(false_value) is False


@pytest.mark.parametrize("script", _INSTALLERS)
def test_installer_prints_final_low_power_value(script):
    text = _installer_text(script)
    tail = text[-1500:]
    assert _ENV_NAME in tail, (
        f"{script}: итоговое значение {_ENV_NAME} не выводится в финальном сообщении"
    )


@pytest.mark.parametrize("script", _INSTALLERS)
def test_installer_has_valid_bash_syntax(script):
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash недоступен")
    proc = subprocess.run(
        [bash, "-n", str(_REPO_ROOT / script)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"{script}: bash -n упал:\n{proc.stderr}"


def test_install_sh_detects_weak_hardware():
    text = _installer_text("install.sh")
    assert "detect_weak_hardware" in text
    assert "/proc/meminfo" in text, "install.sh: нет проверки RAM через /proc/meminfo"
    assert "nproc" in text, "install.sh: нет проверки числа ядер через nproc"
    assert "2097152" in text, "install.sh: порог 2 GB RAM (в кБ) не задан"
    assert "IS_TERMUX" in text and "IS_USERLAND" in text


def test_install_sh_interactive_choice_is_tty_gated():
    text = _installer_text("install.sh")
    assert re.search(r"\[\[\s*-t\s+0\s*\]\]", text), (
        "install.sh: интерактивный выбор должен быть только при TTY"
    )
    assert "read -r" in text


def test_termux_sh_enables_low_power_by_default():
    text = _installer_text("termux.sh")
    idx = text.index('KITSUNE_LOW_POWER="$LOW_POWER_TRUE_VALUE"')
    assert idx > 0
    assert "по умолчанию для Termux" in text
    assert "-t 0" not in text, (
        "termux.sh: интерактивный выбор не нужен, включаем по умолчанию"
    )


def test_install_sh_propagates_low_power_to_autostart_targets():
    text = _installer_text("install.sh")

    profile_block = text[text.index('cat > "$HOME/.bash_profile"'):]
    profile_block = profile_block[:profile_block.index("\nPROFILE\n")]
    assert _ENV_NAME in profile_block, "install.sh: нет экспорта в ~/.bash_profile"

    ul_block = text[text.index('cat > "$HOME/start_kitsune.sh"'):]
    ul_block = ul_block[:ul_block.index("\nULSCRIPT\n")]
    assert _ENV_NAME in ul_block, "install.sh: нет экспорта в start_kitsune.sh"

    service_block = text[text.index("[Unit]"):]
    service_block = service_block[:service_block.index("\nSERVICE\n")]
    assert f"Environment={_ENV_NAME}=" in service_block, (
        "install.sh: systemd unit без Environment=KITSUNE_LOW_POWER"
    )


def test_termux_sh_propagates_low_power_to_autostart():
    text = _installer_text("termux.sh")
    block = text[text.index('cat > "$HOME/.bash_profile"'):]
    block = block[:block.index("\nPROFILE\n")]
    assert f'export {_ENV_NAME}="$KITSUNE_LOW_POWER"' in block, (
        "termux.sh: ~/.bash_profile должен экспортировать актуальное значение"
    )
