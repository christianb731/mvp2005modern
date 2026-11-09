#!/usr/bin/env python3
"""Inspect/extract EA SHPI/FSH textures used by MVP Baseball 2005.

Supports raw SHPI files and EA RefPack-compressed FSH files. Runtime IDs are
computed from mip level 0 only, matching MVP2005 Modern v0.54.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from dataclasses import dataclass, asdict
from pathlib import Path

FORMAT_INFO = {
    0x60: ("DXT1", 0x31545844),
    0x61: ("DXT3", 0x33545844),
    0x62: ("DXT5", 0x35545844),
    0x6D: ("A4R4G4B4", 26),
    0x78: ("R5G6B5", 23),
    0x7B: ("P8", 41),
    0x7D: ("A8R8G8B8", 21),
    0x7E: ("A1R5G5B5", 25),
    0x7F: ("R8G8B8", 20),
}
DDSD_CAPS = 0x1
DDSD_HEIGHT = 0x2
DDSD_WIDTH = 0x4
DDSD_PITCH = 0x8
DDSD_PIXELFORMAT = 0x1000
DDSD_MIPMAPCOUNT = 0x20000
DDSD_LINEARSIZE = 0x80000
DDSCAPS_COMPLEX = 0x8
DDSCAPS_TEXTURE = 0x1000
DDSCAPS_MIPMAP = 0x400000
DDPF_ALPHAPIXELS = 0x1
DDPF_FOURCC = 0x4
DDPF_RGB = 0x40


class FshError(ValueError):
    pass


def u24le(data: bytes, off: int) -> int:
    return data[off] | (data[off + 1] << 8) | (data[off + 2] << 16)


def u24be(data: bytes, off: int) -> int:
    return (data[off] << 16) | (data[off + 1] << 8) | data[off + 2]


def clean_ascii(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", errors="replace")


def is_refpack(data: bytes) -> bool:
    return len(data) >= 2 and data[0] in (0x10, 0x50) and data[1] == 0xFB


def refpack_decompress(data: bytes) -> bytes:
    if not is_refpack(data):
        return data
    src = 2
    flags = data[0]
    if flags & 0x80:
        if len(data) < 6:
            raise FshError("truncated RefPack header")
        target = struct.unpack_from(">I", data, src)[0]
        src += 4
    else:
        if len(data) < 5:
            raise FshError("truncated RefPack header")
        target = u24be(data, src)
        src += 3

    out = bytearray()
    while src < len(data):
        code = data[src]
        if code <= 0x7F:
            if src + 1 >= len(data):
                raise FshError("truncated RefPack short command")
            b1 = data[src + 1]
            literals = code & 0x03
            copy_len = ((code & 0x1C) >> 2) + 3
            copy_off = ((code & 0x60) << 3) + b1 + 1
            src += 2
        elif code <= 0xBF:
            if src + 2 >= len(data):
                raise FshError("truncated RefPack medium command")
            b1, b2 = data[src + 1], data[src + 2]
            literals = (b1 >> 6) & 0x03
            copy_len = (code & 0x3F) + 4
            copy_off = ((b1 & 0x3F) << 8) + b2 + 1
            src += 3
        elif code <= 0xDF:
            if src + 3 >= len(data):
                raise FshError("truncated RefPack long command")
            b1, b2, b3 = data[src + 1], data[src + 2], data[src + 3]
            literals = code & 0x03
            copy_len = ((code & 0x0C) << 6) + b3 + 5
            copy_off = ((code & 0x10) << 12) + (b1 << 8) + b2 + 1
            src += 4
        elif code <= 0xFB:
            literals = ((code & 0x1F) << 2) + 4
            src += 1
            if src + literals > len(data):
                raise FshError("truncated RefPack literal command")
            out.extend(data[src:src + literals])
            src += literals
            if len(out) > target:
                raise FshError("RefPack output exceeded declared size")
            continue
        else:
            literals = code & 0x03
            src += 1
            if src + literals > len(data):
                raise FshError("truncated RefPack stop command")
            out.extend(data[src:src + literals])
            break

        if src + literals > len(data):
            raise FshError("truncated RefPack command literals")
        out.extend(data[src:src + literals])
        src += literals
        copy_src = len(out) - copy_off
        if copy_src < 0:
            raise FshError("invalid RefPack back-reference")
        for i in range(copy_len):
            out.append(out[copy_src + i])
        if len(out) > target:
            raise FshError("RefPack output exceeded declared size")

    if len(out) < target:
        raise FshError(f"RefPack output short: {len(out)} != {target}")
    return bytes(out[:target])


def level_size(code: int, width: int, height: int) -> int | None:
    if width < 1 or height < 1:
        return None
    if code == 0x60:
        return max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 8
    if code in (0x61, 0x62):
        return max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 16
    bpp = {0x6D: 2, 0x78: 2, 0x7B: 1, 0x7D: 4, 0x7E: 2, 0x7F: 3}.get(code)
    return width * height * bpp if bpp else None


def infer_mips(code: int, width: int, height: int, total: int) -> int | None:
    size = 0
    for level in range(16):
        item = level_size(code, max(1, width >> level), max(1, height >> level))
        if item is None:
            return None
        size += item
        if size == total:
            return level + 1
        if size > total:
            return None
    return None


def fnv1a64_v054(width: int, height: int, d3d_format: int, payload: bytes) -> int:
    value = 14695981039346656037
    prime = 1099511628211
    mask = 0xFFFFFFFFFFFFFFFF
    for item in (width, height, d3d_format):
        for shift in (0, 8, 16, 24):
            value = ((value ^ ((item >> shift) & 0xFF)) * prime) & mask
    for byte in payload:
        value = ((value ^ byte) * prime) & mask
    return value


@dataclass
class Attachment:
    offset: int
    code: int
    length: int
    kind: str
    text: str | None = None


@dataclass
class FshEntry:
    name: str
    offset: int
    raw_code: int
    code: int
    record_length: int
    width: int
    height: int
    center_x: int
    center_y: int
    x: int
    y: int
    format_name: str
    d3d_format: int | None
    payload_offset: int
    payload_size: int
    level0_size: int | None
    mip_levels: int | None
    level0_sha256: str | None
    record_sha256: str
    runtime_id_v054: str | None
    attachments: list[Attachment]


@dataclass
class FshFile:
    path: str
    was_refpack: bool
    declared_size: int
    entry_count: int
    directory_id: str
    extra_data_hex: str
    entries: list[FshEntry]
    data: bytes


def parse_attachments(data: bytes, start: int, end: int) -> list[Attachment]:
    out: list[Attachment] = []
    pos = start
    while pos + 4 <= end:
        if not any(data[pos:end]):
            break
        raw_code = data[pos]
        code = raw_code & 0x7F
        length = u24le(data, pos + 1)
        if code == 0x70:
            size = min(16, end - pos)
            out.append(Attachment(pos, raw_code, size, "eTXT-short", clean_ascii(data[pos + 4:pos + size])))
            pos += size
            continue
        if length < 4 or pos + length > end:
            out.append(Attachment(pos, raw_code, max(0, end - pos), "unknown-tail"))
            break
        kind = f"record-0x{code:02X}"
        text = None
        if code == 0x69:
            kind = "eTXT"
            text = clean_ascii(data[pos + 16:pos + length]) if length >= 16 else None
        elif code == 0x6F:
            kind = "text"
            text = clean_ascii(data[pos + 4:pos + length])
        elif code == 0x7C:
            kind = "pixel-region/hotspot"
        out.append(Attachment(pos, raw_code, length, kind, text))
        pos += length
    return out


def parse_fsh(path: Path) -> FshFile:
    source = path.read_bytes()
    was_refpack = is_refpack(source)
    data = refpack_decompress(source)
    if len(data) < 16 or data[:4] != b"SHPI":
        raise FshError("not an SHPI/FSH file after optional RefPack decompression")
    declared_size, count = struct.unpack_from("<II", data, 4)
    group = data[12:16].decode("ascii", errors="replace")
    if declared_size != len(data):
        raise FshError(f"SHPI size mismatch: header={declared_size} actual={len(data)}")
    if 16 + count * 8 > len(data):
        raise FshError("directory extends past file")

    directory: list[tuple[str, int]] = []
    for i in range(count):
        base = 16 + i * 8
        name = clean_ascii(data[base:base + 4])
        off = struct.unpack_from("<I", data, base + 4)[0]
        if off + 16 > len(data):
            raise FshError(f"entry {name!r} outside file")
        directory.append((name, off))

    offsets = sorted({off for _, off in directory})
    boundary = {off: offsets[i + 1] if i + 1 < len(offsets) else len(data) for i, off in enumerate(offsets)}
    extra_start = 16 + count * 8
    first = min(offsets, default=extra_start)
    entries: list[FshEntry] = []

    for name, off in directory:
        raw_code = data[off]
        code = raw_code & 0x7F
        record_len = u24le(data, off + 1)
        width, height, cx, cy, xpos, ypos = struct.unpack_from("<HHHHHH", data, off + 4)
        record_end = off + record_len
        if record_len < 16 or record_end > boundary[off] or record_end > len(data):
            raise FshError(f"entry {name!r} has invalid record length")
        payload = data[off + 16:record_end]
        fmt_name, d3d_format = FORMAT_INFO.get(code, (f"UNKNOWN_0x{code:02X}", None))
        level0 = level_size(code, width, height)
        base_payload = payload[:level0] if level0 is not None and level0 <= len(payload) else None
        runtime_id = None
        if base_payload is not None and d3d_format is not None and code != 0x7B:
            runtime_id = f"{width}x{height}_{fmt_name}_{fnv1a64_v054(width, height, d3d_format, base_payload):016x}"
        entries.append(FshEntry(
            name=name,
            offset=off,
            raw_code=raw_code,
            code=code,
            record_length=record_len,
            width=width,
            height=height,
            center_x=cx,
            center_y=cy,
            x=xpos,
            y=ypos,
            format_name=fmt_name,
            d3d_format=d3d_format,
            payload_offset=off + 16,
            payload_size=len(payload),
            level0_size=level0,
            mip_levels=infer_mips(code, width, height, len(payload)),
            level0_sha256=hashlib.sha256(base_payload).hexdigest() if base_payload is not None else None,
            record_sha256=hashlib.sha256(payload).hexdigest(),
            runtime_id_v054=runtime_id,
            attachments=parse_attachments(data, record_end, boundary[off]),
        ))

    return FshFile(str(path), was_refpack, declared_size, count, group, data[extra_start:first].hex(), entries, data)


def dds_pixel_format(code: int):
    if code in (0x60, 0x61, 0x62):
        return (DDPF_FOURCC, {0x60: b"DXT1", 0x61: b"DXT3", 0x62: b"DXT5"}[code], 0, 0, 0, 0, 0)
    if code == 0x7D:
        return (DDPF_RGB | DDPF_ALPHAPIXELS, b"\0" * 4, 32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    if code == 0x7F:
        return (DDPF_RGB, b"\0" * 4, 24, 0x00FF0000, 0x0000FF00, 0x000000FF, 0)
    if code == 0x78:
        return (DDPF_RGB, b"\0" * 4, 16, 0xF800, 0x07E0, 0x001F, 0)
    if code == 0x7E:
        return (DDPF_RGB | DDPF_ALPHAPIXELS, b"\0" * 4, 16, 0x7C00, 0x03E0, 0x001F, 0x8000)
    if code == 0x6D:
        return (DDPF_RGB | DDPF_ALPHAPIXELS, b"\0" * 4, 16, 0x0F00, 0x00F0, 0x000F, 0xF000)
    return None


def write_dds(path: Path, entry: FshEntry, payload: bytes) -> None:
    pixel_format = dds_pixel_format(entry.code)
    if pixel_format is None:
        raise FshError(f"DDS export unsupported for {entry.format_name}")
    mip_count = entry.mip_levels or 1
    body = payload if entry.mip_levels else payload[:entry.level0_size]
    pf_flags, fourcc_bytes, bits, rmask, gmask, bmask, amask = pixel_format
    is_dxt = entry.code in (0x60, 0x61, 0x62)
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    flags |= DDSD_LINEARSIZE if is_dxt else DDSD_PITCH
    if mip_count > 1:
        flags |= DDSD_MIPMAPCOUNT
    base_size = entry.level0_size or len(body)
    pitch_or_linear = base_size if is_dxt else (entry.width * bits + 7) // 8

    header = bytearray(128)
    header[:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<I", header, 8, flags)
    struct.pack_into("<I", header, 12, entry.height)
    struct.pack_into("<I", header, 16, entry.width)
    struct.pack_into("<I", header, 20, pitch_or_linear)
    struct.pack_into("<I", header, 28, mip_count)
    struct.pack_into("<I", header, 76, 32)
    struct.pack_into("<I", header, 80, pf_flags)
    header[84:88] = fourcc_bytes
    struct.pack_into("<I", header, 88, bits)
    struct.pack_into("<I", header, 92, rmask)
    struct.pack_into("<I", header, 96, gmask)
    struct.pack_into("<I", header, 100, bmask)
    struct.pack_into("<I", header, 104, amask)
    caps = DDSCAPS_TEXTURE | ((DDSCAPS_COMPLEX | DDSCAPS_MIPMAP) if mip_count > 1 else 0)
    struct.pack_into("<I", header, 108, caps)
    path.write_bytes(bytes(header) + body)


def decode_rgba(entry: FshEntry, base: bytes) -> bytes | None:
    out = bytearray(entry.width * entry.height * 4)
    count = entry.width * entry.height
    if entry.code == 0x7D:
        if len(base) < count * 4:
            return None
        for i in range(count):
            blue, green, red, alpha = base[i * 4:i * 4 + 4]
            out[i * 4:i * 4 + 4] = bytes((red, green, blue, alpha))
        return bytes(out)
    if entry.code == 0x7F:
        if len(base) < count * 3:
            return None
        for i in range(count):
            blue, green, red = base[i * 3:i * 3 + 3]
            out[i * 4:i * 4 + 4] = bytes((red, green, blue, 255))
        return bytes(out)
    if entry.code in (0x78, 0x7E, 0x6D):
        if len(base) < count * 2:
            return None
        for i in range(count):
            value = struct.unpack_from("<H", base, i * 2)[0]
            if entry.code == 0x78:
                red = ((value >> 11) & 31) * 255 // 31
                green = ((value >> 5) & 63) * 255 // 63
                blue = (value & 31) * 255 // 31
                alpha = 255
            elif entry.code == 0x7E:
                alpha = 255 if value & 0x8000 else 0
                red = ((value >> 10) & 31) * 255 // 31
                green = ((value >> 5) & 31) * 255 // 31
                blue = (value & 31) * 255 // 31
            else:
                alpha = ((value >> 12) & 15) * 17
                red = ((value >> 8) & 15) * 17
                green = ((value >> 4) & 15) * 17
                blue = (value & 15) * 17
            out[i * 4:i * 4 + 4] = bytes((red, green, blue, alpha))
        return bytes(out)
    return None


def write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fsh", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--extract", type=Path)
    parser.add_argument("--png", action="store_true")
    parser.add_argument("--replacement-names", action="store_true", help="name DDS/PNG outputs with v0.54 IDs")
    args = parser.parse_args()

    fsh = parse_fsh(args.fsh)
    if args.json:
        value = asdict(fsh)
        value.pop("data")
        print(json.dumps(value, indent=2))
        return 0

    print(f"{args.fsh}: SHPI size={fsh.declared_size} entries={fsh.entry_count} group={fsh.directory_id} refpack={fsh.was_refpack}")
    for entry in fsh.entries:
        print(
            f"  {entry.name!r}: {entry.width}x{entry.height} {entry.format_name} "
            f"mips={entry.mip_levels or '?'} level0={entry.level0_size} "
            f"record_payload={entry.payload_size} id={entry.runtime_id_v054 or '-'}"
        )

    if args.extract:
        args.extract.mkdir(parents=True, exist_ok=True)
        for entry in fsh.entries:
            payload = fsh.data[entry.payload_offset:entry.payload_offset + entry.payload_size]
            stem = entry.runtime_id_v054 if args.replacement_names and entry.runtime_id_v054 else entry.name
            if dds_pixel_format(entry.code):
                write_dds(args.extract / (stem + ".dds"), entry, payload)
            if args.png and entry.level0_size:
                rgba = decode_rgba(entry, payload[:entry.level0_size])
                if rgba is not None:
                    write_png(args.extract / (stem + ".png"), entry.width, entry.height, rgba)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
