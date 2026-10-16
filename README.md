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

Keep the rest of the working dgVoodoo configuration unchanged. In particular, MVP2005 Modern does not require dgVoodoo's fake-fullscreen/window-border tricks; the runtime owns the MVP-specific borderless behavior.

## Runtime configuration

Enable the custom borderless path in `mvp2005fix.ini`:

```ini
[Borderless]
Enabled=1
```

Resolution and widescreen scale remain configurable through the normal `mvp2005fix` settings. For a 16:9 output, the tested horizontal projection scale is `0.75`.

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

## Components

- **SafeDiscShim** — compatibility for the original game's SafeDisc launch flow.
- **dgVoodoo2** — modern Direct3D/DirectDraw wrapper.
- **mvp2005fix** — upstream resolution, widescreen and large-drive compatibility work.
- **MVP2005 Modern runtime patches** — true borderless presentation, phase-aware mouse handling, Alt-Tab behavior and MVP-specific integration.

No MVP Baseball 2005 game files, copyrighted EA/MLB assets, no-CD executable, or DRM bypass are distributed by this repository.

## Next phase

With the core compatibility behavior stabilized, development can move to the launcher and mod/profile layer: automatic setup, resolution configuration, profile switching, backups, and mod management while keeping the game installation recoverable.
