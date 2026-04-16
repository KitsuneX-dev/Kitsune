"""Smoke-тесты для kitsune/crypto.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import os as _os

# Патчим KEY_PATH чтобы не трогать реальный ~/.kitsune/kitsune.key
import tempfile, pathlib

@pytest.fixture(autouse=True)
def tmp_key(monkeypatch, tmp_path):
    import kitsune.crypto as crypto
    monkeypatch.setattr(crypto, "KEY_PATH", tmp_path / "test.key")
    yield

def _crypto():
    import kitsune.crypto as crypto
    return crypto

def test_encrypt_decrypt_roundtrip():
    c = _crypto()
    data = b"hello kitsune secret data"
    enc = c.encrypt(data)
    assert enc != data
    assert c.is_encrypted(enc)
    assert c.decrypt(enc) == data

def test_encrypt_has_magic():
    c = _crypto()
    enc = c.encrypt(b"test")
    assert enc.startswith(c.MAGIC)

def test_different_ciphertexts():
    """AES-GCM должен давать разный шифртекст при каждом вызове (случайный nonce)."""
    c = _crypto()
    data = b"same plaintext"
    enc1 = c.encrypt(data)
    enc2 = c.encrypt(data)
    # Если используется AES-GCM — шифртексты разные из-за nonce
    if b"AESGCM1:" in enc1:
        assert enc1 != enc2

def test_decrypt_wrong_data():
    c = _crypto()
    with pytest.raises(Exception):
        c.decrypt(b"not a valid backup")

def test_xor_backward_compat(monkeypatch, tmp_path):
    """XOR-бэкапы старых версий должны расшифровываться."""
    import kitsune.crypto as crypto
    monkeypatch.setattr(crypto, "KEY_PATH", tmp_path / "test.key")
    data = b"old xor backup data"
    key = crypto._load_or_create_key()
    enc = crypto.MAGIC + b"XOR1:" + crypto._xor_encrypt(data, key)
    assert crypto.decrypt(enc) == data

def test_key_created_on_disk(tmp_path, monkeypatch):
    import kitsune.crypto as crypto
    key_path = tmp_path / "new.key"
    monkeypatch.setattr(crypto, "KEY_PATH", key_path)
    crypto._load_or_create_key()
    assert key_path.exists()
