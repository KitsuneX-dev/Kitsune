from __future__ import annotations
import base64
import hashlib
import os
import struct
from pathlib import Path

KEY_ENV = "KITSUNE_KEY"

from .paths import data_dir as _kdd, harden_dir as _harden_dir, harden_file as _harden_file
KEY_PATH = _kdd() / "kitsune.key"
SALT_PATH = _kdd() / "kitsune.key.salt"

MAGIC = b"KBAK1:"

_PBKDF2_ITERATIONS = 600_000
_SALT_LEN = 16

_AES_GCM_AVAILABLE = False

_FERNET_AVAILABLE = False

_CHACHA_AVAILABLE = False

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
try:
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305 as _ChaCha20Poly1305
    _CHACHA_AVAILABLE = True
except ImportError:
    pass


def _parse_toml(text: str) -> dict:
    try:
        import toml as _toml
        return _toml.loads(text)
    except ImportError:
        import tomllib as _tomllib
        return _tomllib.loads(text)


def _derive_key_from_credentials() -> bytes | None:
    try:
        from .paths import (
            config_path as _kcp,
            is_secondary as _kis,
            data_dir as _kdd,
            in_docker as _kin_docker,
            effective_config_path as _kecp,
        )
        if _kis() or _kin_docker():
            cfg_path = _kcp(_kdd())
        else:
            cfg_path = _kecp()
            if not cfg_path.exists():
                cfg_path = Path.home() / "Kitsune" / "config.toml"
        if not cfg_path.exists():
            return None
        cfg = _parse_toml(cfg_path.read_text(encoding="utf-8"))
        api_id = str(cfg.get("api_id", "")).strip()
        api_hash = str(cfg.get("api_hash", "")).strip()
        if not api_id or not api_hash:
            return None
        seed = f"{api_id}:{api_hash}:kitsune-backup-key".encode()
        digest = hashlib.sha256(seed).digest()
        return base64.urlsafe_b64encode(digest)
    except Exception:
        return None


def _load_or_create_key() -> bytes:
    env_key = os.environ.get(KEY_ENV, "").strip()
    if env_key:
        return env_key.encode()
    if KEY_PATH.exists():
        stored = KEY_PATH.read_bytes().strip()
        if stored.startswith(b"derived:"):
            derived = _derive_key_from_credentials()
            if derived:
                return derived
        else:
            return stored
    derived = _derive_key_from_credentials()
    if derived:
        _harden_dir(KEY_PATH.parent)
        KEY_PATH.write_bytes(b"derived:" + derived)
        _harden_file(KEY_PATH)
        return derived
    import logging
    logging.getLogger(__name__).warning(
        "crypto: не удалось получить api_id/api_hash из config.toml — "
        "генерирую случайный ключ. После переустановки бэкап может не открыться!"
    )
    key = base64.urlsafe_b64encode(os.urandom(32))
    _harden_dir(KEY_PATH.parent)
    KEY_PATH.write_bytes(key)
    _harden_file(KEY_PATH)
    return key


def _load_or_create_salt() -> bytes:
    try:
        if SALT_PATH.exists():
            salt = SALT_PATH.read_bytes()
            if len(salt) >= _SALT_LEN:
                return salt
    except Exception:
        pass
    salt = os.urandom(_SALT_LEN)
    try:
        _harden_dir(SALT_PATH.parent)
        SALT_PATH.write_bytes(salt)
        _harden_file(SALT_PATH)
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "crypto: не удалось сохранить соль PBKDF2 — при переустановке "
            "новые бэкапы могут не открыться"
        )
    return salt


def _derive_aes_key_pbkdf2(raw_key: bytes) -> bytes:
    salt = _load_or_create_salt()
    return hashlib.pbkdf2_hmac("sha256", raw_key, salt, _PBKDF2_ITERATIONS, dklen=32)


def _legacy_aes_key(raw_key: bytes) -> bytes:
    return hashlib.sha256(raw_key).digest()


def _aes_gcm_encrypt(data: bytes, key: bytes) -> bytes:
    raw_key = base64.urlsafe_b64decode(key + b"==")
    aes_key = _derive_aes_key_pbkdf2(raw_key)
    nonce = os.urandom(12)
    aesgcm = _AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return struct.pack(">I", len(nonce)) + nonce + ciphertext


def _aes_gcm_decrypt(data: bytes, key: bytes, *, legacy: bool = False) -> bytes:
    raw_key = base64.urlsafe_b64decode(key + b"==")
    aes_key = _legacy_aes_key(raw_key) if legacy else _derive_aes_key_pbkdf2(raw_key)
    nonce_len = struct.unpack(">I", data[:4])[0]
    nonce = data[4:4 + nonce_len]
    ciphertext = data[4 + nonce_len:]
    aesgcm = _AESGCM(aes_key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def _chacha_encrypt(data: bytes, key: bytes) -> bytes:
    raw_key = base64.urlsafe_b64decode(key + b"==")
    k = _derive_aes_key_pbkdf2(raw_key)[:32].ljust(32, b"\0")
    nonce = os.urandom(12)
    return nonce + _ChaCha20Poly1305(k).encrypt(nonce, data, None)


def _chacha_decrypt(data: bytes, key: bytes, *, legacy: bool = False) -> bytes:
    raw_key = base64.urlsafe_b64decode(key + b"==")
    if legacy:
        k = _legacy_aes_key(raw_key)[:32].ljust(32, b"\0")
    else:
        k = _derive_aes_key_pbkdf2(raw_key)[:32].ljust(32, b"\0")
    return _ChaCha20Poly1305(k).decrypt(data[:12], data[12:], None)


def encrypt(data: bytes) -> bytes:
    key = _load_or_create_key()
    if _AES_GCM_AVAILABLE:
        return MAGIC + b"AESGCM2:" + _aes_gcm_encrypt(data, key)
    if _CHACHA_AVAILABLE:
        return MAGIC + b"CHACHA2:" + _chacha_encrypt(data, key)
    if _FERNET_AVAILABLE:
        return MAGIC + _Fernet(key).encrypt(data)
    raise RuntimeError(
        "cryptography package is required to encrypt this backup. "
        "Install it: pip install cryptography"
    )


def decrypt(data: bytes) -> bytes:
    if not data.startswith(MAGIC):
        raise ValueError("not an encrypted Kitsune backup")
    payload = data[len(MAGIC):]
    key = _load_or_create_key()
    if payload.startswith(b"AESGCM2:"):
        try:
            return _aes_gcm_decrypt(payload[8:], key)
        except Exception:
            return _aes_gcm_decrypt(payload[8:], key, legacy=True)
    if payload.startswith(b"CHACHA2:"):
        if not _CHACHA_AVAILABLE:
            raise RuntimeError(
                "cryptography package is required to decrypt CHACHA2 backups."
            )
        try:
            return _chacha_decrypt(payload[8:], key)
        except Exception:
            return _chacha_decrypt(payload[8:], key, legacy=True)
    if payload.startswith(b"CHACHA1:"):
        if not _CHACHA_AVAILABLE:
            raise RuntimeError(
                "cryptography package is required to decrypt CHACHA1 backups."
            )
        return _chacha_decrypt(payload[8:], key, legacy=True)
    if payload.startswith(b"AESGCM1:"):
        return _aes_gcm_decrypt(payload[8:], key, legacy=True)
    if _FERNET_AVAILABLE:
        return _Fernet(key).decrypt(payload)
    raise RuntimeError(
        "cryptography package is required to decrypt this backup. "
        "Install it: pkg install python-cryptography"
    )


def format_version(data: bytes) -> int:
    if not data.startswith(MAGIC):
        return 0
    payload = data[len(MAGIC):]
    if payload.startswith(b"AESGCM2:") or payload.startswith(b"CHACHA2:"):
        return 2
    return 1


def decrypt_and_reencrypt(data: bytes) -> tuple[bytes, bytes | None]:
    plaintext = decrypt(data)
    if format_version(data) < 2:
        try:
            return plaintext, encrypt(plaintext)
        except Exception:
            return plaintext, None
    return plaintext, None


def is_encrypted(data: bytes) -> bool:
    return data.startswith(MAGIC)


def key_path() -> Path:
    return KEY_PATH
