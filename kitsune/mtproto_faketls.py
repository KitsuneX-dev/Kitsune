from __future__ import annotations
import asyncio
import base64
import hashlib
import hmac
import logging
import random
import re
import socket
import time
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from telethon.network.connection.tcpmtproxy import (
    ConnectionTcpMTProxyRandomizedIntermediate,
)

logger = logging.getLogger(__name__)

def _decode_b64(s: str) -> bytes:
    s = re.sub(r"[^a-zA-Z0-9+/=_-]+", "", s)
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)
def _decode_faketls_secret(secret: str) -> bytes:
    s = secret.strip()
    if not s:
        raise ValueError("Empty MTProto secret")
    is_hex = all(c in "0123456789abcdefABCDEF" for c in s)
    if is_hex:
        if s.lower().startswith("ee"):
            raw = bytes.fromhex(s)
        else:
            raw = bytes.fromhex("ee" + s)
    else:
        if s.startswith("7"):
            raw = _decode_b64(s)
        else:
            raw = _decode_b64("7" + s)
    if len(raw) <= 17 or raw[0] != 0xEE:
        raise ValueError("FakeTLS secret must start with ee/7 and contain a domain")
    return raw
def is_faketls_secret(secret: str | None) -> bool:
    if not secret:
        return False
    try:
        raw = _decode_faketls_secret(secret)
    except Exception:
        return False
    return len(raw) > 17 and raw[0] == 0xEE
class _CryptographyEncryptorAdapter:
    __slots__ = ("encryptor", "decryptor")
    def __init__(self, cipher):
        self.encryptor = cipher.encryptor()
        self.decryptor = cipher.decryptor()
    def encrypt(self, data: bytes) -> bytes:
        return self.encryptor.update(data)
    def decrypt(self, data: bytes) -> bytes:
        return self.decryptor.update(data)
def _create_aes_ctr(key: bytes, iv: int):
    iv_bytes = int.to_bytes(iv, 16, "big")
    cipher = Cipher(algorithms.AES(key), modes.CTR(iv_bytes), default_backend())
    return _CryptographyEncryptorAdapter(cipher)
class _MyRandom(random.Random):
    def __init__(self):
        super().__init__()
        key = bytes([random.randrange(256) for _ in range(32)])
        iv = random.randrange(256**16)
        self.encryptor = _create_aes_ctr(key, iv)
        self.buffer = bytearray()
    def getrandbits(self, k):
        numbytes = (k + 7) // 8
        return int.from_bytes(self.getrandbytes(numbytes), "big") >> (numbytes * 8 - k)
    def getrandbytes(self, n):
        chunk_size = 512
        while n > len(self.buffer):
            data = int.to_bytes(super().getrandbits(chunk_size * 8), chunk_size, "big")
            self.buffer += self.encryptor.encrypt(data)
        result = self.buffer[:n]
        self.buffer = self.buffer[n:]
        return bytes(result)
_myrandom = _MyRandom()

def _gen_x25519_public_key() -> bytes:
    p = 2**255 - 19
    n = _myrandom.randrange(p)
    return int.to_bytes((n * n) % p, length=32, byteorder="little")
def _gen_sha256_digest(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key=key, msg=msg, digestmod=hashlib.sha256).digest()
class MTProxyFakeTLSClientCodec:
    client_hello_dict: dict[str, bytes] = {
        "content_type": b"\x16",
        "version": b"\x03\x01",
        "len": b"\x02\x00",
        "handshake_type": b"\x01",
        "handshake_len": b"\x00\x01\xfc",
        "handshake_version": b"\x03\x03",
        "random": b"\x00" * 32,
        "session_id_len": b"\x20",
        "session_id": b"\x00" * 32,
        "cipher_suites_len": b"\x00\x20",
        "cipher_suites": (
            b"\xfa\xfa\x13\x01\x13\x02\x13\x03\xc0\x2b\xc0\x2f\xc0\x2c\xc0\x30"
            b"\xcc\xa9\xcc\xa8\xc0\x13\xc0\x14\x00\x9c\x00\x9d\x00\x2f\x00\x35"
        ),
        "compression_methods_len": b"\x01",
        "compression_methods": b"\x00",
        "extensions_len": b"\x01\x93",
        "ext_reserved_1": b"\x4a\x4a\x00\x00",
        "ext_server_name_type": b"\x00\x00",
        "ext_server_name_len": b"\x00\x00",
        "ext_server_name_indication_list_len": b"\x00\x00",
        "ext_server_name_indication_type": b"\x00",
        "ext_server_name_indication_len": b"\x00\x00",
        "ext_server_name_indication": b"\x00",
        "ext_extended_master_secret": b"\x00\x17\x00\x00",
        "ext_renegotiation_info": b"\xff\x01\x00\x01\x00",
        "ext_supported_groups": b"\x00\x0a\x00\x0a\x00\x08\xba\xba\x00\x1d\x00\x17\x00\x18",
        "ext_ec_point_formats": b"\x00\x0b\x00\x02\x01\x00",
        "ext_session_ticket": b"\x00\x23\x00\x00",
        "ext_alpn": b"\x00\x10\x00\x0e\x00\x0c\x02\x68\x32\x08\x68\x74\x74\x70\x2f\x31\x2e\x31",
        "ext_status_request": b"\x00\x05\x00\x05\x01\x00\x00\x00\x00",
        "ext_signature_algorithms": (
            b"\x00\x0d\x00\x12\x00\x10\x04\x03\x08\x04\x04\x01\x05\x03\x08\x05\x05\x01\x08\x06\x06\x01"
        ),
        "ext_signature_cert_timestamp": b"\x00\x12\x00\x00",
        "ext_key_share_type": b"\x00\x33",
        "ext_key_share_len": b"\x00\x2b",
        "ext_key_share_client_key_len": b"\x00\x29",
        "ext_key_share_reserved": b"\xba\xba\x00\x01\x00",
        "ext_key_share_group": b"\x00\x1d",
        "ext_key_share_exchange_len": b"\x00\x20",
        "ext_key_share_exchange": b"\x00",
        "ext_psk_key_exchange_modes": b"\x00\x2d\x00\x02\x01\x01",
        "ext_supported_tls_versions": b"\x00\x2b\x00\x0b\x0a\x9a\x9a\x03\x04\x03\x03\x03\x02\x03\x01",
        "ext_compress_cert": b"\x00\x1b\x00\x03\x02\x00\x02",
        "ext_reserved_2": b"\x1a\x1a\x00\x01\x00",
        "ext_padding_type": b"\x00\x15",
        "ext_padding_len": b"\x00\x00",
        "ext_padding": b"",
    }
    def __init__(self, secret: str):
        raw = _decode_faketls_secret(secret)
        self.domain = raw[17:]
        self.secret = raw[1:17]
        self.is_pkt_changed = True
        self.pkt = b""
    def client_hello(self, key: str, value=None, ret_type=bytes):
        if value is None:
            if ret_type is bytes:
                return self.client_hello_dict[key]
            if ret_type is str:
                return self.client_hello_dict[key].decode("utf8")
            if ret_type is int:
                return int.from_bytes(self.client_hello_dict[key], "big")
        if isinstance(value, str):
            value = value.encode("utf8")
        elif isinstance(value, int):
            value = value.to_bytes(length=len(self.client_hello_dict[key]), byteorder="big")
        self.client_hello_dict[key] = value
        self.is_pkt_changed = True
    def gen_set_session_id(self):
        self.client_hello("session_id", _myrandom.getrandbytes(32))
    def fix_padding(self):
        self.client_hello("ext_padding", b"")
        padding_len = 517 - len(self.glue_pkt())
        self.client_hello("ext_padding_len", padding_len)
        self.client_hello("ext_padding", b"\x00" * padding_len)
    def glue_pkt(self) -> bytes:
        if self.is_pkt_changed:
            self.pkt = b"".join(self.client_hello_dict.values())
            self.is_pkt_changed = False
        return self.pkt
    def gen_set_key_share(self):
        self.client_hello("ext_key_share_exchange", _gen_x25519_public_key())
    def gen_set_random(self):
        self.client_hello("random", b"\x00" * 32)
        digest = _gen_sha256_digest(self.secret, self.glue_pkt())
        current_time = int(time.time()).to_bytes(length=4, byteorder="little")
        xored_time = bytes(current_time[i] ^ digest[28 + i] for i in range(4))
        digest = digest[:28] + xored_time
        self.client_hello("random", digest)
    def set_domain(self):
        domain_len = len(self.domain)
        self.client_hello("ext_server_name_len", 2 + 1 + 2 + domain_len)
        self.client_hello("ext_server_name_indication_list_len", 1 + 2 + domain_len)
        self.client_hello("ext_server_name_indication_len", domain_len)
        self.client_hello("ext_server_name_indication", self.domain)
    def build_new_client_hello_packet(self) -> bytes:
        self.gen_set_session_id()
        self.set_domain()
        self.gen_set_key_share()
        self.fix_padding()
        self.gen_set_random()
        return self.glue_pkt()
    def verify_server_hello(self, server_hello: bytes) -> bool:
        try:
            if len(server_hello) < 127 + 6:
                raise ValueError("invalid server hello size")
            if not server_hello.startswith(b"\x16\x03\x03"):
                raise ValueError("invalid tls packet 1")
            if server_hello[127:136] != b"\x14\x03\x03\x00\x01\x01\x17\x03\x03":
                raise ValueError("invalid tls packet 2")
            if server_hello[44:76] != self.client_hello_dict["session_id"]:
                raise ValueError("invalid tls session id")
            client_digest = self.client_hello_dict["random"]
            server_digest = server_hello[11:43]
            server_hello = server_hello[:11] + (b"\x00" * 32) + server_hello[43:]
            computed_digest = _gen_sha256_digest(self.secret, client_digest + server_hello)
            if server_digest != computed_digest:
                raise ValueError("invalid server digest")
            return True
        except Exception as exc:
            logger.debug("mtproto_faketls: verify_server_hello failed — %s", exc)
            return False
class _LayeredStreamReaderBase:
    __slots__ = ("upstream",)
    def __init__(self, upstream):
        self.upstream = upstream
    async def read(self, n):
        return await self.upstream.read(n)
    async def readexactly(self, n):
        return await self.upstream.readexactly(n)
class _LayeredStreamWriterBase:
    __slots__ = ("upstream",)
    def __init__(self, upstream):
        self.upstream = upstream
    def write(self, data, extra=None):
        return self.upstream.write(data)
    def write_eof(self):
        return self.upstream.write_eof()
    async def drain(self):
        return await self.upstream.drain()
    def close(self):
        return self.upstream.close()
    def abort(self):
        return self.upstream.transport.abort()
    def get_extra_info(self, name):
        return self.upstream.get_extra_info(name)
    @property
    def transport(self):
        return self.upstream.transport
class FakeTLSStreamReader(_LayeredStreamReaderBase):
    __slots__ = ("buf",)
    def __init__(self, upstream):
        self.upstream = upstream
        self.buf = bytearray()
    async def _read_one_tls_frame(self) -> bytes:
        while True:
            try:
                tls_rec_type = await self.upstream.readexactly(1)
            except asyncio.IncompleteReadError as exc:
                raise ConnectionError(
                    "FakeTLS: connection closed by proxy before TLS record header"
                ) from exc
            if tls_rec_type not in (b"\x14", b"\x17"):
                raise ConnectionError(
                    f"FakeTLS: unexpected TLS record type {tls_rec_type!r} "
                    "(proxy stream desynced)"
                )
            try:
                version = await self.upstream.readexactly(2)
                if version != b"\x03\x03":
                    raise ConnectionError(
                        f"FakeTLS: unexpected TLS version {version!r}"
                    )
                data_len_bytes = await self.upstream.readexactly(2)
                data_len = int.from_bytes(data_len_bytes, "big")
                if data_len <= 0 or data_len > 16384 + 256:
                    raise ConnectionError(
                        f"FakeTLS: bogus TLS record length {data_len}"
                    )
                data = await self.upstream.readexactly(data_len)
            except asyncio.IncompleteReadError as exc:
                raise ConnectionError(
                    "FakeTLS: connection closed mid-record"
                ) from exc
            if tls_rec_type == b"\x14":
                continue
            return data
    async def read(self, n, ignore_buf=False):
        if self.buf and not ignore_buf:
            data = bytes(self.buf[:n])
            del self.buf[:n]
            return data
        data = await self._read_one_tls_frame()
        if ignore_buf:
            return data
        if len(data) > n:
            self.buf += data[n:]
            data = data[:n]
        return data
    async def readexactly(self, n):
        if n is None or n < 0:
            raise ConnectionError(f"FakeTLS: invalid readexactly size {n!r}")
        if n == 0:
            return b""
        while len(self.buf) < n:
            tls_data = await self._read_one_tls_frame()
            if not tls_data:
                raise ConnectionError("FakeTLS: empty TLS record from proxy")
            self.buf += tls_data
        data = bytes(self.buf[:n])
        del self.buf[:n]
        return data
    async def read_server_hello(self) -> bytes:
        try:
            server_hello = await self.upstream.readexactly(127 + 6 + 3 + 2)
            http_data_len = int.from_bytes(server_hello[-2:], "big")
            return server_hello + await self.upstream.readexactly(http_data_len)
        except asyncio.IncompleteReadError as exc:
            raise ConnectionError(
                "FakeTLS: proxy closed connection during ServerHello"
            ) from exc
class FakeTLSStreamWriter(_LayeredStreamWriterBase):
    __slots__ = ()
    def __init__(self, upstream):
        self.upstream = upstream
    def write(self, data, extra=None):
        max_chunk_size = 16384 + 24
        for start in range(0, len(data), max_chunk_size):
            end = min(start + max_chunk_size, len(data))
            self.upstream.write(b"\x17\x03\x03" + int.to_bytes(end - start, 2, "big"))
            self.upstream.write(data[start:end])
        return len(data)
class ConnectionTcpMTProxyFakeTLS(ConnectionTcpMTProxyRandomizedIntermediate):
    def __init__(self, ip, port, dc_id, *, loggers, proxy=None, local_addr=None):
        if proxy is None or len(proxy) < 3:
            raise ValueError("No proxy info specified for MTProto FakeTLS connection")
        self.fake_tls_cdc = MTProxyFakeTLSClientCodec(str(proxy[2]))
        proxy_host = proxy[0]
        if len(proxy_host) > 60:
            proxy_host = socket.gethostbyname(proxy[0])
        proxy = (proxy_host, proxy[1], self.fake_tls_cdc.secret.hex())
        super().__init__(ip, port, dc_id, loggers=loggers, proxy=proxy, local_addr=local_addr)
    async def _connect(self, timeout=None, ssl=None):
        if self._local_addr is not None:
            if isinstance(self._local_addr, tuple) and len(self._local_addr) == 2:
                local_addr = self._local_addr
            elif isinstance(self._local_addr, str):
                local_addr = (self._local_addr, 0)
            else:
                raise ValueError(f"Unknown local address format: {self._local_addr}")
        else:
            local_addr = None
        if not self._proxy:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(
                    host=self._ip,
                    port=self._port,
                    ssl=ssl,
                    local_addr=local_addr,
                ),
                timeout=timeout,
            )
        else:
            sock = await self._proxy_connect(timeout=timeout, local_addr=local_addr)
            if ssl:
                sock = self._wrap_socket_ssl(sock)
            self._reader, self._writer = await asyncio.open_connection(sock=sock)
        logger.info("mtproto_faketls: sending FakeTLS headers")
        self._writer.write(self.fake_tls_cdc.build_new_client_hello_packet())
        await self._writer.drain()
        logger.info("mtproto_faketls: FakeTLS headers sent")
        raw_reader = self._reader
        logger.info("mtproto_faketls: waiting for FakeTLS server hello")
        wrapped_reader = FakeTLSStreamReader(raw_reader)
        if not self.fake_tls_cdc.verify_server_hello(
            await wrapped_reader.read_server_hello()
        ):
            logger.error("mtproto_faketls: FakeTLS server hello verification failed")
            raise ConnectionError("FakeTLS server hello verification failed")
        logger.info("mtproto_faketls: FakeTLS handshake completed")
        self._writer = FakeTLSStreamWriter(self._writer)
        self._reader = wrapped_reader
        self._codec = self.packet_codec(self)
        self._init_conn()
        await self._writer.drain()
