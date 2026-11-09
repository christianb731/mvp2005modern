#!/usr/bin/env python3
"""Build an offline MVP Baseball 2005 texture index from BIG/FSH assets.

The index maps human-readable source locations to the content IDs consumed by
MVP2005 Modern's runtime DDS replacement layer. It reads user-owned game files;
no game assets are embedded in this repository.
"""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from big_tool_v2 import BigError, is_refpack, member_bytes, parse_big, parse_fsh_textures


def iter_inputs(root: Path):
    if root.is_file():
        yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in (".big", ".fsh"):
            yield path


def index_path(path: Path, base: Path) -> list[dict]:
    rel = str(path.relative_to(base)) if base.is_dir() else path.name
    data = path.read_bytes()
    rows: list[dict] = []
    if path.suffix.lower() == ".big":
        header, entries = parse_big(data)
        for entry in entries:
            if not entry.name.lower().endswith(".fsh"):
                continue
            try:
                textures = parse_fsh_textures(entry.name, member_bytes(data, entry, True))
            except BigError as exc:
                rows.append({"archive": rel, "member": entry.name, "error": str(exc)})
                continue
            for tex in textures:
                row = asdict(tex)
                row.update(archive=rel, big_size_encoding=header.size_encoding, error="")
                rows.append(row)
        return rows

    raw = data
    if is_refpack(raw):
        # parse_fsh_textures handles RefPack itself.
        pass
    try:
        textures = parse_fsh_textures(path.name, raw)
    except BigError as exc:
        return [{"archive": rel, "member": path.name, "error": str(exc)}]
    for tex in textures:
        row = asdict(tex)
        row.update(archive=rel, big_size_encoding="", error="")
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="one BIG/FSH file or a game/data directory")
    ap.add_argument("--json", type=Path, help="write JSON index")
    ap.add_argument("--csv", type=Path, help="write CSV index")
    ap.add_argument("--min-dimension", type=int, default=1)
    args = ap.parse_args()

    base = args.input if args.input.is_dir() else args.input.parent
    rows: list[dict] = []
    errors = 0
    for path in iter_inputs(args.input):
        try:
            rows.extend(index_path(path, base))
        except Exception as exc:
            errors += 1
            rows.append({"archive": str(path), "member": "", "error": str(exc)})

    min_dim = max(1, args.min_dimension)
    filtered=[]
    for row in rows:
        if row.get("error"):
            filtered.append(row); continue
        if int(row.get("width", 0)) >= min_dim and int(row.get("height", 0)) >= min_dim:
            filtered.append(row)
    rows = filtered

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        keys = [
            "archive", "archive_member", "fsh_group", "name", "width", "height",
            "format", "inferred_mip_levels", "runtime_id_v054", "record_payload_size",
            "level0_size", "big_size_encoding", "error",
        ]
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
            writer.writeheader(); writer.writerows(rows)

    good = [r for r in rows if not r.get("error")]
    ids = {r.get("runtime_id_v054") for r in good if r.get("runtime_id_v054")}
    print(f"indexed textures={len(good)} unique_runtime_ids={len(ids)} errors={sum(1 for r in rows if r.get('error')) + errors}")
    for row in good[:25]:
        print(f"{row['archive']} :: {row['archive_member']}/{row['name']} :: {row['width']}x{row['height']} {row['format']} :: {row.get('runtime_id_v054') or '-'}")
    if len(good) > 25: print(f"... {len(good)-25} more")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
