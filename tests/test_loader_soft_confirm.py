import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import textwrap

import pytest
from unittest.mock import MagicMock


VALID_MODULE = textwrap.dedent("""
    from kitsune.core.loader import KitsuneModule, command
    class SoftMod(KitsuneModule):
        name = "SoftMod"
        description = "Test module"
        version = "1.0"
        @command()
        async def hello_cmd(self, event):
            pass
""").strip()

FINDINGS = [
    "Sandbox escape attribute requires confirmation: __class__ (line 193)",
    "Sandbox escape attribute requires confirmation: __self__ (line 207)",
]


def _make_dispatcher():
    d = MagicMock()
    d._commands = {}
    d._prefix = "."
    d.register_command = MagicMock()
    d.unregister_command = MagicMock()
    d.register_watcher = MagicMock()
    d.unregister_watchers_for = MagicMock()
    return d


def _make_client():
    c = MagicMock()
    c.tg_id = 12345
    c.inline = None
    c._kitsune_dispatcher = None
    return c


def _make_db():
    db = MagicMock()
    db.get = MagicMock(return_value=None)
    return db


def _make_loader():
    from kitsune.core.loader import Loader
    return Loader(_make_client(), _make_db(), _make_dispatcher())


@pytest.fixture
def soft_findings(monkeypatch):
    import kitsune.core.loader as ld

    def fake_scan(source, filename="<module>"):
        return list(FINDINGS)

    monkeypatch.setattr(ld, "_scan_ast_with_cache", fake_scan)
    return FINDINGS


def test_scan_ast_with_cache_returns_soft_findings():
    from kitsune.core.loader import _ast_cache_clear, _scan_ast_with_cache
    _ast_cache_clear()
    src = "def f(x):\n    return x.__class__\n"
    findings = _scan_ast_with_cache(src, filename="soft.py")
    assert findings, "soft-находка по __class__ должна вернуться наружу"
    assert any("__class__" in f for f in findings)


def test_scan_ast_with_cache_clean_code_returns_empty():
    from kitsune.core.loader import _ast_cache_clear, _scan_ast_with_cache
    _ast_cache_clear()
    findings = _scan_ast_with_cache("x = 1 + 1\n", filename="clean.py")
    assert findings == []


def test_scan_ast_with_cache_findings_survive_cache_hit():
    from kitsune.core.loader import _ast_cache_clear, _scan_ast_with_cache
    _ast_cache_clear()
    src = "def g(y):\n    return y.__self__\n"
    first = _scan_ast_with_cache(src, filename="soft2.py")
    second = _scan_ast_with_cache(src, filename="soft2.py")
    assert first == second != []


def test_scan_ast_soft_findings_out_param():
    from kitsune.core.loader import _scan_ast
    out: list[str] = []
    _scan_ast("def f(x):\n    return x.__func__\n", "<t>", _out_findings=out)
    assert out and "__func__" in out[0]


@pytest.mark.asyncio
async def test_load_from_file_without_callback_ignores_findings(
    tmp_path, soft_findings
):
    mod_file = tmp_path / "softmod_a.py"
    mod_file.write_text(VALID_MODULE)
    loader = _make_loader()
    mod = await loader.load_from_file(mod_file)
    assert mod.name == "SoftMod"


@pytest.mark.asyncio
async def test_load_from_file_callback_declines_raises(tmp_path, soft_findings):
    from kitsune.core.loader import ModuleLoadError
    mod_file = tmp_path / "softmod_b.py"
    mod_file.write_text(VALID_MODULE)
    loader = _make_loader()
    seen: list[list[str]] = []

    async def on_soft(findings):
        seen.append(findings)
        return False

    with pytest.raises(ModuleLoadError, match="отменена"):
        await loader.load_from_file(mod_file, on_soft_findings=on_soft)
    assert seen == [FINDINGS]
    assert "softmod" not in loader._modules


@pytest.mark.asyncio
async def test_load_from_file_callback_accepts_loads(tmp_path, soft_findings):
    mod_file = tmp_path / "softmod_c.py"
    mod_file.write_text(VALID_MODULE)
    loader = _make_loader()
    called = []

    async def on_soft(findings):
        called.append(findings)
        return True

    mod = await loader.load_from_file(mod_file, on_soft_findings=on_soft)
    assert mod.name == "SoftMod"
    assert called == [FINDINGS]


@pytest.mark.asyncio
async def test_load_from_file_no_findings_callback_not_called(tmp_path, monkeypatch):
    import kitsune.core.loader as ld
    monkeypatch.setattr(ld, "_scan_ast_with_cache", lambda s, filename="<m>": [])
    mod_file = tmp_path / "softmod_d.py"
    mod_file.write_text(VALID_MODULE)
    loader = _make_loader()
    called = []

    async def on_soft(findings):
        called.append(findings)
        return False

    mod = await loader.load_from_file(mod_file, on_soft_findings=on_soft)
    assert mod.name == "SoftMod"
    assert called == []


class _FakeResp:
    def __init__(self, text):
        self._text = text

    def raise_for_status(self):
        pass

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, text):
        self._text = text

    def get(self, url, **kw):
        return _FakeResp(self._text)


@pytest.fixture
def fake_http(monkeypatch):
    import kitsune.net.http_pool as pool
    monkeypatch.setattr(pool, "get_shared_session", lambda: _FakeSession(VALID_MODULE))


@pytest.mark.asyncio
async def test_load_from_url_callback_declines_raises(
    tmp_path, monkeypatch, soft_findings, fake_http
):
    from kitsune.core.loader import ModuleLoadError
    import kitsune.paths as kpaths
    monkeypatch.setattr(kpaths, "data_dir", lambda: tmp_path)
    loader = _make_loader()

    async def on_soft(findings):
        return False

    with pytest.raises(ModuleLoadError, match="отменена"):
        await loader.load_from_url(
            "https://example.com/softmod_url.py", on_soft_findings=on_soft
        )


@pytest.mark.asyncio
async def test_load_from_url_callback_accepts_loads(
    tmp_path, monkeypatch, soft_findings, fake_http
):
    import kitsune.paths as kpaths
    monkeypatch.setattr(kpaths, "data_dir", lambda: tmp_path)
    loader = _make_loader()
    called = []

    async def on_soft(findings):
        called.append(findings)
        return True

    mod = await loader.load_from_url(
        "https://example.com/softmod_url2.py", on_soft_findings=on_soft
    )
    assert mod.name == "SoftMod"
    assert called == [FINDINGS]


@pytest.mark.asyncio
async def test_load_from_url_without_callback_ignores_findings(
    tmp_path, monkeypatch, soft_findings, fake_http
):
    import kitsune.paths as kpaths
    monkeypatch.setattr(kpaths, "data_dir", lambda: tmp_path)
    loader = _make_loader()
    mod = await loader.load_from_url("https://example.com/softmod_url3.py")
    assert mod.name == "SoftMod"


def _make_loader_mod():
    from kitsune.modules.loader_mod import LoaderMod as _LM  # type: ignore
    m = _LM.__new__(_LM)
    m.client = MagicMock()
    m.db = _make_db()
    return m


def test_parse_findings_extracts_attr_and_line():
    import kitsune.modules.loader_mod as lm
    cls = _find_loader_mod_class(lm)
    parsed = cls._parse_findings(FINDINGS)
    assert parsed == [("__class__", "193"), ("__self__", "207")]


def test_parse_findings_fallback_on_unknown_format():
    import kitsune.modules.loader_mod as lm
    cls = _find_loader_mod_class(lm)
    parsed = cls._parse_findings(["что-то совсем другое"])
    assert parsed == [("что-то совсем другое", "?")]


def _find_loader_mod_class(lm_module):
    from kitsune.core.loader import KitsuneModule
    for obj in vars(lm_module).values():
        if (
            isinstance(obj, type)
            and issubclass(obj, KitsuneModule)
            and obj is not KitsuneModule
            and hasattr(obj, "_confirm_soft_findings")
        ):
            return obj
    raise AssertionError("класс loader_mod не найден")


def _make_mod_instance():
    import kitsune.modules.loader_mod as lm
    cls = _find_loader_mod_class(lm)
    inst = cls.__new__(cls)
    inst.client = MagicMock()
    return inst


@pytest.mark.asyncio
async def test_confirm_soft_findings_no_inline_proceeds():
    inst = _make_mod_instance()
    inst.client._kitsune_inline = None
    assert await inst._confirm_soft_findings(FINDINGS, message=MagicMock()) is True


@pytest.mark.asyncio
async def test_confirm_soft_findings_yes_button():
    inst = _make_mod_instance()
    captured = {}

    class _Inline:
        _bot = MagicMock()

        async def form(self, text, message, markup):
            captured["text"] = text
            captured["markup"] = markup
            call = MagicMock()
            call.answer = _async_noop
            await markup[0][0]["callback"](call)

        async def edit(self, call, text):
            captured["edit"] = text

    async def _async_noop(*a, **kw):
        return None

    inst.client._kitsune_inline = _Inline()
    ok = await inst._confirm_soft_findings(FINDINGS, message=MagicMock())
    assert ok is True
    assert "Кицунэ насторожилась" in captured["text"]
    assert "строка 193" in captured["text"]
    assert "__class__" in captured["text"]
    assert len(captured["markup"][0]) == 2


@pytest.mark.asyncio
async def test_confirm_soft_findings_no_button():
    inst = _make_mod_instance()
    captured = {}

    async def _async_noop(*a, **kw):
        return None

    class _Inline:
        _bot = MagicMock()

        async def form(self, text, message, markup):
            call = MagicMock()
            call.answer = _async_noop
            await markup[0][1]["callback"](call)

        async def edit(self, call, text):
            captured["edit"] = text

    inst.client._kitsune_inline = _Inline()
    ok = await inst._confirm_soft_findings(FINDINGS, message=MagicMock())
    assert ok is False
    assert "не стала его устанавливать" in captured["edit"]


@pytest.mark.asyncio
async def test_confirm_soft_findings_timeout_declines(monkeypatch):
    import asyncio
    inst = _make_mod_instance()

    class _Inline:
        _bot = MagicMock()

        async def form(self, text, message, markup):
            return None

        async def edit(self, call, text):
            return None

    inst.client._kitsune_inline = _Inline()
    real_wait_for = asyncio.wait_for

    async def fast_wait_for(aw, timeout):
        return await real_wait_for(aw, 0.05)

    monkeypatch.setattr(asyncio, "wait_for", fast_wait_for)
    assert await inst._confirm_soft_findings(FINDINGS, message=MagicMock()) is False
