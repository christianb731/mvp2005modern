#!/usr/bin/env python3
"""Preview a ZIP of replacement BIG archives for an installed MVP 2005 game."""

import argparse
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from zlib import error as DeflateError

from big_tool_v2 import parse_big

try:
    from ntpath import isreserved
except ImportError:
    from pathlib import PureWindowsPath

    def isreserved(name: str) -> bool:
        return PureWindowsPath(name).is_reserved()


MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class Replacement:
    path: str
    installed_sha256: str
    packaged_sha256: str


def game_root(game: Path) -> Path:
    game = game.resolve(strict=True)
    if not (game / "mvp2005.exe").is_file() or not (game / "data").is_dir():
        raise ValueError(f"expected an MVP 2005 installation at {game}")
    return game


def replacement_parts(name: str) -> list[str]:
    parts = name.removesuffix("/").split("/")
    if parts[0].lower() != "data" or any(
        not part or part.endswith((".", " ")) or isreserved(part)
        or any(char in '\\:*?"<>|' or ord(char) < 32 for char in part)
        for part in parts
    ):
        raise ValueError(f"invalid package path {name!r}; expected data/...")
    return parts


def target_path(game: Path, name: str, *, allow_missing: bool = False) -> Path:
    parts = replacement_parts(name)
    if len(parts) < 2 or name.endswith("/") or not parts[-1].lower().endswith(".big"):
        raise ValueError(f"expected a replacement BIG archive at {name!r}")
    target = game.joinpath(*parts)
    if (allow_missing and not target.exists() and not target.is_symlink()
            and target.parent.resolve(strict=True) == target.parent):
        return target
    if not target.is_file() or target.resolve(strict=True) != target:
        raise ValueError(f"expected an existing game file at {name!r}")
    return target


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def preview(package: Path, game: Path, *, stage: Path | None = None) -> list[Replacement]:
    game = game_root(game)
    replacements = []
    seen = set()
    with ZipFile(package) as archive:
        for member in archive.infolist():
            name = member.orig_filename
            file_type = stat.S_IFMT(member.external_attr >> 16)
            if member.is_dir() and file_type in (0, stat.S_IFDIR):
                replacement_parts(name)
                continue
            if file_type not in (0, stat.S_IFREG):
                raise ValueError(f"expected a regular replacement BIG archive at {name!r}")
            key = name.casefold()
            if key in seen:
                raise ValueError(f"duplicate replacement path {name!r}")
            seen.add(key)

            target = target_path(game, name)
            if member.file_size > MAX_ARCHIVE_BYTES:
                raise ValueError(f"replacement exceeds the 256 MiB preview limit: {name!r}")

            payload = archive.read(member)
            try:
                parse_big(payload)
            except ValueError as exc:
                raise ValueError(f"{name}: {exc}") from exc
            replacement = Replacement(name, sha256(target), hashlib.sha256(payload).hexdigest())
            if stage is not None and replacement.installed_sha256 != replacement.packaged_sha256:
                with (stage / f"new-{len(replacements)}.big").open("xb") as staged:
                    staged.write(payload)
                    staged.flush()
                    os.fsync(staged.fileno())
            replacements.append(replacement)
    if not replacements:
        raise ValueError("package contains no replacement BIG archives")
    return replacements


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="ZIP containing data/... BIG archives")
    parser.add_argument("--game", type=Path, required=True, help="MVP 2005 installation folder")
    args = parser.parse_args()
    try:
        replacements = preview(args.package, args.game)
    except (BadZipFile, DeflateError, EOFError, OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"Preview failed: {exc}\n")

    for item in replacements:
        action = "Identical" if item.installed_sha256 == item.packaged_sha256 else "Replace"
        print(f"{action}  {item.path}")
        print(f"  Installed SHA-256  {item.installed_sha256}")
        print(f"  Packaged SHA-256   {item.packaged_sha256}")


if __name__ == "__main__":
    main()
