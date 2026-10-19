#!/usr/bin/env python3
"""Inspect/extract MVP Baseball 2005 BIGF archives.

Supports both original EA BIGF headers and common repacked-mod BIGF headers,
RefPack/QFS members, and SHPI/FSH texture indexing. Runtime IDs intentionally
hash only mip level 0 to match MVP2005 Modern v0.54+.
"""
from __future__ import annotations

import argparse
import json
import struct
from dataclasses import dataclass, asdict
from pathlib import Path

FORMAT_INFO = {
    0x60: ("DXT1", 0x31545844), 0x61: ("DXT3", 0x33545844),
    0x62: ("DXT5", 0x35545844), 0x6D: ("A4R4G4B4", 26),
    0x78: ("R5G6B5", 23), 0x7B: ("P8", 41),
    0x7D: ("A8R8G8B8", 21), 0x7E: ("A1R5G5B5", 25),
    0x7F: ("R8G8B8", 20),
}

class BigError(ValueError):
    pass

@dataclass
class BigHeader:
    magic: str
    size: int
    size_encoding: str
    entry_count: int
    index_end: int
    index_padding: int

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
    if not is_refpack(data): raise BigError("not RefPack data")
    if data[0] & 0x80:
        if len(data) < 6: raise BigError("truncated RefPack header")
        return struct.unpack_from(">I", data, 2)[0]
    if len(data) < 5: raise BigError("truncated RefPack header")
    return _u24be(data, 2)

def refpack_decompress(data: bytes) -> bytes:
    if not is_refpack(data): return data
    src = 2
    if data[0] & 0x80:
        if len(data) < 6: raise BigError("truncated RefPack size")
        target = struct.unpack_from(">I", data, src)[0]; src += 4
    else:
        if len(data) < 5: raise BigError("truncated RefPack size")
        target = _u24be(data, src); src += 3
    out = bytearray()
    while src < len(data):
        code = data[src]
        if code <= 0x7F:
            if src + 1 >= len(data): raise BigError("truncated short RefPack command")
            b1 = data[src + 1]; literals = code & 3
            copy_len = ((code & 0x1C) >> 2) + 3
            copy_off = ((code & 0x60) << 3) + b1 + 1; src += 2
        elif code <= 0xBF:
            if src + 2 >= len(data): raise BigError("truncated medium RefPack command")
            b1, b2 = data[src + 1], data[src + 2]; literals = (b1 >> 6) & 3
            copy_len = (code & 0x3F) + 4
            copy_off = ((b1 & 0x3F) << 8) + b2 + 1; src += 3
        elif code <= 0xDF:
            if src + 3 >= len(data): raise BigError("truncated long RefPack command")
            b1, b2, b3 = data[src + 1], data[src + 2], data[src + 3]
            literals = code & 3; copy_len = ((code & 0x0C) << 6) + b3 + 5
            copy_off = ((code & 0x10) << 12) + (b1 << 8) + b2 + 1; src += 4
        elif code <= 0xFB:
            literals = ((code & 0x1F) << 2) + 4; src += 1
            if src + literals > len(data): raise BigError("truncated literal RefPack command")
            out.extend(data[src:src + literals]); src += literals
            if len(out) > target: raise BigError("RefPack output exceeded declared size")
            continue
        else:
            literals = code & 3; src += 1
            if src + literals > len(data): raise BigError("truncated RefPack stop command")
            out.extend(data[src:src + literals]); break
        if src + literals > len(data): raise BigError("truncated RefPack literals")
        out.extend(data[src:src + literals]); src += literals
        copy_src = len(out) - copy_off
        if copy_src < 0: raise BigError("invalid RefPack back-reference")
        for i in range(copy_len): out.append(out[copy_src + i])
        if len(out) > target: raise BigError("RefPack output exceeded declared size")
    if len(out) < target: raise BigError(f"RefPack output short: {len(out)} != {target}")
    return bytes(out[:target])


def parse_big(data: bytes) -> tuple[BigHeader, list[BigEntry]]:
    if len(data) < 16 or data[:4] not in (b"BIGF", b"BIG4"):
        raise BigError("not a BIGF/BIG4 archive")
    size_be = struct.unpack_from(">I", data, 4)[0]
    size_le = struct.unpack_from("<I", data, 4)[0]
    if size_be == len(data): size_encoding = "big-endian"
    elif size_le == len(data): size_encoding = "little-endian"
    else: raise BigError(f"archive size field does not match file: be={size_be} le={size_le} actual={len(data)}")
    count, index_end = struct.unpack_from(">II", data, 8)
    if index_end < 16 or index_end > len(data): raise BigError("invalid BIG index end")
    pos = 16; entries: list[BigEntry] = []
    for _ in range(count):
        if pos + 8 > index_end: raise BigError("truncated BIG directory")
        off, size = struct.unpack_from(">II", data, pos); pos += 8
        try: end = data.index(0, pos, index_end)
        except ValueError as exc: raise BigError("unterminated BIG filename") from exc
        name = data[pos:end].decode("latin1"); pos = end + 1
        if off + size > len(data): raise BigError(f"member {name!r} extends past archive")
        raw = data[off:off + min(size, 8)]; packed = is_refpack(raw)
        dec = refpack_declared_size(data[off:off + size]) if packed else None
        entries.append(BigEntry(name, off, size, packed, dec))
    padding = index_end - pos
    if padding < 0: raise BigError("BIG directory passed index end")
    if any(data[pos:index_end]): raise BigError("non-zero bytes in BIG index padding")
    header = BigHeader(data[:4].decode("ascii"), len(data), size_encoding, count, index_end, padding)
    return header, entries


def level_size(code: int, width: int, height: int) -> int | None:
    if width < 1 or height < 1: return None
    if code == 0x60: return max(1, (width + 3)//4) * max(1, (height + 3)//4) * 8
    if code in (0x61, 0x62): return max(1, (width + 3)//4) * max(1, (height + 3)//4) * 16
    bpp = {0x6D:2, 0x78:2, 0x7B:1, 0x7D:4, 0x7E:2, 0x7F:3}.get(code)
    return width * height * bpp if bpp else None

def infer_mip_levels(code: int, width: int, height: int, payload_size: int) -> int | None:
    total = 0
    for level in range(16):
        sz = level_size(code, max(1,width>>level), max(1,height>>level))
        if sz is None: return None
        total += sz
        if total == payload_size: return level + 1
        if total > payload_size: return None
    return None

def fnv1a64_v054(width: int, height: int, d3d_format: int, payload: bytes) -> int:
    h = 14695981039346656037; prime = 1099511628211; mask = 0xFFFFFFFFFFFFFFFF
    for value in (width, height, d3d_format):
        for shift in (0,8,16,24): h = ((h ^ ((value >> shift) & 0xFF)) * prime) & mask
    for b in payload: h = ((h ^ b) * prime) & mask
    return h

def parse_fsh_textures(member_name: str, data: bytes) -> list[TextureEntry]:
    if is_refpack(data): data = refpack_decompress(data)
    if len(data) < 16 or data[:4] != b"SHPI": raise BigError(f"{member_name}: not SHPI")
    declared, count = struct.unpack_from("<II", data, 4)
    if declared != len(data): raise BigError(f"{member_name}: SHPI size mismatch")
    group = data[12:16].decode("ascii", errors="replace")
    if 16 + count*8 > len(data): raise BigError(f"{member_name}: truncated SHPI directory")
    directory=[]
    for i in range(count):
        base=16+i*8; name=data[base:base+4].split(b"\0",1)[0].decode("ascii",errors="replace")
        off=struct.unpack_from("<I",data,base+4)[0]; directory.append((name,off))
    result=[]
    for name,off in directory:
        if off+16>len(data): raise BigError(f"{member_name}/{name}: header outside SHPI")
        code=data[off]&0x7F; rec_len=_u24le(data,off+1); width,height=struct.unpack_from("<HH",data,off+4)
        if rec_len<16 or off+rec_len>len(data): raise BigError(f"{member_name}/{name}: invalid image record")
        payload_size=rec_len-16; fmt,d3d=FORMAT_INFO.get(code,(f"UNKNOWN_0x{code:02X}",None)); top=level_size(code,width,height)
        runtime_id=None
        if d3d is not None and code!=0x7B and top is not None and top<=payload_size:
            fp=fnv1a64_v054(width,height,d3d,data[off+16:off+16+top]); runtime_id=f"{width}x{height}_{fmt}_{fp:016x}"
        result.append(TextureEntry(member_name,group,name,fmt,width,height,payload_size,top,infer_mip_levels(code,width,height,payload_size),runtime_id))
    return result

def member_bytes(archive: bytes, entry: BigEntry, decompress: bool=True) -> bytes:
    raw=archive[entry.offset:entry.offset+entry.size]
    return refpack_decompress(raw) if decompress and entry.refpack else raw

def safe_output_path(root: Path, name: str) -> Path:
    parts=[p for p in name.replace("\\","/").split("/") if p not in ("",".","..")]
    if not parts: raise BigError(f"unsafe member path {name!r}")
    return root.joinpath(*parts)


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("archive",type=Path)
    ap.add_argument("--json",action="store_true"); ap.add_argument("--textures",action="store_true")
    ap.add_argument("--extract",type=Path); ap.add_argument("--decompress-refpack",action="store_true")
    args=ap.parse_args(); data=args.archive.read_bytes(); header,entries=parse_big(data)
    textures=[]
    if args.textures:
        for entry in entries:
            if entry.name.lower().endswith(".fsh"):
                try: textures.extend(parse_fsh_textures(entry.name,member_bytes(data,entry,True)))
                except BigError as exc: print(f"warning: {exc}")
    if args.extract:
        args.extract.mkdir(parents=True,exist_ok=True)
        for entry in entries:
            out=safe_output_path(args.extract,entry.name); out.parent.mkdir(parents=True,exist_ok=True)
            out.write_bytes(member_bytes(data,entry,args.decompress_refpack))
    if args.json:
        obj={"path":str(args.archive),"header":asdict(header),"entries":[asdict(e) for e in entries]}
        if args.textures: obj.update(texture_count=len(textures),textures=[asdict(t) for t in textures])
        print(json.dumps(obj,indent=2)); return 0
    print(f"{args.archive}: {header.magic} size={header.size} entries={header.entry_count} index_end=0x{header.index_end:X} size_encoding={header.size_encoding} index_padding={header.index_padding}")
    for e in entries:
        suffix=f" RefPack->{e.decompressed_size}" if e.refpack else ""
        print(f"  {e.name:30} offset=0x{e.offset:08X} size={e.size:8}{suffix}")
    if args.textures:
        print(f"\nTextures: {len(textures)}")
        for t in textures:
            print(f"  {t.archive_member}/{t.name}: {t.width}x{t.height} {t.format} mips={t.inferred_mip_levels or '?'} id={t.runtime_id_v054 or '-'}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
