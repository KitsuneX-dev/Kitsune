from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_AST_SCAN_OK_FILENAME: str = ".ast_scan_ok.json"
_AST_SCAN_OK_MAX_SIZE: int = 50000
_AST_SCAN_OK_FLUSH_EVERY: int = 25
_ast_scan_ok_pending: int = 0


_ast_scan_ok_hashes: set[str] = set()
_ast_scan_ok_loaded: bool = False
_ast_scan_ok_dirty: bool = False

def _ast_scan_ok_path() -> Path:
    from ...paths import data_dir as _kdd
    return _kdd() / _AST_SCAN_OK_FILENAME

def _load_ast_scan_cache() -> None:
    global _ast_scan_ok_loaded
    if _ast_scan_ok_loaded:
        return
    _ast_scan_ok_loaded = True
    path = _ast_scan_ok_path()
    try:
        if not path.exists():
            return
        from ... import _json
        data = _json.loads(path.read_bytes())
    except Exception:
        logger.debug("loader: не удалось прочитать %s", path, exc_info=True)
        return
    if not isinstance(data, list):
        logger.debug("loader: %s имеет неожиданный формат — игнорирую", path)
        return
    for item in data:
        if isinstance(item, str) and len(item) == 64:
            _ast_scan_ok_hashes.add(item)
    logger.debug(
        "loader: дисковый AST-кэш загружен (%d хэшей)", len(_ast_scan_ok_hashes)
    )

def flush_ast_scan_cache() -> None:
    global _ast_scan_ok_dirty
    if not _ast_scan_ok_dirty:
        return
    hashes = _ast_scan_ok_hashes
    if len(hashes) > _AST_SCAN_OK_MAX_SIZE:


        import itertools
        hashes = set(itertools.islice(hashes, _AST_SCAN_OK_MAX_SIZE))
    path = _ast_scan_ok_path()
    try:
        from ...paths import harden_dir, harden_file
        harden_dir(path.parent)
        from ... import _json
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(_json.dumps_bytes(sorted(hashes)))
        os.replace(tmp, path)
        harden_file(path)
        _ast_scan_ok_dirty = False
        logger.debug("loader: дисковый AST-кэш сохранён (%d хэшей)", len(hashes))
    except Exception:
        logger.debug("loader: не удалось сохранить %s", path, exc_info=True)

def _remember_ast_scan_ok(key: str) -> None:
    global _ast_scan_ok_dirty, _ast_scan_ok_pending
    if key in _ast_scan_ok_hashes:
        return
    _ast_scan_ok_hashes.add(key)
    _ast_scan_ok_dirty = True
    _ast_scan_ok_pending += 1
    if _ast_scan_ok_pending >= _AST_SCAN_OK_FLUSH_EVERY:
        _ast_scan_ok_pending = 0
        flush_ast_scan_cache()
