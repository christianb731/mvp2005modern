# MVP2005 Modern

Compatibility, widescreen, and modding-layer work for a user-owned PC installation of **MVP Baseball 2005** on modern Windows.

## Current development target

The current branch is focused on adding true borderless fullscreen at the Direct3D 8 device layer while preserving the already-working stack:

- SafeDiscShim for SafeDisc compatibility
- dgVoodoo2 for legacy Direct3D/DirectDraw compatibility
- `mvp2005fix` for resolution, widescreen projection correction, and large-drive save handling

The previous dgVoodoo-only borderless experiments were intentionally abandoned because they broke MVP's legacy 640x480 menu/scaling behavior. The current approach modifies the existing `mvp2005fix` Direct3D 8 hooks instead.

## Borderless design

When `[Borderless] Enabled=1` is present in `mvp2005fix.ini`, the custom runtime:

1. intercepts `IDirect3D8::CreateDevice`;
2. switches the presentation parameters to windowed mode;
3. uses the current desktop display format for the windowed backbuffer;
4. clears the fullscreen refresh-rate field;
5. converts the device window to a monitor-sized frameless popup;
6. hooks `IDirect3DDevice8::Reset` and reapplies the same rules when MVP changes presentation state.

The dgVoodoo configuration stays on the known-good fullscreen-compatible baseline instead of using dgVoodoo's fake/windowed fullscreen features.

## Build

GitHub Actions clones the known upstream `ostrich/mvp2005fix` revision, applies `patches/apply_borderless.py`, builds with the upstream MinGW Makefile, and uploads a Windows x86 artifact containing `mvp2005fix.exe` and `mvp2005fix.dll`.

Pinned upstream revision:

`1c0dae9b030a8fb66648655c8d14043af1ead676`

No MVP Baseball 2005 game files are included or distributed by this repository.
