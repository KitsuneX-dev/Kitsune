from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

KEY_ENV  = "KITSUNE_KEY"
KEY_PATH = Path.home() / ".kitsune" / "kitsune.key"

MAGIC = b"KBAK1:"

def _load_or_create_key() -> bytes:
    env_key = os.environ.get(KEY_ENV, "").strip()
    if env_key:
        return env_key.encode()

    if KEY_PATH.exists():
        return KEY_PATH.read_bytes().strip()

    key = Fernet.generate_key()
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEY_PATH.write_bytes(key)
    KEY_PATH.chmod(0o600)
    return key

def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())

def encrypt(data: bytes) -> bytes:
    return MAGIC + _fernet().encrypt(data)

def decrypt(data: bytes) -> bytes:
    if not data.startswith(MAGIC):
        raise ValueError("not an encrypted Kitsune backup")
    return _fernet().decrypt(data[len(MAGIC):])

def is_encrypted(data: bytes) -> bool:
    return data.startswith(MAGIC)

def key_path() -> Path:
    return KEY_PATH
