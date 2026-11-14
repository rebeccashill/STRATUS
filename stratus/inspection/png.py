"""Small deterministic RGB PNG codec for authored fixtures; standard library only."""

import binascii
import struct
import zlib
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_FILE_BYTES = 8 * 1024 * 1024


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(
        ">I", binascii.crc32(kind + data) & 0xFFFFFFFF
    )


def encode_rgb(width: int, height: int, pixels: bytes, label: str) -> bytes:
    if len(pixels) != width * height * 3:
        raise ValueError("RGB buffer size does not match dimensions")
    stride = width * 3
    scanlines = b"".join(
        b"\x00" + pixels[y * stride : (y + 1) * stride] for y in range(height)
    )
    return (
        SIGNATURE
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"tEXt", b"Source\x00" + label.encode("ascii"))
        + _chunk(b"IDAT", zlib.compress(scanlines, 9))
        + _chunk(b"IEND", b"")
    )


def validate_png(path: Path) -> tuple[bytes, int, int]:
    """Check the complete PNG, CRCs, and decompressed scanlines, not just its suffix.

    The local fixture format is deliberately bounded to noninterlaced 8-bit RGB
    with filter 0. Other PNG formats require an explicit future decoder change.
    """
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("image exceeds the 8 MiB fixture limit")
    data = path.read_bytes()
    if not data.startswith(SIGNATURE):
        raise ValueError("image is not a PNG")
    offset, compressed, kinds = 8, bytearray(), []
    width = height = 0
    ended = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("truncated PNG chunk")
        size = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        end = offset + 8 + size
        if end + 4 > len(data):
            raise ValueError("truncated PNG data")
        payload = data[offset + 8 : end]
        crc = struct.unpack_from(">I", data, end)[0]
        if binascii.crc32(kind + payload) & 0xFFFFFFFF != crc:
            raise ValueError("PNG checksum mismatch")
        if not kinds and kind != b"IHDR":
            raise ValueError("PNG must begin with IHDR")
        if kind == b"IHDR":
            if kinds or size != 13:
                raise ValueError("invalid PNG header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if not (1 <= width <= 2048 and 1 <= height <= 2048):
                raise ValueError("PNG dimensions outside fixture limits")
            if (depth, color, compression, filtering, interlace) != (8, 2, 0, 0, 0):
                raise ValueError("fixture requires noninterlaced 8-bit RGB PNG")
        elif kind == b"IDAT":
            if b"IDAT" in kinds and kinds[-1] != b"IDAT":
                raise ValueError("PNG IDAT chunks must be consecutive")
            compressed.extend(payload)
        elif kind == b"IEND":
            if size or end + 4 != len(data):
                raise ValueError("invalid PNG end or trailing data")
            ended = True
        elif kind[:1].isupper():
            raise ValueError("unsupported critical PNG chunk")
        kinds.append(kind)
        offset = end + 4
    if not ended or not compressed:
        raise ValueError("PNG is incomplete")
    expected = height * (1 + width * 3)
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(bytes(compressed), expected + 1)
    except zlib.error as exc:
        raise ValueError("invalid PNG compressed pixels") from exc
    if len(raw) != expected or not decoder.eof or decoder.unused_data:
        raise ValueError("PNG pixel data has an invalid length or stream")
    if any(raw[row * (1 + width * 3)] != 0 for row in range(height)):
        raise ValueError("unsupported fixture PNG scanline filter")
    return data, width, height
