
from __future__ import annotations

import logging
import os
import ssl
import sys
import warnings

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mod():
    from kitsune.net import ssl_ctx

    return ssl_ctx


def test_default_context_requires_certificate():
    ctx = _mod().make_ssl_ctx()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_default_context_has_loaded_ca_certificates():
    ctx = _mod().make_ssl_ctx()
    assert len(ctx.get_ca_certs()) > 0


def test_default_context_survives_missing_certifi(monkeypatch):
    monkeypatch.setitem(sys.modules, "certifi", None)
    ctx = _mod().make_ssl_ctx()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_verify_true_explicit_matches_default():
    ctx = _mod().make_ssl_ctx(verify=True)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_verify_false_disables_verification():
    ctx = _mod().make_ssl_ctx(verify=False)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_verify_false_logs_warning(caplog):
    mod = _mod()
    with caplog.at_level(logging.WARNING, logger=mod.__name__):
        mod.make_ssl_ctx(verify=False)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "SSL" in text and ("ОТКЛЮЧЕНА" in text or "insecure" in text)


def test_insecure_call_does_not_leak_into_next_default_call():
    mod = _mod()
    insecure = mod.make_ssl_ctx(verify=False)
    secure = mod.make_ssl_ctx()
    assert insecure is not secure
    assert insecure.verify_mode == ssl.CERT_NONE
    assert secure.verify_mode == ssl.CERT_REQUIRED
    assert mod.make_ssl_ctx() is not mod.make_ssl_ctx()


def test_deprecated_no_verify_wrapper_warns_and_is_insecure():
    mod = _mod()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ctx = mod.make_ssl_ctx_no_verify()
    assert ctx.verify_mode == ssl.CERT_NONE
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_aiohttp_connector_built_with_verifying_context(monkeypatch):
    aiohttp = pytest.importorskip("aiohttp")
    captured = {}

    class _Spy:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(aiohttp, "TCPConnector", _Spy)
    _mod().get_aiohttp_connector()

    ctx = captured.get("ssl")
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
