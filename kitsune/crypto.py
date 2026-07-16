from __future__ import annotations
import base64
import hashlib
import os
import struct
from pathlib import Path

KEY_ENV = "KITSUNE_KEY"

KEY_PATH = Path.home() / ".kitsune" / "kitsune.key"

MAGIC = b"KBAK1:"

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


def _derive_key_from_credentials() -> bytes | None:
    try:
        import toml
        cfg_path = Path(__file__).parent.parent / "config.toml"
        if not cfg_path.exists():
            cfg_path = Path.home() / "Kitsune" / "config.toml"
        if not cfg_path.exists():
            return None
        cfg = toml.loads(cfg_path.read_text(encoding="utf-8"))
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
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        KEY_PATH.write_bytes(b"derived:" + derived)
        try:
            KEY_PATH.chmod(0o600)
        except Exception:
            pass
        return derived
    import logging
    logging.getLogger(__name__).warning(
        "crypto: не удалось получить api_id/api_hash из config.toml — "
        "генерирую случайный ключ. После переустановки бэкап может не открыться!"
    )
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


def _chacha_encrypt(data: bytes, key: bytes) -> bytes:
    raw_key = base64.urlsafe_b64decode(key + b"==")
    k = hashlib.sha256(raw_key).digest()[:32].ljust(32, b"\0")
    nonce = os.urandom(12)
    return nonce + _ChaCha20Poly1305(k).encrypt(nonce, data, None)


def _chacha_decrypt(data: bytes, key: bytes) -> bytes:
    raw_key = base64.urlsafe_b64decode(key + b"==")
    k = hashlib.sha256(raw_key).digest()[:32].ljust(32, b"\0")
    return _ChaCha20Poly1305(k).decrypt(data[:12], data[12:], None)


def encrypt(data: bytes) -> bytes:
    key = _load_or_create_key()
    if _AES_GCM_AVAILABLE:
        return MAGIC + b"AESGCM1:" + _aes_gcm_encrypt(data, key)
    if _FERNET_AVAILABLE:
        return MAGIC + _Fernet(key).encrypt(data)
    if _CHACHA_AVAILABLE:
        return MAGIC + b"CHACHA1:" + _chacha_encrypt(data, key)
    raise RuntimeError(
        "cryptography package is required to encrypt this backup. "
        "Install it: pip install cryptography"
    )


def decrypt(data: bytes) -> bytes:
    if not data.startswith(MAGIC):
        raise ValueError("not an encrypted Kitsune backup")
    payload = data[len(MAGIC):]
    key = _load_or_create_key()
    if payload.startswith(b"CHACHA1:"):
        if not _CHACHA_AVAILABLE:
            raise RuntimeError(
                "cryptography package is required to decrypt CHACHA1 backups."
            )
        return _chacha_decrypt(payload[8:], key)
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
