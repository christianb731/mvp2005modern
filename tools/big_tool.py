#!/usr/bin/env python3
"""Inspect/extract EA BIGF archives used by MVP Baseball 2005.

Understands BIGF directory records, EA RefPack (0x10FB/0x50FB) members,
and SHPI/FSH texture entries. Texture indexing uses only mip level 0 so the
reported content ID matches MVP2005 Modern v0.54 runtime fingerprinting.
"""
from __future__ import annotations

import argparse
import json
import struct
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


class BigError(ValueError):
    pass


@dataclass
class BigEntry:
    name: str
    offset: int
    size: int
    refpack: bool
    decompressed_size: int | None


@dataclass
class TextureEntry:
    archive_member: str
    fsh_group: str
    name: str
    format: str
    width: int
    height: int
    record_payload_size: int
    level0_size: int | None
    inferred_mip_levels: int | None
    runtime_id_v054: str | None


def _u24be(data: bytes, off: int) -> int:
    return (data[off] << 16) | (data[off + 1] << 8) | data[off + 2]


def _u24le(data: bytes, off: int) -> int:
    return data[off] | (data[off + 1] << 8) | (data[off + 2] << 16)


def is_refpack(data: bytes) -> bool:
    return len(data) >= 2 and data[0] in (0x10, 0x50) and data[1] == 0xFB


def refpack_declared_size(data: bytes) -> int:
    if not is_refpack(data):
        raise BigError("not RefPack data")
    if data[0] & 0x80:
        if len(data) < 6:
            raise BigError("truncated RefPack header")
        return struct.unpack_from(">I", data, 2)[0]
    if len(data) < 5:
        raise BigError("truncated RefPack header")
    return _u24be(data, 2)


def refpack_decompress(data: bytes) -> bytes:
    if not is_refpack(data):
        return data
    flags = data[0]
    src = 2
    if flags & 0x80:
        if len(data) < 6:
            raise BigError("truncated RefPack size")
        target = struct.unpack_from(">I", data, src)[0]
        src += 4
    else:
        if len(data) < 5:
            raise BigError("truncated RefPack size")
        target = _u24be(data, src)
        src += 3

    out = bytearray()
    while src < len(data):
        code = data[src]
        if code <= 0x7F:
            if src + 1 >= len(data):
                raise BigError("truncated RefPack short command")
            b1 = data[src + 1]
            literals = code & 0x03
            copy_len = ((code & 0x1C) >> 2) + 3
            copy_off = ((code & 0x60) << 3) + b1 + 1
            src += 2
        elif code <= 0xBF:
            if src + 2 >= len(data):
                raise BigError("truncated RefPack medium command")
            b1, b2 = data[src + 1], data[src + 2]
            literals = (b1 >> 6) & 0x03
            copy_len = (code & 0x3F) + 4
            copy_off = ((b1 & 0x3F) << 8) + b2 + 1
            src += 3
        elif code <= 0xDF:
            if src + 3 >= len(data):
                raise BigError("truncated RefPack long command")
            b1, b2, b3 = data[src + 1], data[src + 2], data[src + 3]
            literals = code & 0x03
            copy_len = ((code & 0x0C) << 6) + b3 + 5
            copy_off = ((code & 0x10) << 12) + (b1 << 8) + b2 + 1
            src += 4
        elif code <= 0xFB:
            literals = ((code & 0x1F) << 2) + 4
            src += 1
            if src + literals > len(data):
                raise BigError("truncated RefPack literal command")
            out.extend(data[src:src + literals])
            src += literals
            if len(out) > target:
                raise BigError("RefPack output exceeded declared size")
            continue
        else:
            literals = code & 0x03
            src += 1
            if src + literals > len(data):
                raise BigError("truncated RefPack stop command")
            out.extend(data[src:src + literals])
            break

        if src + literals > len(data):
            raise BigError("truncated RefPack command literals")
        out.extend(data[src:src + literals])
        src += literals
        copy_src = len(out) - copy_off
        if copy_src < 0:
            raise BigError("invalid RefPack back-reference")
        for i in range(copy_len):
            out.append(out[copy_src + i])
        if len(out) > target:
            raise BigError("RefPack output exceeded declared size")

    if len(out) < target:
        raise BigError(f"RefPack output short: {len(out)} != {target}")
    return bytes(out[:target])


def parse_big(data: bytes) -> tuple[str, int, list[BigEntry]]:
    if len(data) < 16 or data[:4] not in (b"BIGF", b"BIG4"):
        raise BigError("not a BIGF/BIG4 archive")
    magic = data[:4].decode("ascii")
    declared_size, count, index_end = struct.unpack_from(">III", data, 4)
    if declared_size != len(data):
        raise BigError(f"archive size mismatch: header={declared_size} actual={len(data)}")
    pos = 16
    entries: list[BigEntry] = []
    for _ in range(count):
        if pos + 8 > len(data):
            raise BigError("truncated BIG directory")
        off, size = struct.unpack_from(">II", data, pos)
        pos += 8
        try:
            end = data.index(0, pos, index_end)
        except ValueError as exc:
            raise BigError("unterminated BIG filename") from exc
        name = data[pos:end].decode("latin1")
        pos = end + 1
        if off + size > len(data):
            raise BigError(f"member {name!r} extends past archive")
        raw = data[off:off + min(size, 8)]
        packed = is_refpack(raw)
        dec_size = refpack_declared_size(data[off:off + size]) if packed else None
        entries.append(BigEntry(name, off, size, packed, dec_size))
    if pos != index_end:
        raise BigError(f"BIG index ended at 0x{pos:X}, header says 0x{index_end:X}")
    return magic, index_end, entries


def level_size(code: int, width: int, height: int) -> int | None:
    if width < 1 or height < 1:
        return None
    if code == 0x60:
        return max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 8
    if code in (0x61, 0x62):
        return max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * 16
    bpp = {0x6D: 2, 0x78: 2, 0x7B: 1, 0x7D: 4, 0x7E: 2, 0x7F: 3}.get(code)
    return width * height * bpp if bpp else None


def infer_mip_levels(code: int, width: int, height: int, payload_size: int) -> int | None:
    total = 0
    for level in range(16):
        size = level_size(code, max(1, width >> level), max(1, height >> level))
        if size is None:
            return None
        total += size
        if total == payload_size:
            return level + 1
        if total > payload_size:
            return None
    return None


def fnv1a64_v054(width: int, height: int, d3d_format: int, payload: bytes) -> int:
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


def parse_fsh_textures(member_name: str, data: bytes) -> list[TextureEntry]:
    if len(data) < 16 or data[:4] != b"SHPI":
        raise BigError(f"{member_name}: decompressed member is not SHPI")
    declared_size, count = struct.unpack_from("<II", data, 4)
    if declared_size != len(data):
        raise BigError(f"{member_name}: SHPI size mismatch")
    group = data[12:16].decode("ascii", errors="replace")
    if 16 + count * 8 > len(data):
        raise BigError(f"{member_name}: truncated SHPI directory")

    directory: list[tuple[str, int]] = []
    for i in range(count):
        base = 16 + i * 8
        name = data[base:base + 4].split(b"\0", 1)[0].decode("ascii", errors="replace")
        off = struct.unpack_from("<I", data, base + 4)[0]
        directory.append((name, off))

    out: list[TextureEntry] = []
    for name, off in directory:
        if off + 16 > len(data):
            raise BigError(f"{member_name}/{name}: image header outside SHPI")
        code = data[off] & 0x7F
        record_len = _u24le(data, off + 1)
        width, height = struct.unpack_from("<HH", data, off + 4)
        if record_len < 16 or off + record_len > len(data):
            raise BigError(f"{member_name}/{name}: invalid image record")
        record_payload_size = record_len - 16
        fmt_name, d3d_fmt = FORMAT_INFO.get(code, (f"UNKNOWN_0x{code:02X}", None))
        top_size = level_size(code, width, height)
        runtime_id = None
        if d3d_fmt is not None and code != 0x7B and top_size is not None:
            if top_size <= record_payload_size:
                payload = data[off + 16:off + 16 + top_size]
                fp = fnv1a64_v054(width, height, d3d_fmt, payload)
                runtime_id = f"{width}x{height}_{fmt_name}_{fp:016x}"
        out.append(TextureEntry(
            archive_member=member_name,
            fsh_group=group,
            name=name,
            format=fmt_name,
            width=width,
            height=height,
            record_payload_size=record_payload_size,
            level0_size=top_size,
            inferred_mip_levels=infer_mip_levels(code, width, height, record_payload_size),
            runtime_id_v054=runtime_id,
        ))
    return out


def member_bytes(archive: bytes, entry: BigEntry, decompress: bool = True) -> bytes:
    raw = archive[entry.offset:entry.offset + entry.size]
    return refpack_decompress(raw) if decompress and entry.refpack else raw


def safe_output_path(root: Path, name: str) -> Path:
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if not parts:
        raise BigError(f"unsafe/empty member path: {name!r}")
    return root.joinpath(*parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive", type=Path)
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--textures", action="store_true", help="index FSH texture members and v0.54 IDs")
    ap.add_argument("--extract", type=Path, help="extract all archive members")
    ap.add_argument("--decompress-refpack", action="store_true", help="decompress RefPack members on extraction")
    args = ap.parse_args()

    data = args.archive.read_bytes()
    magic, index_end, entries = parse_big(data)

    textures: list[TextureEntry] = []
    if args.textures:
        for entry in entries:
            if not entry.name.lower().endswith(".fsh"):
                continue
            try:
                textures.extend(parse_fsh_textures(entry.name, member_bytes(data, entry, True)))
            except BigError as exc:
                print(f"warning: {exc}")

    if args.extract:
        args.extract.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            out = safe_output_path(args.extract, entry.name)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(member_bytes(data, entry, args.decompress_refpack))

    if args.json:
        obj = {
            "path": str(args.archive),
            "magic": magic,
            "size": len(data),
            "index_end": index_end,
            "entry_count": len(entries),
            "entries": [asdict(e) for e in entries],
        }
        if args.textures:
            obj["texture_count"] = len(textures)
            obj["textures"] = [asdict(t) for t in textures]
        print(json.dumps(obj, indent=2))
        return 0

    print(f"{args.archive}: {magic} size={len(data)} entries={len(entries)} index_end=0x{index_end:X}")
    for entry in entries:
        suffix = f" RefPack->{entry.decompressed_size}" if entry.refpack else ""
        print(f"  {entry.name:30} offset=0x{entry.offset:08X} size={entry.size:8}{suffix}")
    if args.textures:
        print(f"\nTextures: {len(textures)}")
        for texture in textures:
            mip = "?" if texture.inferred_mip_levels is None else str(texture.inferred_mip_levels)
            print(
                f"  {texture.archive_member}/{texture.name}: "
                f"{texture.width}x{texture.height} {texture.format} "
                f"mips={mip} id={texture.runtime_id_v054 or '-'}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
