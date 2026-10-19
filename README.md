# MVP2005 Modern

Compatibility, widescreen, controller, launcher, and quality-of-life work for a user-owned PC installation of **MVP Baseball 2005** on modern Windows.

MVP2005 Modern does **not** distribute `mvp2005.exe`, game assets, a no-CD executable, or a DRM bypass. The original SafeDisc/media verification flow remains in use through SafeDiscShim.

## Current status

The current integrated launcher/runtime build is **v0.49**. The compatibility runtime remains based on the verified RC1 baseline, with the v0.32 controller behavior intentionally frozen and later features layered on top.

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

`patches/apply_production_rc1.py` is the compatibility-runtime baseline. The launcher/controller/features are layered afterward by the build workflow so the history of experiments remains reproducible.

The controller behavior remains frozen at v0.32; LAA is retained from v0.34; Skip Intro is retained from v0.42; and the frontend menu experiments are closed out by the v0.49 production cleanup. New work can therefore proceed from a stable integrated baseline without carrying the high-volume menu-probe hooks in normal execution.
