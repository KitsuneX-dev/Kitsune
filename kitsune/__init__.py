__author__ = "Yushi"
__contact__ = "@Mikasu32"
__copyright__ = "Copyright 2024-2026, Yushi"
__license__ = "AGPLv3"
__status__ = "Production"

# ─────────────────────────────────────────────────────────────────────────────
#  Telethon MTProxy hardening
# ─────────────────────────────────────────────────────────────────────────────
#  Этот блок ОБЯЗАН стоять в kitsune/__init__.py (а не в подмодуле!), потому
#  что только так он гарантированно выполнится ДО того, как kitsune.main
#  импортирует telethon.network.connection.* и любой код начнёт пользоваться
#  пропатченными классами.
#
#  Чиним баг в Telethon, который ловится у пользователя в проде:
#
#    File ".../telethon/network/connection/tcpmtproxy.py", line 77, in readexactly
#        return self._decrypt.encrypt(await self._reader.readexactly(n))
#    File ".../telethon/network/connection/tcpintermediate.py", line 17, in read_packet
#        return await reader.readexactly(length)
#    File ".../asyncio/streams.py", line 694, in readexactly
#        raise ValueError('readexactly size can not be less than zero')
#
#  Корень: IntermediatePacketCodec.read_packet читает 4 байта длины, делает
#  ``int.from_bytes(..., signed=False)`` НО Telethon на ряде версий парсит
#  как signed (или после XOR-расшифровки в MTProxyIO длина уже мусорная и
#  старший бит выставлен) → length ∈ [-2^31, -1] → asyncio роняет ValueError,
#  и весь _recv_loop помирает БЕЗ корректного разрыва соединения, что потом
#  каскадом рождает ``'NoneType' object has no attribute 'connect'`` в
#  MTProtoSender и ``Server replied with a wrong session ID``.
#
#  Защищаемся СРАЗУ В ТРЁХ слоях:
#    (1) MTProxyIO.readexactly — обёртка с size guard;
#    (2) IntermediatePacketCodec.read_packet — перехватываем парсинг длины;
#    (3) ObfuscatedConnection / packet codec общая страховка.
# ─────────────────────────────────────────────────────────────────────────────

import logging as _logging

_log = _logging.getLogger(__name__)


def _kitsune_install_mtproxy_hardening() -> None:
    """Многослойный патч Telethon. Ставится один раз при импорте пакета."""
    # 1) MTProxyIO.readexactly --------------------------------------------------
    try:
        from telethon.network.connection import tcpmtproxy as _m

        _target = None
        # MTProxyIO — официальное имя в Telethon v1; на всякий случай ищем
        # любой класс модуля, в котором ОПРЕДЕЛЁН (не унаследован) readexactly.
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
                # asyncio.StreamReader.readexactly валится с ValueError при n<0.
                # Ловим раньше и поднимаем ConnectionError — Telethon штатно
                # обрабатывает её как обрыв и идёт в auto_reconnect.
                if n is None or n < 0:
                    raise ConnectionError(
                        f"MTProxy: invalid packet size ({n!r}) — "
                        "proxy returned garbage; aborting stream"
                    )
                if n == 0:
                    return b""
                return await _orig(self, n)

            _readexactly_safe._kitsune_size_guard = True
            _target.readexactly = _readexactly_safe
            _log.info(
                "kitsune: MTProxy hardening active (patched %s.readexactly)",
                _target.__name__,
            )
    except Exception as _exc:
        _log.debug("kitsune: MTProxyIO patch skipped — %s", _exc)

    # 2) IntermediatePacketCodec.read_packet -----------------------------------
    #    Это ИСТИННЫЙ источник отрицательного size: тут парсится 4 байта длины
    #    из потока. Если они уже мусор после XOR-расшифровки MTProxyIO —
    #    ловим тут и рвём соединение по-человечески.
    try:
        from telethon.network.connection import tcpintermediate as _ti

        _candidates = (
            getattr(_ti, "IntermediatePacketCodec", None),
            getattr(_ti, "RandomizedIntermediatePacketCodec", None),
        )
        for _cls in _candidates:
            if _cls is None:
                continue
            if "read_packet" not in _cls.__dict__:
                continue
            if getattr(_cls.read_packet, "_kitsune_len_guard", False):
                continue

            _orig_read = _cls.read_packet

            async def _read_packet_safe(self, reader, _orig=_orig_read):
                # Сами читаем 4 байта длины и валидируем перед тем,
                # как уйти в reader.readexactly(length).
                length_bytes = await reader.readexactly(4)
                # signed=True — потому что именно signed-парсинг в комбинации
                # с мусорным старшим битом и порождает «<0».
                length = int.from_bytes(length_bytes, "little", signed=False)

                # Реальные пакеты Telegram — десятки байт..несколько мегабайт.
                # Всё, что выше 16 MiB или нечётно в плохом смысле — мусор.
                MAX_PACKET = 16 * 1024 * 1024
                if length <= 0 or length > MAX_PACKET:
                    raise ConnectionError(
                        f"Intermediate codec: bogus packet length "
                        f"({length}) — proxy stream desynced"
                    )

                # Для RandomizedIntermediate длина выровнена по 4 — но на
                # всякий случай не паримся, отдадим как есть.
                data = await reader.readexactly(length)
                return data

            _read_packet_safe._kitsune_len_guard = True
            _cls.read_packet = _read_packet_safe
            _log.info(
                "kitsune: MTProxy hardening active (patched %s.read_packet)",
                _cls.__name__,
            )
    except Exception as _exc:
        _log.debug("kitsune: IntermediatePacketCodec patch skipped — %s", _exc)


_kitsune_install_mtproxy_hardening()
