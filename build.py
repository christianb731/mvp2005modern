#!/usr/bin/env python3
"""Build MVP2005 Modern from its pinned upstream source."""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parent
UPSTREAM_URL = "https://github.com/ostrich/mvp2005fix.git"
UPSTREAM_REV = "1c0dae9b030a8fb66648655c8d14043af1ead676"
PROFILES = {
    "v0.53": (),
    "v0.53-menu-fit": ("apply_menu_aspect_preview.py",),
    "v0.53-menu-controls": ("apply_menu_aspect_preview.py", "apply_menu_control_trace.py"),
    "v0.53-menu-controller-test": ("apply_menu_aspect_preview.py", "apply_menu_control_trace.py",
                                  "apply_menu_controller_test.py"),
    "v0.53-smoke-display-test": ("apply_smoke_display_test.py",),
    "v0.53-mod-manager": ("apply_mod_manager_launcher.py",),
    "v0.55-texture-packs": ("apply_texture_replacement_v54.py", "apply_texture_packs_v55.py"),
}


def run(*args: str | Path, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def stage_upstream(source: Path, archive: Path | None) -> None:
    source.mkdir()
    if archive is None:
        run("git", "init", "--quiet", cwd=source)
        run("git", "fetch", "--depth=1", UPSTREAM_URL, UPSTREAM_REV, cwd=source)
        run("git", "checkout", "--quiet", "--detach", "FETCH_HEAD", cwd=source)
        return

    with ZipFile(archive) as upstream:
        if upstream.comment != UPSTREAM_REV.encode("ascii"):
            raise ValueError(f"expected a git archive of {UPSTREAM_REV}")
        upstream.extractall(source)


def build(profile: str, output: Path, archive: Path | None, run_tests: bool) -> Path:
    patches = ROOT / "patches"
    baseline = (patches / "build-v0.53.txt").read_text(encoding="ascii").splitlines()
    output.mkdir(parents=True)
    source = output / "upstream"
    stage_upstream(source, archive)
    for patch in (*baseline, *PROFILES[profile]):
        run(sys.executable, "-B", patches / patch, cwd=source)
    if archive is None:
        run("git", "diff", "--check", cwd=source)

    run("make", "CFLAGS=-O2 -Wall -Wextra -D_WIN32_WINNT=0x0A00", "test-build", "release", cwd=source)
    release = source / "release"
    if run_tests:
        run(release / "inline-hooks-test.exe", cwd=release)
        run(release / "inline-hooks-test.exe", "--system", cwd=release)
        run(release / "startup-test.exe", cwd=release)

    package = output / f"mvp2005modern-{profile}-x86.zip"
    with ZipFile(package, "x", compression=ZIP_DEFLATED) as dist:
        dist.write(release / "mvp2005fix.exe", "MVP2005Modern.exe")
        dist.write(release / "mvp2005fix.dll", "mvp2005fix.dll")
        dist.write(source / "LICENSE", "LICENSE")
        dist.writestr("COMPONENTS.txt", f"MVP2005 Modern {profile} (Windows x86)\n"
                      f"Upstream mvp2005fix: {UPSTREAM_REV}\n")
        if profile == "v0.53-mod-manager":
            for name in ("mod_manager.pyw", "mod_install.py", "mod_preview.py", "big_tool_v2.py", "README.md"):
                dist.write(ROOT / "tools" / name, f"tools/{name}")
    return package


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="v0.53")
    parser.add_argument("--output", type=Path, required=True, help="new build directory")
    parser.add_argument("--source-zip", type=Path, help="trusted git archive of the pinned revision")
    parser.add_argument("--run-tests", action="store_true", help="run the x86 test executables on Windows")
    parser.add_argument("--smoke", action="store_true", help="stage and run an interactive Windows launch smoke test")
    parser.add_argument("--smoke-python", type=Path, help="Python with the installed game-test dependencies")
    args = parser.parse_args()
    if (args.run_tests or args.smoke) and os.name != "nt":
        parser.error("--run-tests and --smoke require Windows")
    if args.smoke_python and not args.smoke:
        parser.error("--smoke-python requires --smoke")
    try:
        smoke_python = None
        if args.smoke:
            smoke_python = args.smoke_python
            if smoke_python is None:
                import tomllib

                config = Path.home() / ".codex" / "config.toml"
                server = tomllib.loads(config.read_text(encoding="utf-8"))["mcp_servers"]["mvp-game-test"]
                smoke_python = Path(server["command"])
            smoke_python = smoke_python.resolve(strict=True)
        package = build(args.profile, args.output.resolve(), args.source_zip, args.run_tests)
    except (OSError, ValueError, KeyError, BadZipFile, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Build failed: {exc}\n")
    print(package, flush=True)
    if smoke_python:
        try:
            run(smoke_python, "-B", ROOT / "tools" / "mvp-game-test" / "run_local_smoke.py",
                "--package", package, cwd=ROOT)
        except (OSError, subprocess.CalledProcessError) as exc:
            parser.exit(1, f"Built {package}, but launch smoke failed: {exc}\n")


if __name__ == "__main__":
    main()
