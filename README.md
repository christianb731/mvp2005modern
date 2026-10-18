# MVP2005 Modern

Compatibility, widescreen, controller, and launcher work for a user-owned PC installation of **MVP Baseball 2005** on modern Windows.

MVP2005 Modern does **not** distribute `mvp2005.exe`, game assets, a no-CD executable, or a DRM bypass. The original SafeDisc/media verification flow remains in use through SafeDiscShim.

## Current status

The Windows 11 compatibility runtime is at the verified **RC1** baseline. The current launcher preview is **v0.33**, with the v0.32 controller behavior intentionally frozen.

Verified runtime behavior:

- MVP Baseball 2005 launches on modern Windows with the original SafeDisc flow handled by SafeDiscShim;
- dgVoodoo2 provides the Direct3D 8 / DirectDraw compatibility layer;
- high-resolution modes and true widescreen projection work;
- the game runs true borderless rather than exclusive fullscreen;
- frontend/menu and gameplay mouse coordinates are handled separately and correctly;
- repeated menu -> gameplay -> menu transitions recover input correctly;
- Alt-Tab works without MVP minimizing itself or stealing focus back;
- the upstream large-drive save fix remains enabled.

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
6. Choose a resolution and click **Launch Game**.

The launcher keeps its own configuration in `mvp2005fix.ini` beside `MVP2005Modern.exe`.

## v0.33 setup cleanup

v0.33 makes the compatibility setup path more suitable for normal installations, especially when MVP Baseball 2005 is installed under `Program Files`.

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

The launcher disables Windows file virtualization and probes the **real** selected game directory. If that directory is not writable, only the local dgVoodoo repair step is relaunched with administrator rights. The whole launcher does not need to run elevated.

After the elevated helper returns, the parent launcher verifies that the expected files and validated dgVoodoo settings are actually present in the real game folder instead of trusting only the helper's exit code.

### Setup health display

The launcher now reports useful setup state instead of a generic compatibility message, including:

- SafeDiscShim missing;
- dgVoodoo wrapper files missing;
- dgVoodoo present but not using the validated MVP profile;
- compatibility stack ready.

The v0.33 clean-machine path is compiled and CI-tested, but it should still be treated as a preview until it has been exercised on a fresh Windows 10/11 machine with neither external dependency preinstalled.

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

For a 16:9 output, the tested horizontal projection scale is `0.75`. Resolution, widescreen, borderless mode, and the large-drive save fix are written through the launcher.

General runtime logging is normally off and can be enabled with:

```ini
[Debug]
Logging=1
```

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

Normal play no longer creates the very large controller diagnostic log. It is opt-in with:

```ini
[ControllerDebug]
Logging=1
```

The integrated **Controller Setup** window remains available for generating/editing an MVP `controller.cfg`, but users with a working v0.32 learned setup should not recalibrate just for normal use.

## Intro videos

Intro-video skipping is deferred. The visible launcher option remains removed/disabled, normal settings saves do not modify the movie files, and the compatibility runtime does not depend on intro skipping.

## Pinned external components

- **SafeDiscShim v0.9.0 installer** — SHA-256 `b4c355ec63047a09c20c286c083fcad1031d47a2c17eac0de12b96d377ec369f`
- **dgVoodoo2 v2.87.5 release ZIP** — SHA-256 `5ffde6927f7355ca3fdd5d785b581256a8e6539fa13e395a891ade6ba1040850`

## Components

- **SafeDiscShim** — compatibility for the original game's SafeDisc launch flow;
- **dgVoodoo2** — modern Direct3D/DirectDraw wrapper;
- **mvp2005fix** — upstream resolution, widescreen, and large-drive compatibility work;
- **MVP2005 Modern runtime patches** — true borderless presentation, phase-aware mouse handling, Alt-Tab fixes, and controller translation;
- **MVP2005 Modern launcher** — setup verification/repair, path detection, resolution, controller configuration, and launch orchestration.

## Repository build structure

`patches/apply_production_rc1.py` is the compatibility-runtime baseline. The launcher/controller work is currently layered afterward by the build workflow so the history of experiments remains reproducible.

The next cleanup step is to consolidate the proven launcher/controller patches into a smaller production patch set once v0.33 has been exercised on Windows. After that, the planned product work is profile/mod management: isolated profiles, baseline manifests, backup/restore, activation/deactivation, and presets such as Vanilla, modern rosters, and Total Classics while keeping the base installation recoverable.
