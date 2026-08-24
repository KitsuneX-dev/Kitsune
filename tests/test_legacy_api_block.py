from __future__ import annotations

import pathlib

import pytest

from kitsune.core.loader import LegacyApiError, _detect_legacy_or_raise
from kitsune.core.loader.ast_scanner import detect_legacy_api
from kitsune.core.loader.dependency_resolver import _extract_missing_package

LEGACY_SOURCES = [
    "from .. import loader, utils\nclass X(loader.Module):\n    pass",
    "from ..loader import Module\n",
    "from hikka import loader\n",
    "from herokutl.types import Message\n",
    "import hikkatl\n",
    "import loader\n",
    "@loader.command()\nasync def c(self, m): pass\n",
    "@loader.tds\nclass X:\n    pass\n",
    "@loader.unrestricted\nasync def c(self, m): pass\n",
    "@loader.watcher()\nasync def w(self, m): pass\n",
    "@loader.loop(interval=5)\nasync def l(self): pass\n",
    "@loader.raw_handler(None)\nasync def r(self, u): pass\n",
]

LEGIT_SOURCES = [
    "from kitsune.core.loader import command\n@command()\nasync def foo(): pass",

    "from ..utils import chunks\n",
    "from .. import utils\n",
    "from ...utils.text import escape\n",

    "from . import loader\n",
    "from .loader import Loader\n",
    "from ..core.loader import KitsuneModule, command\n",
    "",
]


@pytest.mark.parametrize("source", LEGACY_SOURCES)
def test_legacy_detected(source: str) -> None:
    assert detect_legacy_api(source) is not None


@pytest.mark.parametrize("source", LEGIT_SOURCES)
def test_legit_not_flagged(source: str) -> None:
    assert detect_legacy_api(source) is None


def test_broken_syntax_returns_none() -> None:
    assert detect_legacy_api("def (:\n") is None


def test_no_false_positives_on_project_files() -> None:
    root = pathlib.Path(__file__).resolve().parent.parent / "kitsune"
    offenders = [
        (str(p), detect_legacy_api(p.read_text(encoding="utf-8", errors="replace")))
        for p in root.rglob("*.py")
        if "__pycache__" not in str(p)
    ]
    assert [item for item in offenders if item[1]] == []


def test_detect_legacy_or_raise_raises() -> None:
    with pytest.raises(LegacyApiError) as excinfo:
        _detect_legacy_or_raise("from .. import loader\n", origin="test.py")
    assert "Kitsune" in str(excinfo.value)


def test_detect_legacy_or_raise_passes_legit() -> None:
    _detect_legacy_or_raise("from ..utils import chunks\n", origin="ok.py")


@pytest.mark.parametrize(
    "name", ["kitsune", "loader", "utils", "hikka", "hikkatl", "heroku", "herokutl"]
)
def test_pip_guard_refuses_internal_packages(name: str) -> None:
    exc = ImportError(f"cannot import name 'x' from '{name}'")
    exc.name = name
    assert _extract_missing_package(exc) is None


def test_pip_guard_allows_real_packages() -> None:
    exc = ImportError("No module named 'requests'")
    exc.name = "requests"
    assert _extract_missing_package(exc) == "requests"


def test_pip_guard_refuses_internal_from_message_only() -> None:
    exc = ImportError("No module named 'hikkatl.tl'")
    assert _extract_missing_package(exc) is None
