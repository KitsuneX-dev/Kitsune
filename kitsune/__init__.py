from __future__ import annotations

import logging as _logging

__author__ = "Yushi"

__contact__ = "@Mikasu32"

__copyright__ = "Copyright 2024-2026, Yushi"

__license__ = "AGPLv3"

__status__ = "Production"

_log = _logging.getLogger(__name__)

_PATCHES_INSTALLED = False

def install_patches() -> None:

    global _PATCHES_INSTALLED

    if _PATCHES_INSTALLED:

        return

    try:

        from telethon.network.connection import tcpmtproxy as _m

        _target = None

        for _name in dir(_m):

            _obj = getattr(_m, _name, None)

            if isinstance(_obj, type) and "readexactly" in _obj.__dict__:

                _target = _obj

                break

        if _target is not None and not getattr(

            _target.readexactly, "_kitsune_size_guard", False

        ):

            _orig = _target.readexactly

            async def _readexactly_safe(self, n):

                if n is None or n < 0:

                    raise ConnectionError(

                        f"MTProxy: invalid packet size ({n!r})"

                    )

                if n == 0:

                    return b""

                return await _orig(self, n)

            _readexactly_safe._kitsune_size_guard = True

            _target.readexactly = _readexactly_safe

            _log.info(

                "kitsune: MTProxy hardening (patched %s.readexactly)",

                _target.__name__,

            )

    except Exception as _exc:

        _log.debug("kitsune: MTProxyIO patch skipped — %s", _exc)

    try:

        from telethon.network.connection import tcpintermediate as _ti

        _cls = getattr(_ti, "IntermediatePacketCodec", None)

        if (

            _cls is not None

            and "read_packet" in _cls.__dict__

            and not getattr(_cls.read_packet, "_kitsune_len_guard", False)

        ):

            import struct as _struct

            async def _read_packet_safe(self, reader):

                length_bytes = await reader.readexactly(4)

                if not length_bytes or len(length_bytes) < 4:

                    raise ConnectionError(

                        "Intermediate codec: short read on length field"

                    )

                (length,) = _struct.unpack("<i", length_bytes)

                MAX_PACKET = 16 * 1024 * 1024

                if length <= 0 or length > MAX_PACKET:

                    raise ConnectionError(

                        f"Intermediate codec: bogus packet length ({length})"

                    )

                return await reader.readexactly(length)

            _read_packet_safe._kitsune_len_guard = True

            _cls.read_packet = _read_packet_safe

            _log.info(

                "kitsune: MTProxy hardening (patched %s.read_packet)",

                _cls.__name__,

            )

    except Exception as _exc:

        _log.debug("kitsune: IntermediatePacketCodec patch skipped — %s", _exc)

    _PATCHES_INSTALLED = True

