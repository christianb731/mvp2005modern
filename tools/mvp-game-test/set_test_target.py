from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import tempfile
import tomllib
from pathlib import Path

SECTION = "mcp_servers.mvp-game-test.env"


def target_fields(launcher: Path) -> dict[str, str]:
    launcher = launcher.resolve(strict=True)
    if not launcher.is_file() or launcher.name.lower() != "mvp2005modern.exe":
        raise ValueError("Select the exact MVP2005Modern.exe build to test")
    build = next((path for path in launcher.parents if path.name.lower() == ".build"), None)
    if build is None:
        raise ValueError("Select a launcher inside the project's .build directory")
    game = (build / "smoke-game" / "MVP2005Smoke.exe").resolve(strict=True)
    ini = launcher.parent / "mvp2005fix.ini"
    dll = launcher.parent / "mvp2005fix.dll"
    if not all(path.is_file() for path in (game, ini, dll)):
        raise ValueError(f"Missing smoke executable, INI or runtime DLL for {launcher}")
    value = ctypes.create_unicode_buffer(32768)
    ctypes.windll.kernel32.GetPrivateProfileStringW("Launcher", "ExePath", "", value, len(value), str(ini))
    selected = Path(value.value)
    if not selected.is_absolute() or selected.resolve() != game:
        raise ValueError(f"{ini} must already select the isolated game {game}; found {value.value!r}")
    return {
        "MVP_GAME_EXE": launcher.as_posix(),
        "MVP_GAME_WORKDIR": launcher.parent.as_posix(),
        "MVP_GAME_ALLOWED_EXES": f"{launcher.as_posix()};{game.as_posix()}",
    }


def update_config(text: str, fields: dict[str, str]) -> str:
    env = tomllib.loads(text)["mcp_servers"]["mvp-game-test"]["env"]
    if not fields.keys() <= env.keys():
        raise ValueError("Install the mvp-game-test config template first")
    lines = text.splitlines(keepends=True)
    active = False
    updated = set()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("["):
            active = re.fullmatch(r"\s*\[" + re.escape(SECTION) + r"\]\s*(?:#.*)?", line) is not None
        if active:
            match = re.match(r"(\s*)(MVP_GAME_[A-Z_]+)\s*=", line)
            if match and match[2] in fields:
                key = match[2]
                if not re.fullmatch(r'\s*' + key + r'\s*=\s*"[^"\r\n]*"\s*', line):
                    raise ValueError(f"Expected simple double-quoted setting for {key}")
                end = line[len(line.rstrip("\r\n")):]
                lines[i] = f"{match[1]}{key} = {json.dumps(fields[key], ensure_ascii=False)}{end}"
                updated.add(key)
    if updated != fields.keys():
        raise ValueError(f"Could not find exact [{SECTION}] settings")
    result = "".join(lines)
    new_env = tomllib.loads(result)["mcp_servers"]["mvp-game-test"]["env"]
    if any(new_env[key] != value for key, value in fields.items()):
        raise ValueError("Updated target failed validation")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Pin the Codex game-test agent to an explicitly selected smoke launcher")
    parser.add_argument("launcher", type=Path)
    parser.add_argument("--config", type=Path, default=Path.home() / ".codex" / "config.toml")
    parser.add_argument("--check", action="store_true", help="Show and verify the intended paths without writing")
    args = parser.parse_args()
    try:
        fields = target_fields(args.launcher)
        for key, value in fields.items():
            print(f"{key} = {value}")
        original = args.config.read_bytes()
        text = original.decode("utf-8")
        updated = update_config(text, fields).encode("utf-8")
        if updated == original:
            print("Codex configuration already matches.")
        elif args.check:
            print("Codex configuration differs.")
        else:
            with tempfile.NamedTemporaryFile(dir=args.config.parent, prefix=".mvp-target-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(updated)
            try:
                if args.config.read_bytes() != original:
                    raise RuntimeError("Codex configuration changed during update. Retry with the new contents.")
                os.replace(temporary, args.config)
            finally:
                temporary.unlink(missing_ok=True)
            print("Updated the three target fields. Reload Codex and confirm with game_test_info.")
    except (KeyError, OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
