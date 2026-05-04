from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
from pathlib import Path

KEY_ENV  = "KITSUNE_KEY"
KEY_PATH = Path.home() / ".kitsune" / "kitsune.key"
MAGIC    = b"KBAK1:"

_AES_GCM_AVAILABLE = False
_FERNET_AVAILABLE  = False

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM
    _AES_GCM_AVAILABLE = True
except ImportError:
    pass

try:
    from cryptography.fernet import Fernet as _Fernet, InvalidToken as _InvalidToken
    _FERNET_AVAILABLE = True
except ImportError:
    pass

def _load_or_create_key() -> bytes:
    env_key = os.environ.get(KEY_ENV, "").strip()
    if env_key:
        return env_key.encode()

    if KEY_PATH.exists():
        return KEY_PATH.read_bytes().strip()

    key = base64.urlsafe_b64encode(os.urandom(32))

    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEY_PATH.write_bytes(key)
    try:
        KEY_PATH.chmod(0o600)
    except Exception:
        pass
    return key

def _aes_gcm_encrypt(data: bytes, key: bytes) -> bytes:
    raw_key = base64.urlsafe_b64decode(key + b"==")
    aes_key = hashlib.sha256(raw_key).digest()
    nonce = os.urandom(12)  
    aesgcm = _AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(nonce, data, None)

    return struct.pack(">I", len(nonce)) + nonce + ciphertext

def _aes_gcm_decrypt(data: bytes, key: bytes) -> bytes:
    raw_key = base64.urlsafe_b64decode(key + b"==")
    aes_key = hashlib.sha256(raw_key).digest()
    nonce_len = struct.unpack(">I", data[:4])[0]
    nonce = data[4:4 + nonce_len]
    ciphertext = data[4 + nonce_len:]
    aesgcm = _AESGCM(aes_key)
    return aesgcm.decrypt(nonce, ciphertext, None)

def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    raw_key = base64.urlsafe_b64decode(key + b"==")
    digest   = hashlib.sha256(raw_key).digest()
    result   = bytearray(len(data))
    for i, byte in enumerate(data):
        result[i] = byte ^ digest[i % 32]
    mac = hmac.new(raw_key, bytes(result), hashlib.sha256).digest()
    return mac + bytes(result)

def _xor_decrypt(data: bytes, key: bytes) -> bytes:
    raw_key  = base64.urlsafe_b64decode(key + b"==")
    mac      = data[:32]
    payload  = data[32:]
    expected = hmac.new(raw_key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("HMAC mismatch — data corrupted or wrong key")
    digest = hashlib.sha256(raw_key).digest()
    result = bytearray(len(payload))
    for i, byte in enumerate(payload):
        result[i] = byte ^ digest[i % 32]
    return bytes(result)

def encrypt(data: bytes) -> bytes:
    key = _load_or_create_key()
    if _AES_GCM_AVAILABLE:                                         
        return MAGIC + b"AESGCM1:" + _aes_gcm_encrypt(data, key)
    if _FERNET_AVAILABLE:                                          
        return MAGIC + _Fernet(key).encrypt(data)
    return MAGIC + b"XOR1:" + _xor_encrypt(data, key)             

def decrypt(data: bytes) -> bytes:
    if not data.startswith(MAGIC):
        raise ValueError("not an encrypted Kitsune backup")
    payload = data[len(MAGIC):]
    key     = _load_or_create_key()
    if payload.startswith(b"XOR1:"):
        return _xor_decrypt(payload[5:], key)
    if payload.startswith(b"AESGCM1:"):
        return _aes_gcm_decrypt(payload[8:], key)
    if _FERNET_AVAILABLE:
        return _Fernet(key).decrypt(payload)
    raise RuntimeError(
        "cryptography package is required to decrypt this backup. "
        "Install it: pkg install python-cryptography"
    )

def is_encrypted(data: bytes) -> bool:
    return data.startswith(MAGIC)

def key_path() -> Path:
    return KEY_PATH
