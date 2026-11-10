# MVP game-test MCP worker

Codex owns builds and conclusions. Use this Windows worker for repeatable runtime tests and use `mvp-ollama` for larger source, diagnostic log and decompiler reads. Use Computer Use to explore an unfamiliar screen or inspect a visual issue. Record repeatable inputs and observable outcomes in JSON once the workflow is understood.

## Build preflight

This project directory contains the maintained worker and live test definitions. Codex uses the Python environment at `C:\AI\mvp-game-test`. Run `setup.ps1` from this directory for a new installation, and install the MCP block from `codex-config-template.toml`. The base tests require Windows and an interactive, unlocked desktop. Virtual Xbox input additionally needs `setup.ps1 -EnableVirtualGamepad` and a working ViGEm driver.

Choose the exact launcher build first. Its `mvp2005fix.ini` must already point to the intended isolated `.build\smoke-game\MVP2005Smoke.exe` and its runtime DLL must be beside it. Keep a fixed smoke launcher directory for repeat builds when practical. When the launcher moves, run this from the project directory with the intended build path:

```powershell
py -3.11 tools\mvp-game-test\set_test_target.py .build\phase-one-test-v2\smoke-launcher\MVP2005Modern.exe
```

The helper updates the launcher, its working directory and the exact two-path allowlist in Codex's config. Add `--check` to preview. Reload Codex after a config change, then call `game_test_info`. Confirm the exact launcher and game and check the reported stale process list. A rerun with the same paths just needs the preflight. The worker refuses a fresh launch if it sees a running MVP process with a known executable name. Use `close_game` for current allowlisted instances or close an older build yourself after verifying its path.

The worker reads the Modern launcher INI and verifies the executable shown in the UI before clicking **Launch Game**. It waits for the newly started, exact game executable, including when the launcher has already exited. `game_status` shows process identity and geometry. Generic direct launch is available for explicitly configured direct-game checks.

## Current smoke suite

| Test | Evidence |
| --- | --- |
| `launch_smoke` | Fresh runtime load, the two borderless D3D8 startup device creations, and a captionless game client matching the monitor |
| `main_menu_navigation` | A client-relative Click to Start action, native title-control dispatch, the Main Menu scene and its initial grid row |
| `controller_menu_navigation` | The isolated menu provider's acknowledgements, Main Menu row changes, Team Select, and the native Back handler |
| `controller_title_navigation` | Simulated controller input from Click to Start through Play Now and back from Team Select |
| `controller_game_modes_navigation` | Game Modes row changes and screenshots, Exhibition entry, and the controller Back route |
| `controller_audio_options_navigation` | My MVP and Options navigation, Audio Options row selection, volume change and restoration screenshots, and the return route |
| `controller_gameplay_options_navigation` | Gameplay Options value change, scrolling beyond the first page, discard confirmation, and Accept |
| `controller_gameplay_tuning_navigation` | Difficulty changes with both bumpers, slider adjustment, scrolling, and discard confirmation |
| `controller_video_options_navigation` | Video setting changes, the stock Auto-Detect action, discard confirmation, and Accept |
| `controller_discard_prompt` | Both answers in the Audio Options discard prompt and screenshots of the kept and discarded edit |
| `controller_pause_quit_prompt` | Controller confirmation of the pause menu's Quit prompt and the return to Main Menu from a real 1920×1080 exhibition |
| `game_modes_mouse_navigation` | Stock Game Modes hover selection and Back with the controller pilot enabled |
| `native_keyboard_navigation` | Native action trace after a keyboard input in Team Select |
| `hardware_controller_navigation` | An operator's fresh D-pad Right press in the first XInput slot and the corresponding native action in Team Select |

Run one with `run_game_test` using its name or `.json` filename. These cases target the current borderless smoke profile with intro skipping and menu tracing. Enable `[Debug] Logging=1` and `[MenuDebug] TraceActions=1`. Grid and simulated controller checks also need the test build with `[MenuController] Enabled=1` and `[MenuControllerTest] Enabled=1`. The simulated controller test requires `MVP_GAME_MENU_TEST=1` in the MCP environment. It exercises the game's menu dispatch and does not require a virtual pad.

For the hardware case, select the trace-enabled hardware build with `[MenuController] Enabled=1`, `[Controller] RemapEnabled=1` and simulated menu input disabled. Use the local runner to see its operator prompt, then press and release D-pad Right once in Team Select. XInput identifies a slot. The operator supplies the physical device.

## Local build smoke and display matrix

On Windows, add `--smoke` to `build.py` to stage the exact new ZIP beside the output and run `launch_smoke`. The worker comes from the project and uses the Python executable configured for `mvp-game-test`. Pass `--smoke-python` to select a different environment with the same dependencies.

```powershell
python build.py --output .build\my-smoke-build --run-tests --smoke
```

The output directory must be a direct child of the `.build` directory containing the isolated `smoke-game` fixture. For an already staged launcher, run `run_local_smoke.py --launcher <exact-launcher> --test <test-name>` with the worker's Python. The local runner checks the exact launcher, INI, game and stale processes using the same preflight as MCP. It pins those paths for its own process. Use `set_test_target.py` separately to change the desktop MCP target.

The three `display_*` tests use the local `v0.53-smoke-display-test` build. Build it in a separate nested `.build` directory containing a copy of the smoke game and its wrapper files, then run `run_local_smoke.py --package <that-build-zip> --display-matrix`. For a staged launcher, use `--launcher` instead of `--package`. Use `--display-mode windowed`, `borderless`, or `fullscreen` to rerun one profile. The runner restores the fixture INI and wrapper config afterward.

Windowed QA requests a windowed D3D8 device and a captioned client. The other profiles exercise Modern borderless and dgVoodoo fullscreen. Tests verify the wrapper settings, fresh runtime startup, and the game window style and bounds. Fullscreen can temporarily change the desktop resolution. The geometry check does not certify exclusive display ownership.

## Authoring tests

Use a flat JSON file under `tests\` with a short `description` and a `steps` array. A test starts with one `launch` and the worker closes its own instances afterward. Set `force_cleanup: true` only for the isolated smoke target. It allows termination of verified run-owned processes after a graceful close times out, which the shipped smoke tests need. Use `capture_on_failure: true` to retain a screenshot when the game client is still safely visible.

- `wait_window` waits for the game. `assert_window` checks `client_size`, `caption` or `monitor_fill`.
- `assert_display_profile` checks the QA mode, its wrapper settings and window geometry.
- `wait_log` waits for a literal `contains` string from `source` (`runtime`, `intro` or `laa`). Matching consumes fresh lines in order. The intro log is recreated at startup. Use separate checks for readiness and for the outcome of an input.
- `wait_pixels` checks a short list of `[relative_x, relative_y, red, green, blue]` samples in memory. The menu tests use it to wait for **Click to Start** because the front-end scene is logged before the button renders. Native dispatch and scene logs still determine the outcome.
- `key_press` and paired `key_down` / `key_up` send supported keys. `click` and `move_cursor` take client pixels, or fractions from 0 through 1 with `relative: true`. Covered or off-screen points fail.
- `pad_button` and `pad_stick` require `virtual_pad: true` in the launch step so the device exists during enumeration. `menu_input` uses the isolated launcher's fixed command file and validates the current run's serial acknowledgement. Supported scenes are `main`, `team` and `menu`.
- `focus`, bounded `wait`, named `screenshot`, and final `close` are available for workflows that need them.

Results show the exact build, recent checks, and the failing step with available process, window and fresh log details. Screenshot capture is opt-in. Use `vision_check` and `vision_compare` for manual visual questions. Vision is advisory and has no effect on scripted verdicts. The screenshot tools capture the visible desktop client region and reject common obstructions. Use Computer Use if the client is clipped, covered or impossible to focus.

Run the worker's focused checks from this directory with `C:\AI\mvp-game-test\.venv\Scripts\python.exe -B -m unittest -v test_worker`. These checks cover path and process boundaries, script validation, fresh log parsing, and config updates.
