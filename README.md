# MVP2005 Modern

Compatibility, widescreen, and modding-layer work for a user-owned PC installation of **MVP Baseball 2005** on modern Windows.

## Compatibility status

The Windows 11 compatibility layer is now at **RC1**. The behavior validated during the v16 test series is frozen as the reference baseline:

- MVP Baseball 2005 launches on modern Windows with the original SafeDisc flow handled by SafeDiscShim.
- dgVoodoo2 provides the Direct3D 8 / DirectDraw compatibility layer.
- the MVP-specific runtime patches high-resolution modes and widescreen projection;
- the game runs true borderless instead of exclusive fullscreen;
- frontend/menu mouse coordinates map correctly across the full display;
- gameplay mouse coordinates use the game's native/raw mapping;
- repeated menu -> gameplay -> menu transitions restore the correct input mode automatically;
- Alt-Tab works normally without MVP minimizing itself or stealing focus back;
- the upstream large-drive save fix remains enabled.

The final known-good development build before cleanup is preserved by Git history at commit:

`a7e2342b7464faa223c7d4e91b26f3d3b88db6f3`

## Required dgVoodoo settings

The validated true-borderless configuration uses:

```ini
[General]
FullScreenMode = false

[DirectX]
AppControlledScreenMode = false
```

The launcher owns the tested MVP-specific dgVoodoo profile, including the settings above, so users do not need to configure them manually.

## Runtime configuration

The MVP2005 Modern launcher automatically enables the custom borderless runtime and writes resolution/widescreen settings. For a 16:9 output, the tested horizontal projection scale is `0.75`.

Debug logging should normally be left off. It can be enabled in `mvp2005fix.ini` when diagnosing a compatibility problem:

```ini
[Debug]
Logging=1
```

## Production runtime

`patches/apply_production_rc1.py` is the canonical RC1 build entry point. It assembles the proven v16 behavior, removes experiment-only probes/log spam, verifies the critical compatibility hooks, and leaves the older development patches in Git history as rollback material.

GitHub Actions pins upstream `ostrich/mvp2005fix` at:

`1c0dae9b030a8fb66648655c8d14043af1ead676`

The standalone compatibility artifact is:

`mvp2005modern-compatibility-rc1-x86`

## All-in-one launcher

The product goal is **one launcher that can start from a normal user-owned MVP Baseball 2005 installation on a machine that does not already have SafeDiscShim or dgVoodoo2 configured**.

Current launcher layers:

- `apply_modern_launcher_v1.py` — core configuration UI;
- `apply_modern_launcher_v2.py` — automatic SafeDiscShim/dgVoodoo setup and repair;
- `apply_modern_launcher_v3.py` / `apply_skip_intro_runtime_v3.py` — experimental intro-skip work retained but disabled in the visible launcher;
- `apply_controller_configurator_v4.py` — integrated DirectInput/controller.cfg support;
- `apply_controller_configurator_v5.py` — calibration-first press-to-bind controller setup.

The launcher can detect/install the pinned compatibility dependencies, configure the verified RC1 runtime, select resolution/widescreen settings, configure controllers, and launch MVP through the verified injection path.

### Controller configurator v0.5

MVP Baseball 2005 stores controller profiles in `Documents\MVP Baseball 2005\controller.cfg`. Modern controllers can expose different DirectInput button orders depending on the controller, connection method, driver and middleware, so v0.5 no longer expects users to understand or guess button numbers.

The recommended flow is:

1. select the connected controller;
2. choose the Xbox-style or generic stick/trigger representation;
3. click **Calibrate by pressing buttons...**;
4. press A, B, X, Y, LB, RB, View/Back, Menu/Start, L3 and R3 when prompted;
5. click **Save to MVP**.

The launcher polls the selected DirectInput device and records the physical button IDs it actually receives. Numeric IDs remain visible only as an advanced/reference view because `controller.cfg` ultimately stores numbered buttons.

The calibration prompts explain the main MVP use of each physical control. For the generated Xbox-style mapping:

- A — confirm, normal swing, pitch 1, throw home;
- B — back, pitch 2, throw first;
- X — bunt, pitch 3, throw third;
- Y — pitch 4, throw second;
- LB — relay/shoulder action;
- RB — pitch 5 and fielder switch;
- View/Back — select;
- Menu/Start — pause/menu;
- L3 / R3 — stick-click actions.

The legacy Xbox 360 and generic DirectInput presets remain available as quick-start fallbacks, but the UI explicitly recommends calibration because button ordering can vary on current hardware/software stacks.

Saving replaces only the selected controller profile while preserving other profiles in `controller.cfg`. The original file is backed up once as `controller.cfg.mvp2005modern.bak`.

### Intro videos

Intro-video skipping is deferred. The earlier checkbox is hidden and normal launcher saves force the experimental setting off. The compatibility/runtime baseline is unaffected.

### Automatic compatibility setup

On Launch or **Setup / Repair**, MVP2005 Modern handles:

- **SafeDiscShim v0.9.0** — when missing, download the official release, verify SHA-256, request the required UAC elevation, and install it while preserving the original SafeDisc/media verification flow;
- **dgVoodoo2 v2.87.5** — when missing/incomplete, download the official release, verify SHA-256, install the x86 D3D8/DirectDraw wrapper files beside the game, back up existing compatibility files, and apply the known-good MVP configuration;
- **MVP2005 Modern RC1 runtime** — the bundled runtime provides high resolution, widescreen, true borderless, correct menu/gameplay mouse handling and fixed Alt-Tab behavior.

Pinned external downloads:

- SafeDiscShim v0.9.0 installer — SHA-256 `b4c355ec63047a09c20c286c083fcad1031d47a2c17eac0de12b96d377ec369f`
- dgVoodoo2 v2.87.5 release ZIP — SHA-256 `5ffde6927f7355ca3fdd5d785b581256a8e6539fa13e395a891ade6ba1040850`

The clean-machine path is intentionally supported in code but still needs a real-world test on Windows 10/11 with neither dependency already present.

## Components

- **SafeDiscShim** — compatibility for the original game's SafeDisc launch flow.
- **dgVoodoo2** — modern Direct3D/DirectDraw wrapper.
- **mvp2005fix** — upstream resolution, widescreen and large-drive compatibility work.
- **MVP2005 Modern runtime patches** — true borderless presentation, phase-aware mouse handling, Alt-Tab behavior and MVP-specific integration.
- **MVP2005 Modern launcher** — automatic setup, path, resolution, controller and compatibility configuration, with profiles/mod management planned on top.

No MVP Baseball 2005 game files, copyrighted EA/MLB assets, no-CD executable, or DRM bypass are distributed by this repository.

## Next phase

After controller calibration and clean-machine dependency setup are tested, the next work is profile/mod management: isolated profiles, backup/restore, file manifests, activation/deactivation and presets such as Vanilla, modern rosters and Total Classics while keeping the base installation recoverable.
