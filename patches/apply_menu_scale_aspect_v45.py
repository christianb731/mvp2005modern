from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"menu scale v45 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


def replace_regex_once(pattern: str, replacement: str, label: str) -> None:
    global text
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"menu scale v45 {label}: expected exactly one match, found {count}")
    text = updated


# v0.44 proved the frontend is rendered as live 800x600 2D geometry into the
# expanded HD backbuffer.  Stretching the viewport to the complete 16:9 target
# therefore stretched the original 4:3 artwork.  v0.45 keeps the HD backbuffer
# but fits the logical 800x600 frontend into the largest centered 4:3 viewport.
# The existing queued-mouse transform is updated to use the exact same viewport.

replace_once(
    'MVP2005 Modern v0.44 safe frontend menu scaling probe',
    'MVP2005 Modern v0.45 aspect-correct frontend scaling',
    'diagnostic header',
)
replace_once(
    'experiment=frontend 800x600 backbuffer+viewport -> configured output using only proven CreateDevice/Reset plus SetViewport; gameplay viewport untouched',
    'experiment=center logical 800x600 frontend in aspect-correct 4:3 viewport inside HD backbuffer; mouse uses same transform; gameplay untouched',
    'diagnostic description',
)

replace_once(
'''static volatile LONG menu_scale_apply_count;\nstatic volatile LONG menu_last_matrix_was_2d;\n''',
'''static volatile LONG menu_scale_apply_count;\nstatic LONG menu_mouse_log_count;\nstatic volatile LONG menu_last_matrix_was_2d;\n''',
'mouse diagnostic counter',
)

# Replace the production frontend mouse scaler with a viewport-aware version.
# Keep the proven gameplay-phase aging/passthrough behavior from v0.16 intact.
replace_regex_once(
    r'''static void scale_queued_mouse_message\(MSG \*msg\)\n\{.*?\n\}\n\n(?=static BOOL WINAPI fake_PeekMessageA_probe)''',
    r'''static void menu_scale_aspect_fit(UINT outer_width, UINT outer_height,
    UINT logical_width, UINT logical_height,
    UINT *out_x, UINT *out_y, UINT *out_width, UINT *out_height)
{
    UINT x = 0, y = 0, width = outer_width, height = outer_height;

    if (!outer_width || !outer_height || !logical_width || !logical_height) {
        width = height = 0;
    } else if ((ULONGLONG)outer_width * logical_height >=
               (ULONGLONG)outer_height * logical_width) {
        height = outer_height;
        width = (UINT)(((ULONGLONG)outer_height * logical_width) / logical_height);
        x = (outer_width - width) / 2;
    } else {
        width = outer_width;
        height = (UINT)(((ULONGLONG)outer_width * logical_height) / logical_width);
        y = (outer_height - height) / 2;
    }

    if (out_x) *out_x = x;
    if (out_y) *out_y = y;
    if (out_width) *out_width = width;
    if (out_height) *out_height = height;
}

static int menu_scale_clamp_int(int value, int minimum, int maximum)
{
    if (value < minimum) return minimum;
    if (value > maximum) return maximum;
    return value;
}

static void scale_queued_mouse_message(MSG *msg)
{
    RECT rc;
    POINT origin;
    int client_width;
    int client_height;
    int physical_x;
    int physical_y;
    int relative_x;
    int relative_y;
    int logical_x;
    int logical_y;
    UINT viewport_x;
    UINT viewport_y;
    UINT viewport_width;
    UINT viewport_height;
    int outside;

    if (!msg || msg->hwnd != borderless_window ||
        !is_client_coordinate_mouse_message(msg->message) ||
        !borderless_logical_width || !borderless_logical_height) return;
    if (GetForegroundWindow() != borderless_window) return;

    /* Preserve the verified v0.16 gameplay -> frontend transition detector. */
    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0 &&
        InterlockedCompareExchange(&gameplay_render_seen, 0, 0) != 0) {
        DWORD now = GetTickCount();
        DWORD last = (DWORD)InterlockedCompareExchange(&gameplay_last_3d_tick, 0, 0);
        if (last && (DWORD)(now - last) >= 750) {
            if (InterlockedExchange(&gameplay_input_phase, 0) != 0) {
                InterlockedExchange(&message_scale_log_count, 0);
                if (InterlockedIncrement(&gameplay_phase_log_count) <= 12)
                    log_line("frontend render phase detected; 800x600 mouse scaling restored\n");
                menu_diag_logf("PHASE frontend mouse transform restored after gameplay timeout");
            }
        }
    }

    /* Gameplay already has correct raw HD mouse behavior. */
    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0)
        return;

    if (!GetClientRect(borderless_window, &rc)) return;
    client_width = rc.right - rc.left;
    client_height = rc.bottom - rc.top;
    if (client_width <= 0 || client_height <= 0) return;

    menu_scale_aspect_fit((UINT)client_width, (UINT)client_height,
        borderless_logical_width, borderless_logical_height,
        &viewport_x, &viewport_y, &viewport_width, &viewport_height);
    if (!viewport_width || !viewport_height) return;

    physical_x = (SHORT)LOWORD(msg->lParam);
    physical_y = (SHORT)HIWORD(msg->lParam);
    relative_x = physical_x - (int)viewport_x;
    relative_y = physical_y - (int)viewport_y;
    outside = relative_x < 0 || relative_y < 0 ||
        relative_x >= (int)viewport_width || relative_y >= (int)viewport_height;

    relative_x = menu_scale_clamp_int(relative_x, 0, (int)viewport_width - 1);
    relative_y = menu_scale_clamp_int(relative_y, 0, (int)viewport_height - 1);
    logical_x = MulDiv(relative_x, (int)borderless_logical_width, (int)viewport_width);
    logical_y = MulDiv(relative_y, (int)borderless_logical_height, (int)viewport_height);
    logical_x = menu_scale_clamp_int(logical_x, 0, (int)borderless_logical_width - 1);
    logical_y = menu_scale_clamp_int(logical_y, 0, (int)borderless_logical_height - 1);

    origin.x = 0;
    origin.y = 0;
    if (ClientToScreen(borderless_window, &origin)) {
        LONG local_pt_x = msg->pt.x - origin.x - (LONG)viewport_x;
        LONG local_pt_y = msg->pt.y - origin.y - (LONG)viewport_y;
        local_pt_x = menu_scale_clamp_int((int)local_pt_x, 0, (int)viewport_width - 1);
        local_pt_y = menu_scale_clamp_int((int)local_pt_y, 0, (int)viewport_height - 1);
        msg->pt.x = origin.x + MulDiv(local_pt_x,
            (int)borderless_logical_width, (int)viewport_width);
        msg->pt.y = origin.y + MulDiv(local_pt_y,
            (int)borderless_logical_height, (int)viewport_height);
    }

    msg->lParam = MAKELPARAM((WORD)(SHORT)logical_x, (WORD)(SHORT)logical_y);

    if (InterlockedIncrement(&menu_mouse_log_count) <= 120) {
        menu_diag_logf(
            "MOUSE FRONTEND physical=%d,%d viewport=%u,%u %ux%u logical=%d,%d outside=%d client=%dx%d",
            physical_x, physical_y,
            (unsigned int)viewport_x, (unsigned int)viewport_y,
            (unsigned int)viewport_width, (unsigned int)viewport_height,
            logical_x, logical_y, outside, client_width, client_height);
    }
}

''',
    'aspect-correct queued mouse transform',
)

# Replace v0.44's full-target viewport expansion with the same aspect-fit helper.
replace_regex_once(
    r'''static HRESULT WINAPI menu_fake_SetViewport\(void \*self, const D3DViewport8MenuLocal \*viewport\)\n\{.*?\n\}\n\n(?=static HRESULT WINAPI menu_fake_GetViewport)''',
    r'''static HRESULT WINAPI menu_fake_SetViewport(void *self, const D3DViewport8MenuLocal *viewport)
{
    D3DViewport8MenuLocal adjusted;
    const D3DViewport8MenuLocal *to_send = viewport;
    int gameplay = InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0;
    int candidate = 0;
    int applied = 0;
    UINT fit_x = 0, fit_y = 0, fit_width = 0, fit_height = 0;
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
            menu_scale_aspect_fit(menu_scale_target_width, menu_scale_target_height,
                800, 600, &fit_x, &fit_y, &fit_width, &fit_height);
            if (fit_width && fit_height) {
                adjusted = *viewport;
                adjusted.X = fit_x;
                adjusted.Y = fit_y;
                adjusted.Width = fit_width;
                adjusted.Height = fit_height;
                to_send = &adjusted;
                applied = 1;
                InterlockedIncrement(&menu_scale_apply_count);
            }
        }
    }

    hr = menu_real_SetViewport ? menu_real_SetViewport(self, to_send) : E_FAIL;
    menu_diag_logf(
        "SETVIEWPORT EXIT n=%ld candidate=%d applied=%d out=%lu,%lu %lux%lu hr=0x%08lx",
        (long)n, candidate, applied,
        to_send ? (unsigned long)to_send->X : 0UL,
        to_send ? (unsigned long)to_send->Y : 0UL,
        to_send ? (unsigned long)to_send->Width : 0UL,
        to_send ? (unsigned long)to_send->Height : 0UL,
        (unsigned long)hr);
    return hr;
}

''',
    'aspect-correct SetViewport wrapper',
)

# Strengthen the safe-hook identity in the dedicated log so an uploaded log can
# be distinguished immediately from v0.44.
replace_once(
    'HOOKS SAFE reset=%d present=%d set_vp=%d shader=%d constants=%d stream=%d extra_v43_hooks=0',
    'HOOKS V45 reset=%d present=%d set_vp=%d shader=%d constants=%d stream=%d aspect_fit=1 mouse_fit=1',
    'hook diagnostic identity',
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern aspect-correct frontend scaling v45")
