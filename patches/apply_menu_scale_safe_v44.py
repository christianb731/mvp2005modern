from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"menu scale v44 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"menu scale v44 {label}: expected exactly one match, found {count}")
    text = updated


# v0.43 crashed immediately after hook installation. Its Present and SetViewport
# paths queried additional COM objects before their first call-level log, so the
# log could not identify which query failed. v0.44 deliberately removes every
# new v0.43 device hook except SetViewport and performs no nested COM queries.
#
# The first behavioral attempt is now internally coherent: when the frontend
# creates/resets an 800x600 backbuffer, expand that backbuffer to the configured
# output resolution through the already-proven CreateDevice/Reset path, while
# preserving borderless_logical_width/height=800x600 for mouse/UI logic. Then
# expand only matching FRONTEND 800x600 SetViewport calls to the same target.
# Gameplay-phase viewport calls are untouched.

replace_once(
    'MVP2005 Modern v0.43 frontend menu scaling probe',
    'MVP2005 Modern v0.44 safe frontend menu scaling probe',
    'diagnostic header',
)
replace_once(
    'experiment=expand frontend 800x600 viewport only when active render target is larger; gameplay untouched',
    'experiment=frontend 800x600 backbuffer+viewport -> configured output using only proven CreateDevice/Reset plus SetViewport; gameplay viewport untouched',
    'diagnostic description',
)

# Forward declarations are needed by the earlier borderless CreateDevice/Reset
# helpers. v0.43 already declares menu_diag_note_matrix at this location.
replace_once(
'''static void menu_diag_note_matrix(DWORD register_address, const void *constant_data, DWORD constant_count);\n\nstatic HRESULT WINAPI fake_SetVertexShaderConstant(void *self, DWORD register_address,\n''',
'''static void menu_diag_note_matrix(DWORD register_address, const void *constant_data, DWORD constant_count);\nstatic void menu_diag_ensure_open(void);\nstatic void menu_diag_logf(const char *fmt, ...);\n\nstatic HRESULT WINAPI fake_SetVertexShaderConstant(void *self, DWORD register_address,\n''',
'menu diagnostic forward declarations',
)

# Expand only the known frontend logical mode. Capture of borderless_logical_*
# happens immediately before this point, so mouse conversion remains 800x600.
create_old = '''    borderless_logical_width = pp->BackBufferWidth;\n    borderless_logical_height = pp->BackBufferHeight;\n\n    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : focus_window;\n'''
create_new = '''    borderless_logical_width = pp->BackBufferWidth;\n    borderless_logical_height = pp->BackBufferHeight;\n\n    if (menu_scale_enabled && borderless_logical_width == 800 &&\n        borderless_logical_height == 600 && menu_scale_target_width >= 800 &&\n        menu_scale_target_height >= 600 &&\n        (menu_scale_target_width != 800 || menu_scale_target_height != 600)) {\n        menu_diag_ensure_open();\n        menu_diag_logf("CREATEDEVICE FRONTEND BACKBUFFER before=%ux%u after=%ux%u logical_kept=800x600",\n            (unsigned int)pp->BackBufferWidth, (unsigned int)pp->BackBufferHeight,\n            (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height);\n        pp->BackBufferWidth = menu_scale_target_width;\n        pp->BackBufferHeight = menu_scale_target_height;\n    }\n\n    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : focus_window;\n'''
if text.count(create_old) < 1:
    raise SystemExit('menu scale v44 CreateDevice logical capture not found')
text = text.replace(create_old, create_new, 1)

# Apply the same rule to frontend resets. This is scoped to the first matching
# occurrence after prepare_borderless_reset so the CreateDevice block above is
# not modified twice.
reset_marker = 'static void prepare_borderless_reset(void *presentation_parameters)\n'
reset_pos = text.find(reset_marker)
if reset_pos < 0:
    raise SystemExit('menu scale v44 reset marker not found')
head = text[:reset_pos]
tail = text[reset_pos:]
reset_old = '''    borderless_logical_width = pp->BackBufferWidth;\n    borderless_logical_height = pp->BackBufferHeight;\n\n    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : borderless_window;\n'''
reset_new = '''    borderless_logical_width = pp->BackBufferWidth;\n    borderless_logical_height = pp->BackBufferHeight;\n\n    if (menu_scale_enabled &&\n        InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0 &&\n        borderless_logical_width == 800 && borderless_logical_height == 600 &&\n        menu_scale_target_width >= 800 && menu_scale_target_height >= 600 &&\n        (menu_scale_target_width != 800 || menu_scale_target_height != 600)) {\n        menu_diag_ensure_open();\n        menu_diag_logf("RESET FRONTEND BACKBUFFER before=%ux%u after=%ux%u logical_kept=800x600",\n            (unsigned int)pp->BackBufferWidth, (unsigned int)pp->BackBufferHeight,\n            (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height);\n        pp->BackBufferWidth = menu_scale_target_width;\n        pp->BackBufferHeight = menu_scale_target_height;\n    }\n\n    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : borderless_window;\n'''
if tail.count(reset_old) != 1:
    raise SystemExit(f'menu scale v44 Reset logical capture expected one match, found {tail.count(reset_old)}')
tail = tail.replace(reset_old, reset_new, 1)
text = head + tail

# SetViewport must log before doing anything except reading primitive globals.
# No GetRenderTarget/GetBackBuffer/GetViewport or surface calls are made here.
replace_regex_once(
    r'''static HRESULT WINAPI menu_fake_SetViewport\(void \*self, const D3DViewport8MenuLocal \*viewport\)\n\{.*?\n\}\n\n(?=static HRESULT WINAPI menu_fake_GetViewport)''',
    r'''static HRESULT WINAPI menu_fake_SetViewport(void *self, const D3DViewport8MenuLocal *viewport)
{
    D3DViewport8MenuLocal adjusted;
    const D3DViewport8MenuLocal *to_send = viewport;
    int gameplay = InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0;
    int candidate = 0;
    int applied = 0;
    HRESULT hr;
    LONG n;

    menu_diag_ensure_open();
    n = InterlockedIncrement(&menu_viewport_log_count);
    menu_diag_logf(
        "SETVIEWPORT ENTER n=%ld phase=%s ptr=%p in=%lu,%lu %lux%lu z=%.3f..%.3f logical=%ux%u target=%ux%u",
        (long)n, gameplay ? "GAMEPLAY" : "FRONTEND", viewport,
        viewport ? (unsigned long)viewport->X : 0UL,
        viewport ? (unsigned long)viewport->Y : 0UL,
        viewport ? (unsigned long)viewport->Width : 0UL,
        viewport ? (unsigned long)viewport->Height : 0UL,
        viewport ? viewport->MinZ : 0.0f, viewport ? viewport->MaxZ : 0.0f,
        (unsigned int)borderless_logical_width, (unsigned int)borderless_logical_height,
        (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height);

    if (viewport && !gameplay && viewport->X == 0 && viewport->Y == 0 &&
        viewport->Width == 800 && viewport->Height == 600) {
        candidate = 1;
        if (menu_scale_enabled && menu_scale_target_width >= 800 &&
            menu_scale_target_height >= 600 &&
            (menu_scale_target_width != 800 || menu_scale_target_height != 600)) {
            adjusted = *viewport;
            adjusted.Width = menu_scale_target_width;
            adjusted.Height = menu_scale_target_height;
            to_send = &adjusted;
            applied = 1;
            InterlockedIncrement(&menu_scale_apply_count);
        }
    }

    hr = menu_real_SetViewport ? menu_real_SetViewport(self, to_send) : E_FAIL;
    menu_diag_logf(
        "SETVIEWPORT EXIT n=%ld candidate=%d applied=%d out=%lux%lu hr=0x%08lx",
        (long)n, candidate, applied,
        to_send ? (unsigned long)to_send->Width : 0UL,
        to_send ? (unsigned long)to_send->Height : 0UL,
        (unsigned long)hr);
    return hr;
}

''',
    'safe SetViewport wrapper',
)

# v0.43's Present diagnostics made nested COM calls before emitting PRESENT.
# Revert to the proven production Present behavior and add only primitive-state
# logging. This guarantees a PRESENT ENTER line before the original method call.
replace_regex_once(
    r'''static HRESULT WINAPI fake_Present\(void \*self, const RECT \*source_rect,\n    const RECT \*dest_rect, HWND dest_window_override, const RGNDATA \*dirty_region\)\n\{.*?\n\}\n\n(?=static HRESULT WINAPI fake_Reset)''',
    r'''static HRESULT WINAPI fake_Present(void *self, const RECT *source_rect,
    const RECT *dest_rect, HWND dest_window_override, const RGNDATA *dirty_region)
{
    HRESULT hr;
    LONG n = InterlockedIncrement(&menu_present_log_count);
    if (n <= 240 || (n % 120) == 0) {
        RECT client;
        int have_client = borderless_window && GetClientRect(borderless_window, &client);
        menu_diag_ensure_open();
        menu_diag_logf(
            "PRESENT ENTER n=%ld phase=%s logical=%ux%u target=%ux%u client=%s%ldx%ld src=%p dst=%p override=%p scale_applies=%ld",
            (long)n,
            InterlockedCompareExchange(&gameplay_input_phase, 0, 0) ? "GAMEPLAY" : "FRONTEND",
            (unsigned int)borderless_logical_width, (unsigned int)borderless_logical_height,
            (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height,
            have_client ? "" : "UNKNOWN/",
            have_client ? client.right - client.left : 0,
            have_client ? client.bottom - client.top : 0,
            source_rect, dest_rect, dest_window_override,
            (long)InterlockedCompareExchange(&menu_scale_apply_count, 0, 0));
    }
    enforce_borderless_at_present();
    hr = real_Present ? real_Present(self, source_rect, dest_rect,
        dest_window_override, dirty_region) : E_FAIL;
    if (n <= 32)
        menu_diag_logf("PRESENT EXIT n=%ld hr=0x%08lx", (long)n, (unsigned long)hr);
    return hr;
}

''',
    'safe Present wrapper',
)

# Keep only the known production hooks plus SetViewport. Every other v0.43 hook
# remains compiled but inert, making rollback/diagnostic comparison easy.
replace_once(
'''        int reset_ok, present_ok, viewport_ok, getviewport_ok, rt_ok, copy_ok;\n        int texture_ok, create_rt_ok, image_ok, shader_ok, constants_ok, stream_ok;\n''',
'''        int reset_ok, present_ok, viewport_ok, shader_ok, constants_ok, stream_ok;\n''',
'menu hook variables',
)

replace_once(
'''        reset_ok = patch_vtable_slot(vtbl, 14, fake_Reset, (void **)&real_Reset);\n        present_ok = patch_vtable_slot(vtbl, 15, fake_Present, (void **)&real_Present);\n        texture_ok = patch_vtable_slot(vtbl, 20, menu_fake_CreateTexture, (void **)&menu_real_CreateTexture);\n        create_rt_ok = patch_vtable_slot(vtbl, 25, menu_fake_CreateRenderTarget, (void **)&menu_real_CreateRenderTarget);\n        image_ok = patch_vtable_slot(vtbl, 27, menu_fake_CreateImageSurface, (void **)&menu_real_CreateImageSurface);\n        copy_ok = patch_vtable_slot(vtbl, 28, menu_fake_CopyRects, (void **)&menu_real_CopyRects);\n        rt_ok = patch_vtable_slot(vtbl, 31, menu_fake_SetRenderTarget, (void **)&menu_real_SetRenderTarget);\n        viewport_ok = patch_vtable_slot(vtbl, 40, menu_fake_SetViewport, (void **)&menu_real_SetViewport);\n        getviewport_ok = patch_vtable_slot(vtbl, 41, menu_fake_GetViewport, (void **)&menu_real_GetViewport);\n        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);\n''',
'''        reset_ok = patch_vtable_slot(vtbl, 14, fake_Reset, (void **)&real_Reset);\n        present_ok = patch_vtable_slot(vtbl, 15, fake_Present, (void **)&real_Present);\n        viewport_ok = patch_vtable_slot(vtbl, 40, menu_fake_SetViewport, (void **)&menu_real_SetViewport);\n        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);\n''',
'safe menu hook set',
)

replace_once(
'''        menu_diag_ensure_open();\n        menu_diag_logf(\n            "HOOKS reset=%d present=%d texture=%d create_rt=%d image=%d copy=%d set_rt=%d set_vp=%d get_vp=%d shader=%d constants=%d stream=%d",\n            reset_ok, present_ok, texture_ok, create_rt_ok, image_ok, copy_ok, rt_ok,\n            viewport_ok, getviewport_ok, shader_ok, constants_ok, stream_ok);\n        if (reset_ok && present_ok && viewport_ok && getviewport_ok && rt_ok && copy_ok &&\n            texture_ok && create_rt_ok && image_ok && shader_ok && constants_ok && stream_ok) {\n''',
'''        menu_diag_ensure_open();\n        menu_diag_logf(\n            "HOOKS SAFE reset=%d present=%d set_vp=%d shader=%d constants=%d stream=%d extra_v43_hooks=0",\n            reset_ok, present_ok, viewport_ok, shader_ok, constants_ok, stream_ok);\n        if (reset_ok && present_ok && viewport_ok && shader_ok && constants_ok && stream_ok) {\n''',
'safe hook success condition',
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern safe frontend menu scaling probe v44")
