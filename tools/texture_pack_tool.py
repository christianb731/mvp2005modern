#!/usr/bin/env python3
"""Create MVP2005 Modern texture packs from user-owned stock assets.

The first built-in recipe creates a stock-layout-preserving Yankee Stadium field
quality test. It never writes to the game archive and never embeds EA assets in
the repository. Pillow is required only for image resampling recipes.
"""
from __future__ import annotations

import argparse
import configparser
import shutil
import struct
from pathlib import Path

from big_tool_v2 import BigError, member_bytes, parse_big, parse_fsh_textures


def fsh_entry_blob(data: bytes, wanted: str):
    if len(data) < 16 or data[:4] != b"SHPI": raise BigError("not SHPI")
    count = struct.unpack_from("<I", data, 8)[0]
    for i in range(count):
        base = 16 + i * 8
        name = data[base:base+4].split(b"\0",1)[0].decode("ascii",errors="replace")
        off = struct.unpack_from("<I", data, base+4)[0]
        if name != wanted: continue
        code = data[off] & 0x7F
        rec_len = data[off+1] | (data[off+2] << 8) | (data[off+3] << 16)
        w,h = struct.unpack_from("<HH", data, off+4)
        if rec_len < 16 or off + rec_len > len(data): raise BigError("invalid FSH image record")
        return code,w,h,data[off+16:off+rec_len]
    raise BigError(f"FSH entry {wanted!r} not found")


def base_level_size(code: int, w: int, h: int) -> int:
    if code == 0x60: return max(1,(w+3)//4)*max(1,(h+3)//4)*8
    if code in (0x61,0x62): return max(1,(w+3)//4)*max(1,(h+3)//4)*16
    bpp={0x6D:2,0x78:2,0x7D:4,0x7E:2,0x7F:3}.get(code)
    if not bpp: raise BigError(f"unsupported source format 0x{code:02X}")
    return w*h*bpp


def decode_rgba(code: int, w: int, h: int, payload: bytes):
    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit("Pillow is required for stock-derived HD pack generation: pip install pillow") from exc
    need=base_level_size(code,w,h); payload=payload[:need]
    out=bytearray(w*h*4)
    if code == 0x78:  # R5G6B5
        for i in range(w*h):
            v=payload[i*2] | (payload[i*2+1]<<8)
            r=((v>>11)&31)*255//31; g=((v>>5)&63)*255//63; b=(v&31)*255//31
            out[i*4:i*4+4]=bytes((r,g,b,255))
    elif code == 0x6D:  # A4R4G4B4
        for i in range(w*h):
            v=payload[i*2] | (payload[i*2+1]<<8)
            a=((v>>12)&15)*17; r=((v>>8)&15)*17; g=((v>>4)&15)*17; b=(v&15)*17
            out[i*4:i*4+4]=bytes((r,g,b,a))
    elif code == 0x7E:  # A1R5G5B5
        for i in range(w*h):
            v=payload[i*2] | (payload[i*2+1]<<8)
            a=255 if v&0x8000 else 0; r=((v>>10)&31)*255//31; g=((v>>5)&31)*255//31; b=(v&31)*255//31
            out[i*4:i*4+4]=bytes((r,g,b,a))
    elif code == 0x7D:  # A8R8G8B8 / BGRA memory order
        for i in range(w*h):
            b,g,r,a=payload[i*4:i*4+4]; out[i*4:i*4+4]=bytes((r,g,b,a))
    elif code == 0x7F:
        for i in range(w*h):
            b,g,r=payload[i*3:i*3+3]; out[i*4:i*4+4]=bytes((r,g,b,255))
    else:
        raise BigError("compressed source formats are not used by the field-test recipe")
    return Image.frombytes("RGBA",(w,h),bytes(out))


def rgba_to_bgra_bytes(image) -> bytes:
    raw=image.convert("RGBA").tobytes(); out=bytearray(len(raw))
    for i in range(0,len(raw),4):
        r,g,b,a=raw[i:i+4]; out[i:i+4]=bytes((b,g,r,a))
    return bytes(out)


def write_argb8888_dds(path: Path, image) -> int:
    from PIL import Image
    levels=[]; cur=image.convert("RGBA")
    while True:
        levels.append(cur)
        if cur.width==1 and cur.height==1: break
        cur=cur.resize((max(1,cur.width//2),max(1,cur.height//2)),Image.Resampling.LANCZOS)
    header=bytearray(128); header[:4]=b"DDS "; struct.pack_into("<I",header,4,124)
    flags=0x00001007|0x00000008|0x00020000  # caps,height,width,pixfmt,pitch,mipmapcount
    struct.pack_into("<I",header,8,flags); struct.pack_into("<I",header,12,image.height); struct.pack_into("<I",header,16,image.width)
    struct.pack_into("<I",header,20,image.width*4); struct.pack_into("<I",header,28,len(levels))
    struct.pack_into("<I",header,76,32); struct.pack_into("<I",header,80,0x41); struct.pack_into("<I",header,88,32)
    struct.pack_into("<I",header,92,0x00FF0000); struct.pack_into("<I",header,96,0x0000FF00); struct.pack_into("<I",header,100,0x000000FF); struct.pack_into("<I",header,104,0xFF000000)
    caps=0x1000 | (0x400000|0x8 if len(levels)>1 else 0); struct.pack_into("<I",header,108,caps)
    path.write_bytes(bytes(header)+b"".join(rgba_to_bgra_bytes(level) for level in levels))
    return len(levels)


def write_manifest(pack_dir: Path, name: str, description: str, source: str):
    cfg=configparser.ConfigParser(); cfg["Pack"]={"Name":name,"Format":"1","Description":description,"Source":source,"StockLayoutRequired":"1"}
    with (pack_dir/"manifest.ini").open("w",encoding="utf-8") as fh: cfg.write(fh)


def make_yankee_field_test(archive: Path, out_root: Path, scale: int):
    try:
        from PIL import Image, ImageFilter
    except ImportError as exc:
        raise SystemExit("Pillow is required: pip install pillow") from exc
    data=archive.read_bytes(); header,entries=parse_big(data); by_name={e.name.lower():e for e in entries}
    pack=out_root/"StockHDTest"; texdir=pack/"Textures"; texdir.mkdir(parents=True,exist_ok=True)
    recipe=[("field0.fsh","fl01"),("field1.fsh","fl02"),("field2.fsh","fl03")]
    created=[]
    for member,name in recipe:
        entry=by_name.get(member)
        if not entry: raise BigError(f"{member} missing from {archive}")
        fsh=member_bytes(data,entry,True); indexed={t.name:t for t in parse_fsh_textures(member,fsh)}
        meta=indexed[name]
        if not meta.runtime_id_v054: raise BigError(f"no runtime ID for {member}/{name}")
        code,w,h,payload=fsh_entry_blob(fsh,name); image=decode_rgba(code,w,h,payload)
        enlarged=image.resize((w*scale,h*scale),Image.Resampling.LANCZOS)
        enlarged=enlarged.filter(ImageFilter.UnsharpMask(radius=1.25,percent=120,threshold=3))
        out=texdir/(meta.runtime_id_v054+".dds"); mips=write_argb8888_dds(out,enlarged)
        created.append((member,name,meta.runtime_id_v054,w,h,enlarged.width,enlarged.height,mips))
    write_manifest(pack,"StockHDTest","Stock-layout-preserving 4x Yankee Stadium field texture quality test.",archive.name)
    readme=pack/"README.txt"; readme.write_text(
        "MVP2005 Modern StockHDTest\n\nGenerated from your own stock Yankee Stadium archive.\n"
        "No BIG/FSH game files are modified. Enable with:\n\n[TextureMods]\nActivePack=StockHDTest\n\n"
        + "\n".join(f"{m}/{n}: {ow}x{oh} -> {nw}x{nh}  {rid}" for m,n,rid,ow,oh,nw,nh,_ in created)+"\n",
        encoding="utf-8")
    for item in created: print(f"{item[0]}/{item[1]}: {item[3]}x{item[4]} -> {item[5]}x{item[6]} mips={item[7]} id={item[2]}")
    print(f"pack: {pack}")


def init_pack(name: str, out_root: Path):
    pack=out_root/name; (pack/"Textures").mkdir(parents=True,exist_ok=True)
    write_manifest(pack,name,"MVP2005 Modern texture pack","user-authored")
    print(pack)

def add_dds(pack: Path, runtime_id: str, dds: Path):
    if not dds.is_file(): raise SystemExit(f"DDS not found: {dds}")
    dest=pack/"Textures"/(runtime_id+".dds"); dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(dds,dest); print(dest)


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="cmd",required=True)
    p=sub.add_parser("init"); p.add_argument("name"); p.add_argument("out",type=Path)
    p=sub.add_parser("add-dds"); p.add_argument("pack",type=Path); p.add_argument("runtime_id"); p.add_argument("dds",type=Path)
    p=sub.add_parser("make-yankee-field-test"); p.add_argument("archive",type=Path); p.add_argument("out",type=Path); p.add_argument("--scale",type=int,default=4,choices=(2,4,8))
    args=ap.parse_args()
    if args.cmd=="init": init_pack(args.name,args.out)
    elif args.cmd=="add-dds": add_dds(args.pack,args.runtime_id,args.dds)
    else: make_yankee_field_test(args.archive,args.out,args.scale)
    return 0

if __name__ == "__main__": raise SystemExit(main())
