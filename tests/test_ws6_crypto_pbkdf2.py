
from __future__ import annotations

import base64
import hashlib
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def isolate_key(monkeypatch, tmp_path):
    import kitsune.crypto as crypto

    monkeypatch.setattr(crypto, "KEY_PATH", tmp_path / "test.key")
    monkeypatch.setattr(crypto, "SALT_PATH", tmp_path / "test.key.salt")
    monkeypatch.delenv("KITSUNE_KEY", raising=False)
    yield


def _crypto():
    import kitsune.crypto as crypto

    return crypto


def _raw_key(c) -> bytes:
    return base64.urlsafe_b64decode(c._load_or_create_key() + b"==")


def test_new_backup_is_encrypted_with_pbkdf2_key_not_sha256(monkeypatch):
    c = _crypto()
    if not c._AES_GCM_AVAILABLE:
        pytest.skip("AES-GCM not available")
    monkeypatch.setenv("KITSUNE_KEY", "cGJrZGYyLXZzLXNoYTI1Ni1jaGVjay1rZXktMTIzNDU")

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    data = b"pbkdf2 must be the derivation " * 10
    enc = c.encrypt(data)
    assert enc.startswith(c.MAGIC + b"AESGCM2:")

    body = enc[len(c.MAGIC) + 8:]
    nonce_len = struct.unpack(">I", body[:4])[0]
    nonce = body[4:4 + nonce_len]
    ct = body[4 + nonce_len:]

    raw = _raw_key(c)
    pbkdf2_key = c._derive_aes_key_pbkdf2(raw)
    legacy_key = hashlib.sha256(raw).digest()
    assert pbkdf2_key != legacy_key

    assert AESGCM(pbkdf2_key).decrypt(nonce, ct, None) == data
    with pytest.raises(Exception):
        AESGCM(legacy_key).decrypt(nonce, ct, None)


def test_salt_actually_participates_in_key_derivation(monkeypatch, tmp_path):
    c = _crypto()
    monkeypatch.setenv("KITSUNE_KEY", "c2FsdC1tYXR0ZXJzLWNoZWNrLWtleS12YWx1ZS0xMjM")
    raw = _raw_key(c)

    monkeypatch.setattr(c, "SALT_PATH", tmp_path / "salt_a")
    key_a = c._derive_aes_key_pbkdf2(raw)

    monkeypatch.setattr(c, "SALT_PATH", tmp_path / "salt_b")
    key_b = c._derive_aes_key_pbkdf2(raw)

    assert (tmp_path / "salt_a").read_bytes() != (tmp_path / "salt_b").read_bytes()
    assert key_a != key_b
    assert len(key_a) == 32


def test_chacha2_marker_used_when_aes_gcm_unavailable(monkeypatch):
    c = _crypto()
    if not c._CHACHA_AVAILABLE:
        pytest.skip("ChaCha20-Poly1305 not available")
    monkeypatch.setenv("KITSUNE_KEY", "Y2hhY2hhMi1tYXJrZXItY2hlY2sta2V5LTEyMzQ1Njc")
    monkeypatch.setattr(c, "_AES_GCM_AVAILABLE", False)

    data = b"chacha2 payload " * 20
    enc = c.encrypt(data)
    assert enc.startswith(c.MAGIC + b"CHACHA2:")
    assert c.format_version(enc) == 2
    assert c.decrypt(enc) == data


def test_legacy_chacha1_backup_still_decrypts_and_migrates(monkeypatch):
    c = _crypto()
    if not c._CHACHA_AVAILABLE:
        pytest.skip("ChaCha20-Poly1305 not available")
    monkeypatch.setenv("KITSUNE_KEY", "Y2hhY2hhMS1sZWdhY3ktY2hlY2sta2V5LTEyMzQ1Njc4")

    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    data = b"legacy chacha payload " * 15
    legacy_k = hashlib.sha256(_raw_key(c)).digest()[:32].ljust(32, b"\0")
    nonce = os.urandom(12)
    body = nonce + ChaCha20Poly1305(legacy_k).encrypt(nonce, data, None)
    legacy = c.MAGIC + b"CHACHA1:" + body

    assert c.format_version(legacy) == 1
    assert c.decrypt(legacy) == data

    plain, migrated = c.decrypt_and_reencrypt(legacy)
    assert plain == data
    assert migrated is not None
    assert c.format_version(migrated) == 2
    assert c.decrypt(migrated) == data


def test_format_version_zero_for_non_backup():
    c = _crypto()
    assert c.format_version(b"") == 0
    assert c.format_version(b"plain sqlite file contents") == 0
    assert c.format_version(b"AESGCM2:whatever") == 0


def test_decrypt_and_reencrypt_leaves_v2_untouched(monkeypatch):
    c = _crypto()
    monkeypatch.setenv("KITSUNE_KEY", "bm8tbWlncmF0aW9uLW5lZWRlZC1rZXktdmFsdWUxMg")
    data = b"already v2 payload " * 12
    enc = c.encrypt(data)
    assert c.format_version(enc) == 2

    plain, migrated = c.decrypt_and_reencrypt(enc)
    assert plain == data
    assert migrated is None
