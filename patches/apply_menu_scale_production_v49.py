from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"menu production v49 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"menu production v49 {label}: expected exactly one match, found {count}")
    text = updated


# v0.48 established the stable frontend policy: MVP owns a native 800x600
# frontend render path and the existing wrapper/borderless presentation scales
# the completed frame to the desktop client.  v0.49 productionizes that result.
#
# Keep the proven full-client -> logical 800x600 mouse mapping, but remove the
# experimental menu diagnostics and stop installing the SetViewport/draw-probe
# hooks.  The old probe bodies remain compiled but inert so this cleanup does not
# churn unrelated D3D code that already survived testing.

replace_once(
    'MVP2005 Modern v0.48 native 800x600 frontend + draw-path probe',
    'MVP2005 Modern v0.49 production native frontend',
    'diagnostic header identity',
)
replace_once(
    'experiment=keep frontend render target/viewport/projection native 800x600 and let wrapper scale completed frame; draw calls traced by caller; gameplay untouched',
    'production=native 800x600 frontend; wrapper scales completed frame; full-client mouse mapping; gameplay untouched',
    'diagnostic description identity',
)

# Remove v0.48 CreateDevice/Reset observation-only logging. These blocks did not
# change presentation parameters; removing them cannot change rendering behavior.
replace_regex_once(
    r'''\n    if \(menu_scale_enabled && borderless_logical_width == 800 &&\n        borderless_logical_height == 600\) \{\n        menu_diag_ensure_open\(\);\n        menu_diag_logf\("CREATEDEVICE FRONTEND NATIVE.*?\n    \}\n''',
    '\n',
    'CreateDevice diagnostics',
)
replace_regex_once(
    r'''\n    if \(menu_scale_enabled &&\n        InterlockedCompareExchange\(&gameplay_input_phase, 0, 0\) == 0 &&\n        borderless_logical_width == 800 && borderless_logical_height == 600\) \{\n        menu_diag_ensure_open\(\);\n        menu_diag_logf\("RESET FRONTEND NATIVE.*?\n    \}\n''',
    '\n',
    'Reset diagnostics',
)

# Restore the pre-menu-probe Present path: borderless enforcement + real Present,
# with no per-frame menu logging.
replace_regex_once(
    r'''static HRESULT WINAPI fake_Present\(void \*self, const RECT \*source_rect,\n    const RECT \*dest_rect, HWND dest_window_override, const RGNDATA \*dirty_region\)\n\{.*?\n\}\n\n(?=static HRESULT WINAPI fake_Reset)''',
    r'''static HRESULT WINAPI fake_Present(void *self, const RECT *source_rect,
    const RECT *dest_rect, HWND dest_window_override, const RGNDATA *dirty_region)
{
    enforce_borderless_at_present();
    return real_Present ? real_Present(self, source_rect, dest_rect,
        dest_window_override, dirty_region) : E_FAIL;
}

''',
    'production Present path',
)

# The matrix observer was diagnostic-only. Preserve the existing shader/aspect
# hook itself, which is production gameplay functionality.
replace_once(
    '    menu_diag_note_matrix(register_address, constant_data, constant_count);\n',
    '',
    'matrix diagnostic call',
)

# Keep v0.48's full-client mouse mapping, but remove menu-specific counters/logs
# and draw-probe rearming. The established 750ms gameplay->frontend phase detector
# remains intact.
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
                if (InterlockedIncrement(&gameplay_phase_log_count) <= 12)
                    log_line("frontend render phase detected; 800x600 mouse scaling restored\n");
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
}

''',
    'production frontend mouse mapping',
)

# Stop installing experimental SetViewport and draw-call hooks. Reset/Present and
# shader/constant/stream hooks predate the menu experiment and remain required by
# established borderless/gameplay behavior.
replace_once(
'''        int reset_ok, present_ok, viewport_ok, shader_ok, constants_ok, stream_ok;\n        int draw_ok, draw_indexed_ok, draw_up_ok, draw_indexed_up_ok;\n''',
'''        int reset_ok, present_ok, shader_ok, constants_ok, stream_ok;\n''',
    'hook variable cleanup',
)

replace_regex_once(
    r'''        viewport_ok = patch_vtable_slot\(vtbl, 40, menu_fake_SetViewport, \(void \*\*\)&menu_real_SetViewport\);\n        draw_ok = patch_vtable_slot\(vtbl, 70, menu_fake_DrawPrimitive, \(void \*\*\)&menu_real_DrawPrimitive\);\n        draw_indexed_ok = patch_vtable_slot\(vtbl, 71, menu_fake_DrawIndexedPrimitive, \(void \*\*\)&menu_real_DrawIndexedPrimitive\);\n        draw_up_ok = patch_vtable_slot\(vtbl, 72, menu_fake_DrawPrimitiveUP, \(void \*\*\)&menu_real_DrawPrimitiveUP\);\n        draw_indexed_up_ok = patch_vtable_slot\(vtbl, 73, menu_fake_DrawIndexedPrimitiveUP, \(void \*\*\)&menu_real_DrawIndexedPrimitiveUP\);\n''',
    '',
    'experimental vtable hooks',
)

# Remove the menu-probe startup log and return the success condition to the five
# production hooks. Use a compact base debug-log line instead of a dedicated menu
# diagnostic file.
replace_regex_once(
    r'''        menu_diag_ensure_open\(\);\n        menu_diag_logf\(\n            "HOOKS V48.*?\n        if \(reset_ok && present_ok && viewport_ok && draw_ok && draw_indexed_ok &&\n            draw_up_ok && draw_indexed_up_ok && shader_ok && constants_ok && stream_ok\) \{''',
    r'''        if (reset_ok && present_ok && shader_ok && constants_ok && stream_ok) {''',
    'production hook success condition',
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern production native frontend cleanup v49")
