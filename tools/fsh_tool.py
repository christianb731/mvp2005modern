#!/usr/bin/env python3
"""Inspect and extract EA SHPI/FSH texture containers used by MVP Baseball 2005.

Pure Python stdlib. The extractor preserves compressed DXT payloads when writing
DDS files, so it does not require a DXT codec.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

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
DDSD_LINEARSIZE = 0x80000
DDSCAPS_TEXTURE = 0x1000
DDPF_ALPHAPIXELS = 0x1
DDPF_FOURCC = 0x4
DDPF_RGB = 0x40


class FshError(ValueError):
    pass


def u24le(data: bytes, off: int) -> int:
    if off + 3 > len(data):
        raise FshError("truncated 24-bit integer")
    return data[off] | (data[off + 1] << 8) | (data[off + 2] << 16)


def clean_ascii(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", errors="replace")


def fnv1a64_v054(width: int, height: int, d3d_format: int, payload: bytes) -> int:
    """Match MVP2005 Modern v0.54's content-addressed texture fingerprint."""
    h = 14695981039346656037
    prime = 1099511628211
    mask = 0xFFFFFFFFFFFFFFFF
    for value in (width, height, d3d_format):
        for shift in (0, 8, 16, 24):
            h ^= (value >> shift) & 0xFF
            h = (h * prime) & mask
    for b in payload:
        h ^= b
        h = (h * prime) & mask
    return h


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
    sha256: str
    runtime_id_v054: str | None
    attachments: list[Attachment]


@dataclass
class FshFile:
    path: Path
    declared_size: int
    entry_count: int
    directory_id: str
    extra_data: bytes
    entries: list[FshEntry]
    data: bytes


def parse_attachments(data: bytes, start: int, end: int) -> list[Attachment]:
    items: list[Attachment] = []
    pos = start
    while pos + 4 <= end:
        if not any(data[pos:end]):
            break
        raw_code = data[pos]
        code = raw_code & 0x7F
        length = u24le(data, pos + 1)

        if code == 0x70:
            rec_len = min(16, end - pos)
            text = clean_ascii(data[pos + 4:pos + rec_len])
            items.append(Attachment(pos, raw_code, rec_len, "eTXT-short", text))
            pos += rec_len
            continue

        if length < 4 or pos + length > end:
            items.append(Attachment(pos, raw_code, max(0, end - pos), "unknown-tail", None))
            break

        text = None
        kind = f"record-0x{code:02X}"
        if code == 0x69:
            kind = "eTXT"
            if length >= 16:
                text = clean_ascii(data[pos + 16:pos + length])
        elif code == 0x6F:
            kind = "text"
            text = clean_ascii(data[pos + 4:pos + length])
        elif code == 0x7C:
            kind = "pixel-region/hotspot"
        items.append(Attachment(pos, raw_code, length, kind, text))
        pos += length
    return items


def parse_fsh(path: Path) -> FshFile:
    data = path.read_bytes()
    if len(data) < 16 or data[:4] != b"SHPI":
        raise FshError("not an SHPI/FSH file")

    declared_size, count = struct.unpack_from("<II", data, 4)
    directory_id = data[12:16].decode("ascii", errors="replace")
    if 16 + count * 8 > len(data):
        raise FshError("directory extends past end of file")

    directory: list[tuple[str, int]] = []
    for i in range(count):
        base = 16 + i * 8
        name = clean_ascii(data[base:base + 4])
        off = struct.unpack_from("<I", data, base + 4)[0]
        if off + 16 > len(data):
            raise FshError(f"entry {name!r} points outside file: 0x{off:X}")
        directory.append((name, off))

    first_off = min((off for _, off in directory), default=16 + count * 8)
    extra_start = 16 + count * 8
    extra_data = data[extra_start:first_off]

    next_boundary: dict[int, int] = {}
    offsets = sorted({off for _, off in directory})
    for idx, off in enumerate(offsets):
        next_boundary[off] = offsets[idx + 1] if idx + 1 < len(offsets) else len(data)

    entries: list[FshEntry] = []
    for name, off in directory:
        raw_code = data[off]
        code = raw_code & 0x7F
        record_length = u24le(data, off + 1)
        width, height, cx, cy, xpos, ypos = struct.unpack_from("<HHHHHH", data, off + 4)
        if record_length < 16:
            raise FshError(f"entry {name!r} has invalid record length {record_length}")
        record_end = off + record_length
        boundary = next_boundary[off]
        if record_end > boundary or record_end > len(data):
            raise FshError(f"entry {name!r} record extends past its boundary")
        payload = data[off + 16:record_end]
        fmt_name, d3d_fmt = FORMAT_INFO.get(code, (f"UNKNOWN_0x{code:02X}", None))
        runtime_id = None
        if d3d_fmt is not None and code != 0x7B:
            fp = fnv1a64_v054(width, height, d3d_fmt, payload)
            runtime_id = f"{width}x{height}_{fmt_name}_{fp:016x}"
        attachments = parse_attachments(data, record_end, boundary)
        entries.append(FshEntry(
            name=name,
            offset=off,
            raw_code=raw_code,
            code=code,
            record_length=record_length,
            width=width,
            height=height,
            center_x=cx,
            center_y=cy,
            x=xpos,
            y=ypos,
            format_name=fmt_name,
            d3d_format=d3d_fmt,
            payload_offset=off + 16,
            payload_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            runtime_id_v054=runtime_id,
            attachments=attachments,
        ))

    return FshFile(path, declared_size, count, directory_id, extra_data, entries, data)


def dds_pixel_format(code: int):
    if code == 0x60:
        return (DDPF_FOURCC, b"DXT1", 0, 0, 0, 0, 0)
    if code == 0x61:
        return (DDPF_FOURCC, b"DXT3", 0, 0, 0, 0, 0)
    if code == 0x62:
        return (DDPF_FOURCC, b"DXT5", 0, 0, 0, 0, 0)
    if code == 0x7D:
        return (DDPF_RGB | DDPF_ALPHAPIXELS, b"\0\0\0\0", 32,
                0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    if code == 0x7F:
        return (DDPF_RGB, b"\0\0\0\0", 24,
                0x00FF0000, 0x0000FF00, 0x000000FF, 0)
    if code == 0x78:
        return (DDPF_RGB, b"\0\0\0\0", 16,
                0xF800, 0x07E0, 0x001F, 0)
    if code == 0x7E:
        return (DDPF_RGB | DDPF_ALPHAPIXELS, b"\0\0\0\0", 16,
                0x7C00, 0x03E0, 0x001F, 0x8000)
    if code == 0x6D:
        return (DDPF_RGB | DDPF_ALPHAPIXELS, b"\0\0\0\0", 16,
                0x0F00, 0x00F0, 0x000F, 0xF000)
    return None


def write_dds(path: Path, entry: FshEntry, payload: bytes) -> None:
    pf = dds_pixel_format(entry.code)
    if pf is None:
        raise FshError(f"DDS export not supported for {entry.format_name}")
    pf_flags, fourcc_bytes, rgb_bits, rmask, gmask, bmask, amask = pf
    is_dxt = entry.code in (0x60, 0x61, 0x62)
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    if is_dxt:
        flags |= DDSD_LINEARSIZE
        pitch_or_linear = len(payload)
    else:
        flags |= DDSD_PITCH
        pitch_or_linear = (entry.width * rgb_bits + 7) // 8

    fourcc = struct.unpack("<I", fourcc_bytes)[0]
    header = bytearray(128)
    header[:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<I", header, 8, flags)
    struct.pack_into("<I", header, 12, entry.height)
    struct.pack_into("<I", header, 16, entry.width)
    struct.pack_into("<I", header, 20, pitch_or_linear)
    struct.pack_into("<I", header, 24, 0)
    struct.pack_into("<I", header, 28, 1)
    struct.pack_into("<I", header, 76, 32)
    struct.pack_into("<I", header, 80, pf_flags)
    struct.pack_into("<I", header, 84, fourcc)
    struct.pack_into("<I", header, 88, rgb_bits)
    struct.pack_into("<I", header, 92, rmask)
    struct.pack_into("<I", header, 96, gmask)
    struct.pack_into("<I", header, 100, bmask)
    struct.pack_into("<I", header, 104, amask)
    struct.pack_into("<I", header, 108, DDSCAPS_TEXTURE)
    path.write_bytes(bytes(header) + payload)


def decode_to_rgba(entry: FshEntry, payload: bytes) -> bytes | None:
    out = bytearray(entry.width * entry.height * 4)
    if entry.code == 0x7D:
        if len(payload) < entry.width * entry.height * 4:
            return None
        for i in range(entry.width * entry.height):
            b, g, r, a = payload[i * 4:i * 4 + 4]
            out[i * 4:i * 4 + 4] = bytes((r, g, b, a))
        return bytes(out)
    if entry.code == 0x7F:
        if len(payload) < entry.width * entry.height * 3:
            return None
        for i in range(entry.width * entry.height):
            b, g, r = payload[i * 3:i * 3 + 3]
            out[i * 4:i * 4 + 4] = bytes((r, g, b, 255))
        return bytes(out)
    if entry.code in (0x78, 0x7E, 0x6D):
        if len(payload) < entry.width * entry.height * 2:
            return None
        for i in range(entry.width * entry.height):
            value = struct.unpack_from("<H", payload, i * 2)[0]
            if entry.code == 0x78:
                r = ((value >> 11) & 31) * 255 // 31
                g = ((value >> 5) & 63) * 255 // 63
                b = (value & 31) * 255 // 31
                a = 255
            elif entry.code == 0x7E:
                a = 255 if (value & 0x8000) else 0
                r = ((value >> 10) & 31) * 255 // 31
                g = ((value >> 5) & 31) * 255 // 31
                b = (value & 31) * 255 // 31
            else:
                a = ((value >> 12) & 15) * 17
                r = ((value >> 8) & 15) * 17
                g = ((value >> 4) & 15) * 17
                b = (value & 15) * 17
            out[i * 4:i * 4 + 4] = bytes((r, g, b, a))
        return bytes(out)
    return None


def write_png_rgba(path: Path, width: int, height: int, rgba: bytes) -> None:
    if len(rgba) != width * height * 4:
        raise FshError("RGBA buffer size mismatch")
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(
            ">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def entry_payload(fsh: FshFile, entry: FshEntry) -> bytes:
    return fsh.data[entry.payload_offset:entry.payload_offset + entry.payload_size]


def print_info(fsh: FshFile) -> None:
    actual = len(fsh.data)
    print(f"File: {fsh.path}")
    print("Magic: SHPI")
    print(f"Declared size: {fsh.declared_size} (actual {actual})")
    print(f"Entries: {fsh.entry_count}")
    print(f"Directory ID: {fsh.directory_id!r}")
    if fsh.extra_data:
        print(f"Extra data: {len(fsh.extra_data)} bytes {fsh.extra_data!r}")
    for idx, entry in enumerate(fsh.entries):
        print()
        print(f"[{idx}] {entry.name!r} @ 0x{entry.offset:X}")
        print(f"  code: 0x{entry.raw_code:02X} (base 0x{entry.code:02X})")
        print(f"  format: {entry.format_name}")
        print(f"  size: {entry.width}x{entry.height}")
        print(f"  record length: {entry.record_length}; payload: {entry.payload_size} bytes")
        print(f"  center: {entry.center_x},{entry.center_y}; position: {entry.x},{entry.y}")
        print(f"  payload sha256: {entry.sha256}")
        if entry.runtime_id_v054:
            print(f"  MVP2005 Modern v0.54 ID: {entry.runtime_id_v054}")
            print(f"  replacement filename: {entry.runtime_id_v054}.dds")
        if entry.attachments:
            print("  attachments:")
            for attachment in entry.attachments:
                desc = (
                    f"    - 0x{attachment.offset:X}: {attachment.kind} "
                    f"code=0x{attachment.code:02X} length={attachment.length}"
                )
                if attachment.text:
                    desc += f" text={attachment.text!r}"
                print(desc)


def json_info(fsh: FshFile) -> dict:
    return {
        "path": str(fsh.path),
        "magic": "SHPI",
        "declared_size": fsh.declared_size,
        "actual_size": len(fsh.data),
        "entry_count": fsh.entry_count,
        "directory_id": fsh.directory_id,
        "extra_data_hex": fsh.extra_data.hex(),
        "extra_data_ascii": clean_ascii(fsh.extra_data),
        "entries": [asdict(entry) for entry in fsh.entries],
    }


def extract(fsh: FshFile, out_dir: Path, png: bool, dds: bool, raw: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx, entry in enumerate(fsh.entries):
        payload = entry_payload(fsh, entry)
        stem = f"{idx:03d}_{entry.name}_{entry.width}x{entry.height}_{entry.format_name}"
        if dds and dds_pixel_format(entry.code) is not None:
            target = out_dir / f"{stem}.dds"
            write_dds(target, entry, payload)
            print(f"DDS: {target}")
            if entry.runtime_id_v054:
                runtime_target = out_dir / f"{entry.runtime_id_v054}.dds"
                if runtime_target != target:
                    write_dds(runtime_target, entry, payload)
                    print(f"DDS (runtime name): {runtime_target}")
        if png:
            rgba = decode_to_rgba(entry, payload)
            if rgba is not None:
                target = out_dir / f"{stem}.png"
                write_png_rgba(target, entry.width, entry.height, rgba)
                print(f"PNG: {target}")
        if raw:
            target = out_dir / f"{stem}.bin"
            target.write_bytes(payload)
            print(f"RAW: {target}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect/extract EA SHPI/FSH texture files")
    parser.add_argument("file", type=Path)
    parser.add_argument("--json", action="store_true", help="print metadata as JSON")
    parser.add_argument("--extract", type=Path, metavar="DIR", help="extract entries")
    parser.add_argument("--no-dds", action="store_true", help="skip DDS output")
    parser.add_argument("--png", action="store_true", help="also emit PNG for uncompressed formats")
    parser.add_argument("--raw", action="store_true", help="also emit raw payload bytes")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        fsh = parse_fsh(args.file)
        if args.json:
            print(json.dumps(json_info(fsh), indent=2))
        else:
            print_info(fsh)
        if args.extract:
            extract(fsh, args.extract, args.png, not args.no_dds, args.raw)
        return 0
    except (OSError, FshError, struct.error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
