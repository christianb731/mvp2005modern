# MVP2005 Modern

Compatibility, widescreen, controller, launcher, and quality-of-life work for a user-owned PC installation of **MVP Baseball 2005** on modern Windows.

MVP2005 Modern does **not** distribute `mvp2005.exe`, game assets, a no-CD executable, or a DRM bypass. The original SafeDisc/media verification flow remains in use through SafeDiscShim.

## Current status

The development baseline is **v0.53**. It retains the v0.49 native frontend policy and v0.32 gameplay controller behavior. The aspect-fit menu, menu input diagnostics, and named texture packs are separate preview profiles.

Verified behavior includes:

- MVP Baseball 2005 launches on modern Windows with the original SafeDisc flow handled by SafeDiscShim;
- dgVoodoo2 provides the Direct3D 8 / DirectDraw compatibility layer;
- high-resolution modes and true widescreen projection work during gameplay;
- the game runs true borderless rather than exclusive fullscreen;
- the frontend remains on MVP's stable native 800x600 render path and is scaled to the borderless client by the compatibility/presentation layer;
- frontend/menu and gameplay mouse coordinates are handled separately and correctly;
- repeated menu -> gameplay -> menu transitions recover input correctly;
- Alt-Tab works without MVP minimizing itself or stealing focus back;
- the upstream large-drive save fix remains enabled;
- optional Large Address Aware support gives the 32-bit game access to the larger user virtual-address space on 64-bit Windows;
- Skip Intro automatically advances through the EA Sports and MVP startup movies without modifying the installed movie files.

The final known-good pre-cleanup compatibility runtime is preserved in Git history at:

`a7e2342b7464faa223c7d4e91b26f3d3b88db6f3`

GitHub Actions pins upstream `ostrich/mvp2005fix` at:

`1c0dae9b030a8fb66648655c8d14043af1ead676`

## Quick start

1. Install MVP Baseball 2005 from your original media.
2. Put `MVP2005Modern.exe` and `mvp2005fix.dll` together in a normal writable folder.
3. Run `MVP2005Modern.exe`.
4. Let the launcher reuse the detected/remembered installation, or browse to the original `mvp2005.exe`.
5. Click **Verify / Repair** once.
6. Choose a resolution and optional features such as Large Address Aware and Skip Intro.
7. Click **Launch Game**.

The launcher keeps its own configuration in `mvp2005fix.ini` beside `MVP2005Modern.exe`.

## Compatibility setup

### Verify / Repair

**SafeDiscShim v0.9.0**

- detects the installed SafeDiscShim environment;
- downloads only the pinned official installer when needed;
- verifies the installer SHA-256 before execution;
- uses the normal Windows UAC elevation flow;
- distinguishes a canceled UAC prompt from a generic installation failure;
- keeps MVP's original disc/media verification requirement intact.

**dgVoodoo2 v2.87.5**

- downloads the pinned official release ZIP when files are missing or a forced repair is requested;
- verifies the ZIP SHA-256 before extraction;
- installs the x86 `D3D8.dll`, `DDraw.dll`, and `D3DImm.dll` beside `mvp2005.exe`;
- backs up pre-existing compatibility files once under `MVP2005Modern.Backup\compatibility`;
- applies and verifies the known-good MVP-specific dgVoodoo configuration.

### Protected game folders

The launcher disables Windows file virtualization and probes the **real** selected game directory. If that directory is not writable, only the local repair step that requires access is relaunched with administrator rights. The whole launcher does not need to run elevated.

After an elevated helper returns, the parent launcher verifies that the expected files/settings are actually present instead of trusting only the helper's exit code.

## Required dgVoodoo profile

The validated MVP setup includes these important settings:

```ini
[General]
OutputAPI = bestavailable
FullScreenMode = false
ScalingMode = stretched
KeepWindowAspectRatio = false
CaptureMouse = false
CenterAppWindow = false

[GeneralExt]
FreeMouse = false

[DirectX]
DisableAndPassThru = false
VideoCard = geforce_9800_gt
VRAM = 1024
Resolution = unforced
AppControlledScreenMode = false
DisableAltEnterToToggleScreenMode = true
ForceVerticalSync = false
dgVoodooWatermark = false

[DirectXExt]
DefaultEnumeratedResolutions = all
```

The launcher owns these tested MVP-specific compatibility settings so users do not need to configure dgVoodoo manually.

## Runtime configuration

For a 16:9 gameplay output, the tested horizontal projection scale is `0.75`. Resolution, widescreen, borderless mode, the large-drive save fix, Large Address Aware intent, and Skip Intro are written through the launcher.

General runtime logging is normally off and can be enabled with:

```ini
[Debug]
Logging=1
```

## Frontend menus

The widescreen-menu experiments from v0.43 through v0.48 are retired. They established that MVP's frontend is substantially more coupled to its original 800x600 assumptions than gameplay and that forcing an HD frontend render target/viewport creates layout and lifecycle problems for limited visual benefit.

The production v0.49 policy is therefore:

- keep MVP's frontend backbuffer, viewport, and orthographic projection native;
- do not rewrite frontend matrices or install the experimental SetViewport/draw-probe hooks;
- let the compatibility/presentation layer scale the completed frontend frame to the borderless client;
- map the complete client mouse coordinates back into MVP's logical 800x600 frontend space;
- leave gameplay HD/widescreen rendering unchanged.

The high-volume `MVP2005Modern-MenuScale.log` probe is no longer expected during normal use.

### Aspect-fit menu preview

Apply `patches/apply_menu_aspect_preview.py` from the generated upstream directory after the v0.53 patch stack, then rebuild the launcher and DLL. To try the preview, add `[MenuScale]` and `PreserveAspect=1` to `mvp2005fix.ini` beside the preview launcher. The game folder's `dgVoodoo.conf` needs `WindowedAttributes = borderless, fullscreensize` in `[GeneralExt]`. Use a gameplay resolution with the same aspect ratio as the monitor.

The preview scales the completed 800x600 menu proportionally inside the borderless window. It uses black bars for the extra space and maps the mouse into the fitted area. Set `PreserveAspect=0` and relaunch to restore the normal stretched presentation.

The preview launcher also exposes **Fill screen with menus**. Check it before launching to fill the window with the original menu artwork. This scales the 4:3 artwork to the display's aspect ratio. Clear it to use the proportional 4:3 fit. The launcher saves your choice in its own `mvp2005fix.ini` for the next launch.

#### Check the transition back to the menu

1. Leave the main menu idle until the **Demo Mode** banner appears. Press Esc and check that the menu or title screen returns with the 4:3 fit. In the Windows 11 test, clicking the prompt or the field left the demo running.
2. Start a separate match through **Play Now**. Once play begins, press Esc, choose **Quit**, and confirm that the main menu returns with the same proportions and that **Play Now** still responds to the mouse.

With `[Debug] Logging=1`, `mvp2005fix.log` reports the gameplay backbuffer size and `frontend render phase detected; 800x600 mouse scaling restored` on return. Check both transitions when changing how the game detects the render phase.

### Native menu input diagnostic

Build the `v0.53-menu-controls` profile and enable the trace in `mvp2005fix.ini` beside the launcher.

```ini
[Debug]
Logging=1

[MenuDebug]
TraceControls=1
TraceActions=1
```

The runtime checks the executable's x86 code signatures before installing the hooks. `TraceControls` logs handled mouse events, including Play Now through the Main Menu grid and Back and Advance through the Team Select navigation bar. The team arrows use a separate path. `TraceActions` logs active scene changes and newly observed native actions in `mvp2005fix.log`. In a `pressed_mask`, the least significant bit represents action 1. On the tested executable, the Main Menu grid scene is `004b74b0` and the scene that replaced it on entering Team Select is `004bcdb8`.

### Controller menu pilot and simulated input

In the `v0.53-menu-controls` build, add `[MenuController]` with `Enabled=1` to the launcher INI to enable the pilot. While the borderless game has focus, press A at the title screen when **Click to Start** appears. Use D-pad Up and Down to select rows and A to confirm in Main Menu, Game Modes, My MVP, and Options. Press B to go back from Game Modes, My MVP, or Options. Moving or clicking the mouse gives the pointer control again. Team Select uses the game's directional actions and its stock Back button handler.

In **Audio Options**, use Up and Down to select a volume, Left and Right to adjust it, A to accept, and B to go back. If B opens the discard-changes prompt, use D-pad Up or Down to choose No or Yes, then press A. No returns to Audio Options with the edits still pending. Yes discards the edits and returns to Options. The other Options categories still need controller coverage inside their settings screens.

The same D-pad and A controls work in the Quit confirmation after it opens from an exhibition's pause menu.

Game Modes uses the verified stock row grid at logical bounds `322,121 243x261`. D-pad navigation calls its native row selector. B queues the stock Back action so it remains available when the game's transition checks it again during the same frame. Wait for the screen's entrance animation before checking row changes.

The separate local `v0.53-menu-controller-test` profile can replace the XInput sample with one simulated button at a time. Select the isolated `MVP2005Smoke.exe` copy, enable both `[MenuController]` and `[MenuControllerTest]` with `Enabled=1`, and set `[Debug] Logging=1` for diagnostics. With the smoke game in front, write an increasing serial number, the expected screen (`title`, `main`, `modes`, `team`, `my_mvp`, `options`, `audio`, or `prompt`), and a button (`up`, `down`, `left`, `right`, `a`, or `b`) into `MVP2005Modern-MenuInput.txt` beside the launcher. Run this command from the launcher folder to simulate D-pad Down.

```powershell
Set-Content -LiteralPath .\MVP2005Modern-MenuInput.txt -Encoding ascii '1 main down'
```

Wait for the command to be logged and the screen to settle before sending the next one. The test build ignores the command already in the file at startup. The log records accepted and rejected commands, the Main Menu row, and actions that reach the native dispatcher.

## Controller baseline

Controller work is intentionally frozen at the **v0.32 persistent live-learner baseline** rather than continuing to change fixed mappings.

On the development Flydigi Vader 3 / XInput setup, the currently usable baseline includes working face buttons, pitch 5 on RB, Start/pause behavior, fixed L3 behavior, and persisted learned mappings for the remaining controls.

Learned mappings are stored in:

```ini
[ControllerLearned]
```

and are reloaded on future launches.

The live learner remains available as a fallback for controls that need machine/controller-specific adjustment:

- `Ctrl+F1` — LB
- `Ctrl+F2` — LT
- `Ctrl+F3` — RT
- `Ctrl+F4` — Back/View
- press the selected physical control repeatedly to cycle candidates;
- `Ctrl+Enter` — lock and persist the candidate that works;
- `Ctrl+Backspace` — clear the selected learned mapping.

Normal play no longer creates the large controller diagnostic log. It is opt-in with:

```ini
[ControllerDebug]
Logging=1
```

The integrated **Controller Setup** window remains available for generating/editing an MVP `controller.cfg`, but users with a working v0.32 learned setup should not recalibrate just for normal use.

## Large Address Aware

The launcher can enable the PE32 `IMAGE_FILE_LARGE_ADDRESS_AWARE` flag on the selected `mvp2005.exe` and keeps a one-time executable backup under `MVP2005Modern.Backup\executable` before changing it.

The launcher verifies the PE header before writing, changes only the LAA characteristics bit, and verifies the result afterward. On 64-bit Windows the validated game process receives the expanded user virtual-address range.

## Skip Intro

Skip Intro is a supported v0.42 launcher/runtime feature retained in the v0.49 integrated build.

When **Skip EA Sports / MVP intro videos** is enabled:

- the installed `easports.vp6` and `mvpintro.vp6` files are never modified;
- the runtime validates their Electronic Arts VP6/ADPCM container structure;
- short disposable cached copies are generated in `MVP2005Modern.IntroCache`;
- only the two startup movie opens are redirected to those cached files;
- one guarded automatic Skip input is sent after the first cached movie starts;
- input is sent only if an MVP window still owns the foreground;
- only one automatic input is scheduled per process, avoiding a delayed click on the main menu;
- the cursor is not moved.

Unchecking Skip Intro restores normal startup movie behavior on the next launch. The cache directory can be deleted at any time and will be regenerated from the user's installed movies when needed.

`MVP2005Modern-Intro.log` remains available for support, but the production path uses concise logging: healthy launches record only startup identity, cache-ready summaries, and final automatic-skip success. Validation failures, fallbacks, focus aborts, and input failures retain detailed diagnostics.

## Pinned external components

- **SafeDiscShim v0.9.0 installer** — SHA-256 `b4c355ec63047a09c20c286c083fcad1031d47a2c17eac0de12b96d377ec369f`
- **dgVoodoo2 v2.87.5 release ZIP** — SHA-256 `5ffde6927f7355ca3fdd5d785b581256a8e6539fa13e395a891ade6ba1040850`

## Components

- **SafeDiscShim** — compatibility for the original game's SafeDisc launch flow;
- **dgVoodoo2** — modern Direct3D/DirectDraw wrapper;
- **mvp2005fix** — upstream resolution, widescreen, and large-drive compatibility work;
- **MVP2005 Modern runtime patches** — true borderless presentation, phase-aware mouse handling, Alt-Tab fixes, controller translation, Large Address Aware diagnostics, Skip Intro, and the native frontend production policy;
- **MVP2005 Modern launcher** — setup verification/repair, path detection, resolution, controller configuration, feature settings, and launch orchestration.

## Repository build structure

Install Python 3.11+, Git, GNU Make, and an i686 MinGW toolchain. Run this command from the source folder with the toolchain on `PATH`.

```powershell
python build.py --output .build/v053-local --run-tests
```

The default profile is `v0.53`. Use a fresh output directory for each build. `--source-zip` accepts a trusted `git archive` ZIP of the pinned revision for offline builds. `--run-tests` runs the Windows x86 hook and startup fixtures after compiling them. Omit it for cross-compilation. The output ZIP contains the matching launcher, runtime DLL, upstream license, and component information.

On Windows, add `--smoke` to stage the exact new launcher and run it against the isolated smoke game. The local runner verifies the build before it launches and leaves the desktop MCP target selection in place. See [the local game-test workflow](tools/mvp-game-test/README.md) for the required fixture and the input and display tests.

The local builder and GitHub Actions use the ordered list in `patches/build-v0.53.txt`. Pass `--profile v0.53-menu-fit` for the aspect-fit menu, `--profile v0.53-menu-controls` for the menu diagnostics, `--profile v0.53-mod-manager` for ZIP mod management, or `--profile v0.55-texture-packs` for the named texture packs. Each profile starts from the same pinned upstream source.

The v0.53 build, hook tests, and startup fixtures have passed on Windows 11. The 4:3 preview has been exercised with 1920×1080 and 2560×1440 gameplay renders on a 2560×1440 desktop. The borderless mouse correction was verified at 1920×1080 on that desktop by clicking Quit in a real exhibition, confirming the prompt, and reopening Play Now from the restored 4:3 menu. A second exhibition returned successfully with menu traces enabled in the simulated-input build. Simulated D-pad, A, and B navigation worked again after that return.

A prior run with the controller pilot and menu traces enabled crashed during the return to the 800×600 frontend. Windows reported an access violation at RVA `0x003ba7e4` in the tested executable. The cause remains unconfirmed. Windows 10 validation is pending.

The controller behavior remains frozen at v0.32; LAA is retained from v0.34; Skip Intro is retained from v0.42; and the frontend menu experiments are closed out by the v0.49 production cleanup. New work can therefore proceed from a stable integrated baseline without carrying the high-volume menu-probe hooks in normal execution.
