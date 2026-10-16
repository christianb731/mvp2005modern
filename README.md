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

The launcher now owns the tested MVP-specific dgVoodoo profile, including the settings above, so users do not need to configure them manually.

## Runtime configuration

Enable the custom borderless path in `mvp2005fix.ini`:

```ini
[Borderless]
Enabled=1
```

The MVP2005 Modern launcher writes this automatically. Resolution and widescreen scale remain configurable through the launcher. For a 16:9 output, the tested horizontal projection scale is `0.75`.

Debug logging should normally be left off. It can be enabled when diagnosing a compatibility problem:

```ini
[Debug]
Logging=1
```

## How the RC1 runtime works

The compatibility runtime converts MVP's D3D8 device to windowed presentation using the desktop display format and presentation interval `0`, while preserving MVP's logical rendering sizes. It then keeps the tracked game HWND monitor-sized and frameless.

MVP's frontend is logically 800x600 even when the physical client is much larger, so queued Win32 mouse coordinates are mapped from the physical client into the logical frontend coordinate space. Gameplay uses a different input interpretation, so the runtime switches to raw queued coordinates during 3D gameplay. Recent 3D projection activity is used as the phase signal; after gameplay rendering stops, the frontend mapping is restored automatically.

For true borderless Alt-Tab, MVP's legacy minimize requests are suppressed for the tracked game window. Windows is therefore free to transfer focus to another application without the old minimize/restore/refocus cycle.

## Production build

`patches/apply_production_rc1.py` is the canonical RC1 build entry point. It assembles the proven development changes, removes experiment-only probes/log spam, verifies the critical compatibility hooks, and leaves the older v7-v16 patch scripts in the repository as development history and rollback material.

GitHub Actions clones and pins upstream `ostrich/mvp2005fix` at:

`1c0dae9b030a8fb66648655c8d14043af1ead676`

It then builds the upstream x86 release and publishes the artifact:

`mvp2005modern-compatibility-rc1-x86`

## All-in-one launcher preview

The product goal is **one launcher that can start from a normal user-owned MVP Baseball 2005 installation on a machine that does not already have SafeDiscShim or dgVoodoo2 configured**.

`patches/apply_modern_launcher_v1.py` provides the base MVP2005 Modern configuration UI, `apply_modern_launcher_v2.py` adds automatic dependency setup, and `apply_modern_launcher_v3.py` migrates the intro-skip implementation to the safer runtime method.

The v0.3 launcher:

- always opens its UI instead of silently auto-launching from an existing config;
- remembers and auto-detects the selected `mvp2005.exe` path, including the retail install registry location and common Program Files paths;
- selects standard or custom resolutions and calculates the matching widescreen projection scale;
- keeps the large-drive save fix configurable;
- enables the verified RC1 borderless runtime automatically;
- detects SafeDiscShim and, when missing, downloads the official pinned v0.9.0 installer, verifies its SHA-256, requests the required Windows elevation, installs it, and makes the current launcher process use `RedirectDrvMgt` before starting the game;
- detects the local dgVoodoo2 wrapper and, when missing or repaired explicitly, downloads the official pinned v2.87.5 release, verifies its SHA-256, installs the x86 D3D8/DirectDraw components beside the game, and applies the known-good MVP profile;
- makes one-time backups of existing compatibility files under `MVP2005Modern.Backup` before replacing them during repair;
- provides a **Setup / Repair** button to explicitly re-check SafeDiscShim and refresh the pinned dgVoodoo files;
- provides **Skip EA Sports / MVP intro videos** without replacing the VP6 files. The runtime patches MVP's internal `ENABLE_FRONTEND_MOVIES` default before the game resumes. This replaces the v0.2 zero-byte VP6 method, which caused a launch crash on the verified modern setup;
- automatically restores any intro movies that v0.2 backed up under `MVP2005Modern.Backup\intro`, so upgrading from the broken file-based test is self-repairing;
- launches the game through the same verified runtime injection path as RC1.

The frontend-movie runtime patch was derived from the retail executable's own video-settings constructor. The launcher setting changes only the internal frontend-movies boolean while leaving the neighboring visual settings enabled.

External compatibility packages are downloaded directly from their official GitHub releases instead of being redistributed in the MVP2005 Modern artifact. The pinned downloads are:

- SafeDiscShim v0.9.0 installer — SHA-256 `b4c355ec63047a09c20c286c083fcad1031d47a2c17eac0de12b96d377ec369f`
- dgVoodoo2 v2.87.5 release ZIP — SHA-256 `5ffde6927f7355ca3fdd5d785b581256a8e6539fa13e395a891ade6ba1040850`

The current launcher preview build publishes:

`mvp2005modern-launcher-v0.3-x86`

The artifact contains `MVP2005Modern.exe`, `mvp2005fix.dll`, the upstream/third-party license notices, and setup notes. It does not contain MVP Baseball 2005, EA/MLB assets, dgVoodoo2 binaries, SafeDiscShim binaries, or a no-CD executable. First-time automatic setup therefore requires internet access and one UAC approval for SafeDiscShim.

The clean-machine path is intentionally supported in code now, but still needs a real-world test on a Windows 10/11 machine with neither SafeDiscShim nor dgVoodoo2 already present.

## Components

- **SafeDiscShim** — compatibility for the original game's SafeDisc launch flow. The launcher can install the official release automatically; it does not bypass the original media verification.
- **dgVoodoo2** — modern Direct3D/DirectDraw wrapper, installed/configured automatically by the launcher when needed.
- **mvp2005fix** — upstream resolution, widescreen and large-drive compatibility work.
- **MVP2005 Modern runtime patches** — true borderless presentation, phase-aware mouse handling, Alt-Tab behavior, safe intro skipping and MVP-specific integration.
- **MVP2005 Modern launcher** — integrated setup, path, resolution and compatibility configuration, with profiles/mod management planned on top.

No MVP Baseball 2005 game files, copyrighted EA/MLB assets, no-CD executable, or DRM bypass are distributed by this repository.

## Next phase

After the all-in-one launcher setup path is verified on a clean/missing-dependency installation, the next work is profile and mod management: isolated profiles, backup/restore, file manifests, activation/deactivation and eventually presets such as Vanilla, modern rosters and Total Classics without making the base installation difficult to recover.
