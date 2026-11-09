from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"menu scale v48 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"menu scale v48 {label}: expected exactly one match, found {count}")
    text = updated


# v0.47 exposed the lifecycle boundary we needed. At process startup our forced
# 2560x1440 frontend backbuffer/viewport was accepted, but after gameplay MVP had
# returned to a real 800x600 frontend render target. The same forced 2560x1440
# SetViewport then returned D3DERR_INVALIDCALL repeatedly, while the visible menu
# became coherent because MVP was effectively rendering natively again.
#
# v0.48 makes that post-game state the rule from first startup: MVP owns an
# internal 800x600 frontend backbuffer, viewport, and projection. The existing
# borderless/dgVoodoo path owns scaling the completed frame to the HD client.
# Gameplay remains unchanged. The v0.47 draw-path probe stays installed and is
# re-armed when gameplay ages back into frontend mode.

replace_once(
    'MVP2005 Modern v0.47 coherent frontend fit + draw-path probe',
    'MVP2005 Modern v0.48 native 800x600 frontend + draw-path probe',
    'diagnostic header',
)
replace_once(
    'experiment=full HD viewport; every exact 800x600 frontend ortho matrix uses one coherent centered fit; draw calls traced by caller; gameplay untouched',
    'experiment=keep frontend render target/viewport/projection native 800x600 and let wrapper scale completed frame; draw calls traced by caller; gameplay untouched',
    'diagnostic description',
)

# Stop enlarging the frontend backbuffer during initial CreateDevice. Keep the
# diagnostic so we can prove that the process starts in the same native mode that
# appeared naturally after returning from gameplay in the v0.47 capture.
create_old = '''    if (menu_scale_enabled && borderless_logical_width == 800 &&\n        borderless_logical_height == 600 && menu_scale_target_width >= 800 &&\n        menu_scale_target_height >= 600 &&\n        (menu_scale_target_width != 800 || menu_scale_target_height != 600)) {\n        menu_diag_ensure_open();\n        menu_diag_logf("CREATEDEVICE FRONTEND BACKBUFFER before=%ux%u after=%ux%u logical_kept=800x600",\n            (unsigned int)pp->BackBufferWidth, (unsigned int)pp->BackBufferHeight,\n            (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height);\n        pp->BackBufferWidth = menu_scale_target_width;\n        pp->BackBufferHeight = menu_scale_target_height;\n    }\n'''
create_new = '''    if (menu_scale_enabled && borderless_logical_width == 800 &&\n        borderless_logical_height == 600) {\n        menu_diag_ensure_open();\n        menu_diag_logf("CREATEDEVICE FRONTEND NATIVE backbuffer=%ux%u target_client=%ux%u internal_resize=0",\n            (unsigned int)pp->BackBufferWidth, (unsigned int)pp->BackBufferHeight,\n            (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height);\n    }\n'''
replace_once(create_old, create_new, 'native CreateDevice backbuffer')

# Same policy for frontend Reset: observe but never replace MVP's requested size.
reset_old = '''    if (menu_scale_enabled &&\n        InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0 &&\n        borderless_logical_width == 800 && borderless_logical_height == 600 &&\n        menu_scale_target_width >= 800 && menu_scale_target_height >= 600 &&\n        (menu_scale_target_width != 800 || menu_scale_target_height != 600)) {\n        menu_diag_ensure_open();\n        menu_diag_logf("RESET FRONTEND BACKBUFFER before=%ux%u after=%ux%u logical_kept=800x600",\n            (unsigned int)pp->BackBufferWidth, (unsigned int)pp->BackBufferHeight,\n            (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height);\n        pp->BackBufferWidth = menu_scale_target_width;\n        pp->BackBufferHeight = menu_scale_target_height;\n    }\n'''
reset_new = '''    if (menu_scale_enabled &&\n        InterlockedCompareExchange(&gameplay_input_phase, 0, 0) == 0 &&\n        borderless_logical_width == 800 && borderless_logical_height == 600) {\n        menu_diag_ensure_open();\n        menu_diag_logf("RESET FRONTEND NATIVE backbuffer=%ux%u target_client=%ux%u internal_resize=0",\n            (unsigned int)pp->BackBufferWidth, (unsigned int)pp->BackBufferHeight,\n            (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height);\n    }\n'''
replace_once(reset_old, reset_new, 'native Reset backbuffer')

# Remove the v0.47 frontend projection rewrite entirely. The original 800x600
# orthographic matrix is already classified as 2D by the older aspect hook, so it
# is naturally excluded from gameplay widescreen correction.
replace_regex_once(
    r'''    \{\n        const float \*menu_matrix_in = \(const float \*\)constant_data;\n        float menu_matrix_copy\[256\];\n        int menu_matrix_match = 0;\n\n        if \(menu_scale_enabled.*?        menu_diag_note_matrix\(register_address,\n            menu_matrix_match \? \(const void \*\)menu_matrix_in : constant_data,\n            constant_count\);\n    \}\n''',
    '''    menu_diag_note_matrix(register_address, constant_data, constant_count);\n''',
    'native frontend matrix',
)

# Pass every viewport through unchanged. We still identify the native 800x600
# frontend candidate and log the HRESULT; v0.47 showed that trying to enlarge it
# after gameplay returns is an invalid call against the 800x600 render target.
replace_regex_once(
    r'''static HRESULT WINAPI menu_fake_SetViewport\(void \*self, const D3DViewport8MenuLocal \*viewport\)\n\{.*?\n\}\n\n(?=static HRESULT WINAPI menu_fake_GetViewport)''',
    r'''static HRESULT WINAPI menu_fake_SetViewport(void *self, const D3DViewport8MenuLocal *viewport)
{
    int gameplay = InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0;
    int candidate = 0;
    HRESULT hr;
    LONG n;

    menu_diag_ensure_open();
    n = InterlockedIncrement(&menu_viewport_log_count);
    if (viewport && !gameplay && viewport->X == 0 && viewport->Y == 0 &&
        viewport->Width == 800 && viewport->Height == 600)
        candidate = 1;

    if (n <= 320 || candidate || (n % 240) == 0) {
        menu_diag_logf(
            "SETVIEWPORT ENTER n=%ld phase=%s ptr=%p in=%lu,%lu %lux%lu z=%.3f..%.3f logical=%ux%u target=%ux%u mode=NATIVE_PASS",
            (long)n, gameplay ? "GAMEPLAY" : "FRONTEND", viewport,
            viewport ? (unsigned long)viewport->X : 0UL,
            viewport ? (unsigned long)viewport->Y : 0UL,
            viewport ? (unsigned long)viewport->Width : 0UL,
            viewport ? (unsigned long)viewport->Height : 0UL,
            viewport ? viewport->MinZ : 0.0f, viewport ? viewport->MaxZ : 0.0f,
            (unsigned int)borderless_logical_width, (unsigned int)borderless_logical_height,
            (unsigned int)menu_scale_target_width, (unsigned int)menu_scale_target_height);
    }

    hr = menu_real_SetViewport ? menu_real_SetViewport(self, viewport) : E_FAIL;
    if (n <= 320 || candidate || (n % 240) == 0) {
        menu_diag_logf(
            "SETVIEWPORT EXIT n=%ld candidate=%d applied=0 out=%lu,%lu %lux%lu hr=0x%08lx mode=NATIVE_PASS",
            (long)n, candidate,
            viewport ? (unsigned long)viewport->X : 0UL,
            viewport ? (unsigned long)viewport->Y : 0UL,
            viewport ? (unsigned long)viewport->Width : 0UL,
            viewport ? (unsigned long)viewport->Height : 0UL,
            (unsigned long)hr);
    }
    return hr;
}

''',
    'native SetViewport pass-through',
)

# The wrapper stretches the completed 800x600 frontend image across the borderless
# client, so queued Win32 mouse coordinates must use that same full-client mapping.
# Keep the verified gameplay raw-HD path and 750 ms gameplay->frontend detector.
replace_regex_once(
    r'''static void scale_queued_mouse_message\(MSG \*msg\)\n\{.*?\n\}\n\n(?=static BOOL WINAPI fake_PeekMessageA_probe)''',
    r'''static void scale_queued_mouse_message(MSG *msg)
{
    RECT rc;
    POINT origin;
    int client_width;
    int client_height;
    int physical_x;
    int physical_y;
    int logical_x;
    int logical_y;

    if (!msg || msg->hwnd != borderless_window ||
        !is_client_coordinate_mouse_message(msg->message) ||
        !borderless_logical_width || !borderless_logical_height) return;
    if (GetForegroundWindow() != borderless_window) return;

    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0 &&
        InterlockedCompareExchange(&gameplay_render_seen, 0, 0) != 0) {
        DWORD now = GetTickCount();
        DWORD last = (DWORD)InterlockedCompareExchange(&gameplay_last_3d_tick, 0, 0);
        if (last && (DWORD)(now - last) >= 750) {
            if (InterlockedExchange(&gameplay_input_phase, 0) != 0) {
                InterlockedExchange(&message_scale_log_count, 0);
                InterlockedExchange(&menu_mouse_log_count, 0);
                InterlockedExchange(&menu_draw_log_count, 0);
                if (InterlockedIncrement(&gameplay_phase_log_count) <= 12)
                    log_line("frontend render phase detected; native 800x600 mouse scaling restored\n");
                menu_diag_logf("PHASE frontend native 800x600 restored after gameplay timeout; draw_probe_rearmed=1");
            }
        }
    }

    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0)
        return;

    if (!GetClientRect(borderless_window, &rc)) return;
    client_width = rc.right - rc.left;
    client_height = rc.bottom - rc.top;
    if (client_width <= 0 || client_height <= 0) return;

    physical_x = (SHORT)LOWORD(msg->lParam);
    physical_y = (SHORT)HIWORD(msg->lParam);
    logical_x = MulDiv(menu_scale_clamp_int(physical_x, 0, client_width - 1),
        (int)borderless_logical_width, client_width);
    logical_y = MulDiv(menu_scale_clamp_int(physical_y, 0, client_height - 1),
        (int)borderless_logical_height, client_height);
    logical_x = menu_scale_clamp_int(logical_x, 0, (int)borderless_logical_width - 1);
    logical_y = menu_scale_clamp_int(logical_y, 0, (int)borderless_logical_height - 1);

    origin.x = 0;
    origin.y = 0;
    if (ClientToScreen(borderless_window, &origin)) {
        LONG local_pt_x = msg->pt.x - origin.x;
        LONG local_pt_y = msg->pt.y - origin.y;
        local_pt_x = menu_scale_clamp_int((int)local_pt_x, 0, client_width - 1);
        local_pt_y = menu_scale_clamp_int((int)local_pt_y, 0, client_height - 1);
        msg->pt.x = origin.x + MulDiv(local_pt_x,
            (int)borderless_logical_width, client_width);
        msg->pt.y = origin.y + MulDiv(local_pt_y,
            (int)borderless_logical_height, client_height);
    }

    msg->lParam = MAKELPARAM((WORD)(SHORT)logical_x, (WORD)(SHORT)logical_y);

    if (InterlockedIncrement(&menu_mouse_log_count) <= 120) {
        menu_diag_logf(
            "MOUSE FRONTEND mode=NATIVE_FULLCLIENT physical=%d,%d client=%dx%d logical=%d,%d logical_size=%ux%u",
            physical_x, physical_y, client_width, client_height, logical_x, logical_y,
            (unsigned int)borderless_logical_width, (unsigned int)borderless_logical_height);
    }
}

''',
    'native full-client mouse mapping',
)

replace_once(
    'HOOKS V47 reset=%d present=%d set_vp=%d draw=%d/%d/%d/%d shader=%d constants=%d stream=%d full_viewport=1 coherent_fit=1 draw_trace=1 mouse_fit=1',
    'HOOKS V48 reset=%d present=%d set_vp=%d draw=%d/%d/%d/%d shader=%d constants=%d stream=%d native_frontend=1 draw_trace=1 mouse_fullclient=1',
    'hook diagnostic identity',
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern native 800x600 frontend baseline v48")
