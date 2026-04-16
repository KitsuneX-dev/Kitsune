from __future__ import annotations

import math
import struct
import typing

_EXP = [0] * 512
_LOG = [0] * 256

_EXP[0] = 1
for _i in range(1, 255):
    _EXP[_i] = _EXP[_i - 1] * 2
    if _EXP[_i] >= 256:
        _EXP[_i] ^= 0x11D
for _i in range(255):
    _LOG[_EXP[_i]] = _i
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]

def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]

def _rs_generator(degree: int) -> list[int]:
    g = [1]
    for i in range(degree):
        g = _poly_mul(g, [1, _EXP[i]])
    return g

def _poly_mul(p: list[int], q: list[int]) -> list[int]:
    result = [0] * (len(p) + len(q) - 1)
    for i, pi in enumerate(p):
        for j, qj in enumerate(q):
            result[i + j] ^= _gf_mul(pi, qj)
    return result

def _rs_encode(data: list[int], n_ec: int) -> list[int]:
    gen = _rs_generator(n_ec)
    msg = data + [0] * n_ec
    for i in range(len(data)):
        if msg[i] == 0:
            continue
        coef = msg[i]
        for j in range(len(gen)):
            msg[i + j] ^= _gf_mul(gen[j], coef)
    return msg[len(data):]

_EC_BLOCKS: dict[str, dict[int, tuple[int, int, int, int]]] = {
    "L": {
        1: (19, 7, 1, 19),
        2: (34, 10, 1, 34),
        3: (55, 15, 1, 55),
        4: (80, 20, 1, 80),
        5: (108, 26, 1, 108),
    },
    "M": {
        1: (16, 10, 1, 16),
        2: (28, 16, 1, 28),
        3: (44, 26, 1, 44),
        4: (64, 18, 2, 32),
        5: (86, 24, 2, 43),
    },
}

_FORMAT_INFO: dict[str, int] = {"L": 0b01, "M": 0b00}

_ALIGN: dict[int, list[int]] = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30],
}

class _QRMatrix:

    def __init__(self, size: int) -> None:
        self.size = size
        self._m: list[list[int]] = [[-1] * size for _ in range(size)]

    def set(self, r: int, c: int, val: int, force: bool = False) -> None:
        if force or self._m[r][c] == -1:
            self._m[r][c] = val

    def get(self, r: int, c: int) -> int:
        return self._m[r][c]

    def is_free(self, r: int, c: int) -> bool:
        return self._m[r][c] == -1

    def rows(self) -> list[list[int]]:
        return self._m

def _qr_version_for(data_len: int, ec: str) -> int:
    for v in range(1, 6):
        cap = _EC_BLOCKS[ec][v][0]
        max_bytes = cap - 3
        if max_bytes >= data_len:
            return v
    raise ValueError(f"Данные слишком длинные для QR v1-5 (длина {data_len})")

def _place_finder(m: _QRMatrix, r: int, c: int) -> None:
    pat = [
        [1, 1, 1, 1, 1, 1, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 1, 1, 1, 0, 1],
        [1, 0, 0, 0, 0, 0, 1],
        [1, 1, 1, 1, 1, 1, 1],
    ]
    for dr, row in enumerate(pat):
        for dc, val in enumerate(row):
            m.set(r + dr, c + dc, val, force=True)

def _place_timing(m: _QRMatrix) -> None:
    n = m.size
    for i in range(8, n - 8):
        v = 1 if i % 2 == 0 else 0
        m.set(6, i, v, force=True)
        m.set(i, 6, v, force=True)

def _place_dark(m: _QRMatrix) -> None:
    m.set(8, 4 * (_version_size_to_v(m.size)) + 9, 1, force=True)

def _version_size_to_v(size: int) -> int:
    return (size - 21) // 4 + 1

def _place_format(m: _QRMatrix, ec: str, mask: int) -> None:
    fi = (_FORMAT_INFO[ec] << 3) | mask
    gen = 0x537
    rem = fi << 10
    for _ in range(10):
        if rem & (1 << (14 - _)):
            rem ^= gen << (4 - _)
    fi = ((fi << 10) | rem) ^ 0x5412

    bits = [(fi >> i) & 1 for i in range(15)]
    pos = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
           (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    for i, (r, c) in enumerate(pos):
        m.set(r, c, bits[i], force=True)
    n = m.size
    mirror = [(n - 1 - i, 8) for i in range(7)] + [(8, n - 8 + i) for i in range(8)]
    for i, (r, c) in enumerate(mirror):
        m.set(r, c, bits[i], force=True)

def _encode_data(text: str, version: int, ec: str) -> list[int]:
    data_bytes = text.encode("utf-8") if isinstance(text, str) else text
    n          = len(data_bytes)
    bits: list[int] = []

    bits += [0, 1, 0, 0]
    bits += [(n >> i) & 1 for i in range(7, -1, -1)]
    for byte in data_bytes:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]

    total_bits = _EC_BLOCKS[ec][version][0] * 8
    for _ in range(min(4, total_bits - len(bits))):
        bits.append(0)
    while len(bits) % 8:
        bits.append(0)
    pad = [0b11101100, 0b00010001]
    i = 0
    while len(bits) < total_bits:
        bits += [(pad[i % 2] >> j) & 1 for j in range(7, -1, -1)]
        i += 1

    return [int("".join(str(b) for b in bits[i:i+8]), 2) for i in range(0, len(bits), 8)]

def _interleave_and_ec(codewords: list[int], version: int, ec: str) -> list[int]:
    n_ec, ec_per, n1, d1 = _EC_BLOCKS[ec][version]
    blocks = [codewords[i * d1:(i + 1) * d1] for i in range(n1)]
    ec_blocks = [_rs_encode(b, ec_per) for b in blocks]

    result: list[int] = []
    max_d = max(len(b) for b in blocks)
    for i in range(max_d):
        for b in blocks:
            if i < len(b):
                result.append(b[i])
    max_e = max(len(e) for e in ec_blocks)
    for i in range(max_e):
        for e in ec_blocks:
            if i < len(e):
                result.append(e[i])
    return result

def _apply_mask(m: _QRMatrix, mask: int) -> _QRMatrix:
    n = m.size
    masked = _QRMatrix(n)
    masked._m = [row[:] for row in m._m]
    conditions = [
        lambda r, c: (r + c) % 2 == 0,
        lambda r, c: r % 2 == 0,
        lambda r, c: c % 3 == 0,
        lambda r, c: (r + c) % 3 == 0,
        lambda r, c: (r // 2 + c // 3) % 2 == 0,
        lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
        lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
        lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
    ]
    cond = conditions[mask]
    for r in range(n):
        for c in range(n):
            if masked._m[r][c] in (0, 1):
                if m.get(r, c) != -1 and cond(r, c):
                    masked._m[r][c] ^= 1
    return masked

def _place_bits(m: _QRMatrix, bitstream: list[int]) -> None:
    n    = m.size
    idx  = 0
    up   = True

    col = n - 1
    while col >= 0:
        if col == 6:
            col -= 1
            continue
        row_range = range(n - 1, -1, -1) if up else range(n)
        for row in row_range:
            for dc in range(2):
                c = col - dc
                if m.is_free(row, c) and idx < len(bitstream):
                    m.set(row, c, bitstream[idx])
                    idx += 1
        col -= 2
        up = not up

def _make_matrix(text: str, ec: str = "M") -> _QRMatrix:
    version  = _qr_version_for(len(text.encode("utf-8")), ec)
    size     = 21 + (version - 1) * 4
    m        = _QRMatrix(size)

    _place_finder(m, 0, 0)
    _place_finder(m, 0, size - 7)
    _place_finder(m, size - 7, 0)

    for i in range(8):
        for pos in [(7, i), (i, 7), (7, size - 1 - i), (i, size - 8),
                    (size - 8, i), (size - 1 - i, 7)]:
            m.set(*pos, 0, force=True)

    _place_timing(m)

    m.set(4 * version + 9, 8, 1, force=True)

    _place_format(m, ec, 0)

    data = _encode_data(text, version, ec)
    full = _interleave_and_ec(data, version, ec)
    bits = []
    for byte in full:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]

    _place_bits(m, bits)

    best_mask = 0
    masked = _apply_mask(m, best_mask)
    _place_format(masked, ec, best_mask)

    return masked

def make_qr_text(text: str, ec: str = "M") -> str:
    m     = _make_matrix(text, ec)
    rows  = m.rows()
    lines = []
    quiet = "  "
    border = quiet + "  " * m.size + quiet
    lines.append(border)
    for row in rows:
        line = quiet
        for cell in row:
            line += "██" if cell == 1 else "  "
        line += quiet
        lines.append(line)
    lines.append(border)
    return "\n".join(lines)

def make_qr_image(text: str, ec: str = "M", scale: int = 10) -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        raise ImportError("Для make_qr_image нужен Pillow: pip install Pillow")

    m      = _make_matrix(text, ec)
    rows   = m.rows()
    n      = m.size
    quiet  = 4
    total  = (n + quiet * 2) * scale

    img  = Image.new("RGB", (total, total), "white")
    draw = ImageDraw.Draw(img)

    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if cell == 1:
                x1 = (c + quiet) * scale
                y1 = (r + quiet) * scale
                x2 = x1 + scale
                y2 = y1 + scale
                draw.rectangle([x1, y1, x2, y2], fill="black")

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
