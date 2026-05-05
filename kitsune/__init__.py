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
#  Чиним ДВА бага сразу:
#
#  (A) ``ValueError: readexactly size can not be less than zero`` —
#      когда FakeTLS-прокси отдаёт мусор и в length-поле прилетает <0.
#
#  (B) ``../crypto/aes/aes_ige.c:60: OpenSSL internal error:
#      assertion failed: (length % AES_BLOCK_SIZE) == 0`` →  Aborted —
#      этот баг ПОРОЖДАЛ САМ ПРЕДЫДУЩИЙ ПАТЧ. Старая версия патча
#      перезаписывала ОБА класса (IntermediatePacketCodec И
#      RandomizedIntermediatePacketCodec), затирая в Randomized-варианте
#      штатное снятие padding-а ``len(pkt) % 4``. В MTProto-слой приходил
#      пакет с 1–3 байтами случайного хвоста → длина не кратна 16 →
#      нативный AES-IGE (cryptg / OpenSSL) делал abort() прямо в C.
#
#  Решение:
#    * Патчим ТОЛЬКО ``IntermediatePacketCodec.read_packet`` — это
#      базовый метод, и ``RandomizedIntermediatePacketCodec.read_packet``
#      сам зовёт ``super().read_packet()``, так что наш size-guard
#      достаётся ему автоматически, а штатное снятие padding-а
#      остаётся НЕТРОНУТЫМ.
#    * Патчим ``MTProxyIO.readexactly`` как нижний слой защиты.
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
    #    ТОЛЬКО базовый класс! RandomizedIntermediatePacketCodec унаследует
    #    наш size-guard через super().read_packet() и продолжит штатно
    #    снимать свой padding %4.  Если перезаписать обе read_packet —
    #    выпиливается снятие padding-а и ломается AES-IGE длина → abort().
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
                # Сами читаем 4 байта длины и валидируем перед тем,
                # как уйти в reader.readexactly(length).
                length_bytes = await reader.readexactly(4)
                if not length_bytes or len(length_bytes) < 4:
                    raise ConnectionError(
                        "Intermediate codec: short read on length field"
                    )

                # signed=False — корректный парсинг для Telegram intermediate.
                # Старый «signed=True» — это был костыль, теперь он не нужен,
                # потому что нижний readexactly_safe уже отсекает мусор.
                (length,) = _struct.unpack("<i", length_bytes)

                # Реальные пакеты Telegram — десятки байт..несколько мегабайт.
                # Всё, что выше 16 MiB или ≤0 — мусор.
                MAX_PACKET = 16 * 1024 * 1024
                if length <= 0 or length > MAX_PACKET:
                    raise ConnectionError(
                        f"Intermediate codec: bogus packet length "
                        f"({length}) — proxy stream desynced"
                    )

                # ВАЖНО: НЕ снимаем здесь padding %4. Если поверх нас стоит
                # RandomizedIntermediatePacketCodec — он сделает это сам,
                # вызывая нас через super().read_packet().
                return await reader.readexactly(length)

            _read_packet_safe._kitsune_len_guard = True
            _cls.read_packet = _read_packet_safe
            _log.info(
                "kitsune: MTProxy hardening active (patched %s.read_packet)",
                _cls.__name__,
            )
    except Exception as _exc:
        _log.debug("kitsune: IntermediatePacketCodec patch skipped — %s", _exc)


_kitsune_install_mtproxy_hardening()
