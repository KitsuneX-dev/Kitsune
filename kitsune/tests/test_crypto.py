import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import base64
import hashlib
import hmac
import struct
import pytest


@pytest.fixture(autouse=True)
def isolate_key(monkeypatch, tmp_path):
    import kitsune.crypto as crypto
    monkeypatch.setattr(crypto, "KEY_PATH", tmp_path / "test.key")
    monkeypatch.delenv("KITSUNE_KEY", raising=False)
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
def test_is_encrypted_true():
    c = _crypto()
    assert c.is_encrypted(c.encrypt(b"x")) is True
def test_is_encrypted_false():
    c = _crypto()
    assert c.is_encrypted(b"plain") is False
    assert c.is_encrypted(b"") is False
def test_key_path_returns_path():
    c = _crypto()
    p = c.key_path()
    assert p is not None
    assert hasattr(p, "exists")
def test_aes_gcm_used_when_available():
    c = _crypto()
    if not c._AES_GCM_AVAILABLE:
        pytest.skip("AES-GCM not available")
    enc = c.encrypt(b"some payload")
    assert b"AESGCM1:" in enc[:32]
def test_aes_gcm_random_nonce_unique_ciphertexts():
    c = _crypto()
    if not c._AES_GCM_AVAILABLE:
        pytest.skip("AES-GCM not available")
    data = b"identical plaintext"
    enc1 = c.encrypt(data)
    enc2 = c.encrypt(data)
    assert enc1 != enc2
    assert c.decrypt(enc1) == data
    assert c.decrypt(enc2) == data
def test_aes_gcm_nonce_length_is_12():
    c = _crypto()
    if not c._AES_GCM_AVAILABLE:
        pytest.skip("AES-GCM not available")
    enc = c.encrypt(b"payload")
    payload = enc[len(c.MAGIC):]
    assert payload.startswith(b"AESGCM1:")
    body = payload[len(b"AESGCM1:"):]
    nonce_len = struct.unpack(">I", body[:4])[0]
    assert nonce_len == 12
def test_aes_gcm_tampered_ciphertext_fails():
    c = _crypto()
    if not c._AES_GCM_AVAILABLE:
        pytest.skip("AES-GCM not available")
    enc = bytearray(c.encrypt(b"genuine"))
    enc[-1] ^= 0xFF
    with pytest.raises(Exception):
        c.decrypt(bytes(enc))
def test_aes_gcm_tampered_nonce_fails():
    c = _crypto()
    if not c._AES_GCM_AVAILABLE:
        pytest.skip("AES-GCM not available")
    enc = bytearray(c.encrypt(b"genuine"))
    pos = len(c.MAGIC) + len(b"AESGCM1:") + 4
    enc[pos] ^= 0xAA
    with pytest.raises(Exception):
        c.decrypt(bytes(enc))
def test_aes_gcm_empty_data():
    c = _crypto()
    if not c._AES_GCM_AVAILABLE:
        pytest.skip("AES-GCM not available")
    enc = c.encrypt(b"")
    assert c.decrypt(enc) == b""
def test_aes_gcm_large_data():
    c = _crypto()
    if not c._AES_GCM_AVAILABLE:
        pytest.skip("AES-GCM not available")
    big = os.urandom(1024 * 256)           
    enc = c.encrypt(big)
    assert c.decrypt(enc) == big
def test_aes_gcm_binary_data_with_zero_bytes():
    c = _crypto()
    data = b"\x00\x01\x02\x00\xff\x00binary\x00data\x00"
    enc = c.encrypt(data)
    assert c.decrypt(enc) == data
def test_aes_gcm_unicode_payload():
    c = _crypto()
    data = "🦊 кицунэ 狐 🌸".encode("utf-8")
    enc = c.encrypt(data)
    assert c.decrypt(enc) == data
def test_aes_gcm_internal_helpers():
    c = _crypto()
    if not c._AES_GCM_AVAILABLE:
        pytest.skip("AES-GCM not available")
    key = base64.urlsafe_b64encode(os.urandom(32))
    enc = c._aes_gcm_encrypt(b"hello", key)
    assert c._aes_gcm_decrypt(enc, key) == b"hello"
def test_aes_gcm_wrong_key_fails():
    c = _crypto()
    if not c._AES_GCM_AVAILABLE:
        pytest.skip("AES-GCM not available")
    key1 = base64.urlsafe_b64encode(os.urandom(32))
    key2 = base64.urlsafe_b64encode(os.urandom(32))
    enc = c._aes_gcm_encrypt(b"top secret", key1)
    with pytest.raises(Exception):
        c._aes_gcm_decrypt(enc, key2)
def test_decrypt_no_magic_raises():
    c = _crypto()
    with pytest.raises(ValueError):
        c.decrypt(b"not a valid backup")
def test_decrypt_empty_raises():
    c = _crypto()
    with pytest.raises(ValueError):
        c.decrypt(b"")
def test_decrypt_truncated_data_raises():
    c = _crypto()
    enc = c.encrypt(b"valid")
    truncated = enc[:len(c.MAGIC) + 4]
    with pytest.raises(Exception):
        c.decrypt(truncated)
def test_chacha_backend():
    c = _crypto()
    data = b"chacha backup data"
    key = c._load_or_create_key()
    enc = c.MAGIC + b"CHACHA1:" + c._chacha_encrypt(data, key)
    assert c.decrypt(enc) == data
def test_chacha_tag_authentication():
    c = _crypto()
    key = c._load_or_create_key()
    enc = c.MAGIC + b"CHACHA1:" + c._chacha_encrypt(b"data", key)
    bad = bytearray(enc)
    bad[-1] ^= 0x01
    with pytest.raises(Exception):
        c.decrypt(bytes(bad))
def test_chacha_internal_helpers_roundtrip():
    c = _crypto()
    key = base64.urlsafe_b64encode(os.urandom(32))
    enc = c._chacha_encrypt(b"abc", key)
    assert c._chacha_decrypt(enc, key) == b"abc"
def test_key_created_on_disk(tmp_path, monkeypatch):
    import kitsune.crypto as crypto
    key_path = tmp_path / "new.key"
    monkeypatch.setattr(crypto, "KEY_PATH", key_path)
    crypto._load_or_create_key()
    assert key_path.exists()
def test_key_file_permissions(tmp_path, monkeypatch):
    import kitsune.crypto as crypto
    key_path = tmp_path / "perm.key"
    monkeypatch.setattr(crypto, "KEY_PATH", key_path)
    crypto._load_or_create_key()
    if hasattr(os, "stat") and os.name != "nt":
        mode = os.stat(key_path).st_mode & 0o777
        assert mode == 0o600
def test_key_loaded_from_env(monkeypatch, tmp_path):
    import kitsune.crypto as crypto
    monkeypatch.setattr(crypto, "KEY_PATH", tmp_path / "env.key")
    custom_key = base64.urlsafe_b64encode(b"x" * 32)
    monkeypatch.setenv(crypto.KEY_ENV, custom_key.decode())
    loaded = crypto._load_or_create_key()
    assert loaded == custom_key
    assert not (tmp_path / "env.key").exists()
def test_key_persists_across_calls(tmp_path, monkeypatch):
    import kitsune.crypto as crypto
    monkeypatch.setattr(crypto, "KEY_PATH", tmp_path / "persist.key")
    k1 = crypto._load_or_create_key()
    k2 = crypto._load_or_create_key()
    assert k1 == k2
def test_different_keys_produce_different_ciphertexts(tmp_path, monkeypatch):
    import kitsune.crypto as crypto
    monkeypatch.setattr(crypto, "KEY_PATH", tmp_path / "k1.key")
    monkeypatch.setenv(crypto.KEY_ENV, base64.urlsafe_b64encode(b"a" * 32).decode())
    enc1 = crypto.encrypt(b"data")
    monkeypatch.setenv(crypto.KEY_ENV, base64.urlsafe_b64encode(b"b" * 32).decode())
    enc2 = crypto.encrypt(b"data")
    assert enc1 != enc2
def test_derived_key_from_credentials(tmp_path, monkeypatch):
    import kitsune.crypto as crypto
    cfg = tmp_path / "config.toml"
    cfg.write_text('api_id = "123456"\napi_hash = "abcdef0123456789abcdef0123456789"\n')
    monkeypatch.setattr(crypto, "KEY_PATH", tmp_path / ".kitsune" / "kitsune.key")
    real_init = crypto.__file__
    monkeypatch.setattr(crypto, "__file__", str(tmp_path / "fake" / "crypto.py"))
    derived = crypto._derive_key_from_credentials()
    assert derived is not None
    assert isinstance(derived, bytes)
    derived2 = crypto._derive_key_from_credentials()
    assert derived == derived2
def test_derived_key_returns_none_without_config(tmp_path, monkeypatch):
    import kitsune.crypto as crypto
    monkeypatch.setattr(crypto, "__file__", str(tmp_path / "no_cfg" / "crypto.py"))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home_no_kitsune")
    result = crypto._derive_key_from_credentials()
    assert result is None
