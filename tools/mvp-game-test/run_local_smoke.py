"""Run the same game worker locally against one explicitly selected smoke build."""

from __future__ import annotations

import argparse
import configparser
import os
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from set_test_target import target_fields

ROOT = Path(__file__).resolve().parent
DISPLAY_MODES = ("windowed", "borderless", "fullscreen")


def stage_package(package: Path) -> Path:
    package = package.resolve(strict=True)
    build_root = package.parent.parent
    game = build_root / "smoke-game" / "MVP2005Smoke.exe"
    if build_root.name.lower() != ".build" or not game.is_file() or game.resolve() != game:
        raise ValueError(f"Build output must be directly under .build with an isolated smoke game at {game}")
    stage = package.parent / "smoke-launcher"
    with ZipFile(package) as archive:
        files = {name: archive.read(name) for name in ("MVP2005Modern.exe", "mvp2005fix.dll", "COMPONENTS.txt")}
    stage.mkdir()
    for name, payload in files.items():
        (stage / name).write_bytes(payload)
    (stage / "mvp2005fix.ini").write_text(
        f"[Launcher]\nExePath={game}\n"
        "[Resolution]\nWidth=1920\nHeight=1080\n"
        "[Aspect]\nEnabled=1\nScaleX=0.75\n"
        "[SaveFix]\nEnabled=1\n[Debug]\nLogging=1\n"
        "[Modern]\nSkipIntro=1\n[MenuScale]\nPreserveAspect=0\n",
        encoding="mbcs",
    )
    return stage / "MVP2005Modern.exe"


def run_selected(launcher: Path, tests: list[str], display_modes: tuple[str, ...]) -> int:
    fields = target_fields(launcher)
    os.environ.update(fields)
    os.environ.update({
        "MVP_GAME_ARGS_JSON": "[]",
        "MVP_GAME_TESTS_DIR": str(ROOT / "tests"),
        "MVP_GAME_ARTIFACT_DIR": str(launcher.resolve().parent / "artifacts"),
        "MVP_GAME_MENU_TEST": "1",
        "MVP_GAME_WINDOW_TITLE_REGEX": "",
    })
    import mvp_game_test as worker

    def run_one(name: str) -> bool:
        result = worker.run_game_test(name)
        print(result, flush=True)
        return result.startswith("PASS ")

    @worker.desktop_tool
    def run() -> int:
        print(worker.game_test_info(), flush=True)
        target = worker._target()
        active = worker._processes(target)
        if active:
            raise RuntimeError("Clean launch requires closing existing MVP processes: " + worker._process_summary(active))
        if not display_modes:
            for test in tests:
                if not run_one(test):
                    return 1
            return 0

        component = target.launch.parent / "COMPONENTS.txt"
        if not component.read_text(encoding="utf-8").startswith("MVP2005 Modern v0.53-smoke-display-test "):
            raise ValueError("Display matrix requires the v0.53-smoke-display-test launcher")
        # Display testing can change wrapper settings. Require a separate fixture.
        build = target.game.parent.parent
        if not any(parent.name.lower() == ".build" for parent in build.parents):
            raise ValueError("Display testing requires a separate nested .build fixture")
        if target.launch.parent.parent.parent != build:
            raise ValueError("Stage the display launcher under .build/<output>/smoke-launcher")
        ini = target.ini
        wrapper = target.game.parent / "dgVoodoo.conf"
        originals = {path: path.read_bytes() for path in (ini, wrapper)}
        failures = []
        try:
            for mode in display_modes:
                config = configparser.ConfigParser(interpolation=None)
                config.optionxform = str
                config.read_string(originals[ini].decode("mbcs"))
                config["DisplayTest"] = {"Mode": mode}
                with ini.open("w", encoding="mbcs") as stream:
                    config.write(stream)
                if not run_one(f"display_{mode}"):
                    failures.append(mode)
                if worker._processes(target):
                    raise RuntimeError("Display run left an MVP process active")
        finally:
            for path, payload in originals.items():
                path.write_bytes(payload)
        if failures:
            print("Display failures: " + ", ".join(failures), flush=True)
        return int(bool(failures))

    return run()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--launcher", type=Path)
    source.add_argument("--package", type=Path)
    cases = parser.add_mutually_exclusive_group()
    cases.add_argument("--test", action="append", help="JSON test name, repeat to run several cases")
    cases.add_argument("--display-matrix", action="store_true")
    cases.add_argument("--display-mode", choices=DISPLAY_MODES, help="run one isolated display profile")
    args = parser.parse_args()
    try:
        launcher = stage_package(args.package) if args.package else args.launcher
        modes = DISPLAY_MODES if args.display_matrix else (args.display_mode,) if args.display_mode else ()
        raise SystemExit(run_selected(launcher, args.test or ["launch_smoke"], modes))
    except (OSError, ValueError, RuntimeError, BadZipFile, KeyError) as exc:
        parser.exit(1, f"Local smoke failed: {exc}\n")


if __name__ == "__main__":
    main()
