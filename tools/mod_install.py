#!/usr/bin/env python3
"""Install or restore one MVP 2005 BIG replacement package on Windows."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from zipfile import BadZipFile
from zlib import error as DeflateError

from mod_preview import Replacement, game_root, preview, sha256, target_path


def require_closed_game(game: Path) -> None:
    names = {path.stem.casefold() for path in game.glob("mvp2005*.exe")}
    names.difference_update({"mvp2005fix", "mvp2005modern"})
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "$ErrorActionPreference = 'Stop'; Get-Process | ForEach-Object ProcessName"],
        check=True, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if names.intersection(line.strip().casefold() for line in result.stdout.splitlines()):
        raise ValueError("close MVP Baseball 2005 before changing installed files")


def plain_path(path: Path) -> Path:
    if path.resolve() != path:
        raise ValueError(f"unexpected link in mod storage at {path}")
    return path


@contextmanager
def locked_storage(game: Path):
    if os.name != "nt":
        raise ValueError("install and restore require Windows")
    import msvcrt

    storage = plain_path(game / "MVP2005Modern.Mods")
    storage.mkdir(exist_ok=True)
    with plain_path(storage / "lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError("another mod operation is in progress") from exc
        try:
            require_closed_game(game)
            yield storage
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def copy_verified(source: Path, destination: Path, expected: str) -> None:
    with source.open("rb") as source_file, destination.open("xb") as dest_file:
        shutil.copyfileobj(source_file, dest_file)
        dest_file.flush()
        os.fsync(dest_file.fileno())
    if sha256(destination) != expected:
        raise ValueError(f"file changed while staging {source}")


def replace_archive(staged: Path, target: Path, displaced: Path) -> None:
    from ctypes import WinDLL, WinError, c_void_p
    from ctypes.wintypes import BOOL, DWORD, LPCWSTR

    # Windows can recalculate inherited entries while merging a file's DACL.
    # Stage both swap files beside the target so inheritance uses its directory.
    replace = WinDLL("kernel32", use_last_error=True).ReplaceFileW
    replace.argtypes = (LPCWSTR, LPCWSTR, LPCWSTR, DWORD, c_void_p, c_void_p)
    replace.restype = BOOL
    if plain_path(displaced).exists():
        raise ValueError(f"a previous replacement must be recovered first: {target}")
    incoming = plain_path(displaced.with_suffix(".incoming"))
    if incoming.exists():
        raise ValueError(f"a previous replacement must be recovered first: {target}")
    try:
        copy_verified(staged, incoming, sha256(staged))
        if not replace(str(target), str(incoming), str(displaced), 0, None, None):
            raise WinError()
    finally:
        incoming.unlink(missing_ok=True)
    displaced.unlink()


def swap_backup(target: Path, transaction: Path, phase: str, index: int) -> Path:
    return target.with_name(f".mvp2005-{transaction.name}-{phase}-{index}.backup")


def write_journal(journal: Path, transaction: Path, entries: list[tuple[int, Replacement]]) -> None:
    data = {"version": 1, "directory": transaction.name,
            "files": [{"index": index, **asdict(entry)} for index, entry in entries]}
    staged = transaction / "journal.json"
    with staged.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    staged.replace(journal)


def discard_transaction(transaction: Path, indices: range | list[int]) -> None:
    for index in indices:
        for prefix in ("new", "original", "restore"):
            (transaction / f"{prefix}-{index}.big").unlink(missing_ok=True)
    (transaction / "journal.json").unlink(missing_ok=True)
    transaction.rmdir()


def install(game: Path, package: Path, *, expected: list[Replacement] | None = None) -> int:
    game = game_root(game)
    with locked_storage(game) as storage:
        journal = plain_path(storage / "active.json")
        if journal.exists():
            raise ValueError("a mod is active or interrupted; run restore first")
        transaction = Path(tempfile.mkdtemp(prefix="transaction-", dir=storage))
        committed = False
        try:
            replacements = preview(package, game, stage=transaction)
            if expected is not None and replacements != expected:
                raise ValueError("package or installed files changed since preview")
            entries = [(i, entry) for i, entry in enumerate(replacements)
                       if entry.installed_sha256 != entry.packaged_sha256]
            if not entries:
                return 0
            for index, entry in entries:
                target = target_path(game, entry.path)
                copy_verified(target, transaction / f"original-{index}.big", entry.installed_sha256)
            require_closed_game(game)
            for index, entry in entries:
                if sha256(target_path(game, entry.path)) != entry.installed_sha256:
                    raise ValueError(f"installed file changed since preview: {entry.path}")
                if sha256(transaction / f"new-{index}.big") != entry.packaged_sha256:
                    raise ValueError(f"staged replacement failed verification: {entry.path}")
            write_journal(journal, transaction, entries)
            committed = True
            for index, entry in entries:
                target = target_path(game, entry.path)
                if sha256(target) != entry.installed_sha256:
                    raise ValueError(f"installed file changed before replacement: {entry.path}")
                replace_archive(transaction / f"new-{index}.big", target,
                                swap_backup(target, transaction, "install", index))
                print(f"Installed {entry.path}")
            return len(entries)
        finally:
            if not committed and not journal.exists():
                # The transaction is our new directory. Remove only files created there.
                for staged in transaction.iterdir():
                    staged.unlink()
                transaction.rmdir()


def read_journal(storage: Path, journal: Path) -> tuple[Path, list[tuple[int, Replacement]]]:
    data = json.loads(journal.read_text(encoding="utf-8"))
    try:
        if data["version"] != 1 or not re.fullmatch(r"transaction-[a-z0-9_]+", data["directory"]):
            raise ValueError
        transaction = plain_path(storage / data["directory"])
        entries = []
        paths = set()
        indices = set()
        for record in data["files"]:
            index = record["index"]
            entry = Replacement(record["path"], record["installed_sha256"], record["packaged_sha256"])
            if (type(index) is not int or index < 0 or index in indices or entry.path.casefold() in paths
                    or not re.fullmatch(r"[a-f0-9]{64}", entry.installed_sha256)
                    or not re.fullmatch(r"[a-f0-9]{64}", entry.packaged_sha256)
                    or entry.installed_sha256 == entry.packaged_sha256):
                raise ValueError
            paths.add(entry.path.casefold())
            indices.add(index)
            entries.append((index, entry))
        if not entries:
            raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid mod recovery journal at {journal}") from exc
    return transaction, entries


def restore(game: Path) -> int:
    game = game_root(game)
    with locked_storage(game) as storage:
        journal = plain_path(storage / "active.json")
        if not journal.exists():
            return 0
        transaction, entries = read_journal(storage, journal)
        pending = []
        displaced_files = []
        swap_files = []
        recovered_originals = 0
        for index, entry in entries:
            target = target_path(game, entry.path, allow_missing=True)
            install_copy = plain_path(swap_backup(target, transaction, "install", index))
            restore_copy = plain_path(swap_backup(target, transaction, "restore", index))
            swap_files.extend((install_copy, install_copy.with_suffix(".incoming"),
                               restore_copy, restore_copy.with_suffix(".incoming")))
            if target.exists():
                current = sha256(target)
            elif install_copy.is_file() and sha256(install_copy) == entry.installed_sha256:
                displaced_files.append((install_copy, target))
                recovered_originals += 1
                continue
            elif restore_copy.is_file() and sha256(restore_copy) == entry.packaged_sha256:
                displaced_files.append((restore_copy, target))
                current = entry.packaged_sha256
            else:
                raise ValueError(f"installed file is missing: {entry.path}")
            if current == entry.installed_sha256:
                continue
            if current != entry.packaged_sha256:
                raise ValueError(f"file changed outside the mod manager: {entry.path}")
            backup = plain_path(transaction / f"original-{index}.big")
            staged = transaction / f"restore-{index}.big"
            staged.unlink(missing_ok=True)
            copy_verified(backup, staged, entry.installed_sha256)
            pending.append((staged, restore_copy, entry))
        require_closed_game(game)
        for displaced, target in displaced_files:
            if target.exists() or target.is_symlink():
                raise ValueError(f"file reappeared before restore: {target}")
            displaced.rename(target)
        for staged, displaced, entry in pending:
            target = target_path(game, entry.path)
            if sha256(target) != entry.packaged_sha256:
                raise ValueError(f"file changed before restore: {entry.path}")
            displaced.with_suffix(".incoming").unlink(missing_ok=True)
            replace_archive(staged, target, displaced)
            print(f"Restored {entry.path}")
        journal.unlink()
        try:
            for path in swap_files:
                path.unlink(missing_ok=True)
            discard_transaction(transaction, [index for index, _ in entries])
        except OSError as exc:
            print(f"Game files restored. Could not remove staging files: {exc}", file=sys.stderr)
        return len(pending) + recovered_originals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True, help="MVP 2005 installation folder")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("install").add_argument("package", type=Path)
    actions.add_parser("restore")
    args = parser.parse_args()
    try:
        changed = install(args.game, args.package) if args.action == "install" else restore(args.game)
    except (BadZipFile, DeflateError, EOFError, OSError, RuntimeError, ValueError,
            subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Mod operation failed: {exc}\n")
    if not changed:
        print("No game files needed to change.")


if __name__ == "__main__":
    main()
