from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v16 keeps the v15 true-borderless configuration and fixes two remaining
# lifecycle issues:
#   1. gameplay_input_phase stayed latched after quitting a match, so the main
#      menu continued receiving raw 2560x1440 mouse coordinates instead of the
#      required logical 800x600 mapping;
#   2. MVP still minimizes its borderless HWND during Alt-Tab. Suppress legacy
#      minimize requests so Windows can simply move focus to another app.
#
# The existing widescreen matrix hook already distinguishes 3D perspective
# matrices from 2D orthographic frontend matrices. Use recent 3D rendering as a
# runtime phase signal: gameplay stays raw while 3D matrices are being submitted,
# and after 750 ms with no 3D matrix the next mouse message returns to frontend
# scaling. If 3D rendering resumes (pause/menu transition or another match), raw
# gameplay input is restored automatically.
replace_once(
'''static volatile LONG gameplay_input_phase;\nstatic LONG present_guard_log_count;\n''',
'''static volatile LONG gameplay_input_phase;\nstatic volatile LONG gameplay_render_seen;\nstatic volatile LONG gameplay_last_3d_tick;\nstatic LONG gameplay_phase_log_count;\nstatic LONG present_guard_log_count;\n''',
"v16 render phase globals",
)

# Track recent 3D projection activity independently of Aspect.Enabled. This runs
# on the same matrix classification already trusted by the widescreen patch.
needle = '''    (void)current_vertex_shader;\n    (void)current_stream_stride;\n\n    if (aspect_enabled && constant_data && constant_count <= 64 && constant_count >= 4 &&\n'''
replacement = '''    (void)current_vertex_shader;\n    (void)current_stream_stride;\n\n    if (constant_data && constant_count <= 64 && constant_count >= 4 &&\n        (register_address == 0 || register_address == 12) &&\n        !is_probably_2d_ortho_matrix((const float *)constant_data) &&\n        InterlockedCompareExchange(&gameplay_window_transition_seen, 0, 0) != 0) {\n        LONG old_phase;\n        InterlockedExchange(&gameplay_last_3d_tick, (LONG)GetTickCount());\n        InterlockedExchange(&gameplay_render_seen, 1);\n        old_phase = InterlockedExchange(&gameplay_input_phase, 1);\n        if (!old_phase && InterlockedIncrement(&gameplay_phase_log_count) <= 12)\n            log_line("3D gameplay rendering resumed; raw mouse passthrough enabled\\n");\n    }\n\n    if (aspect_enabled && constant_data && constant_count <= 64 && constant_count >= 4 &&\n'''
replace_once(needle, replacement, "track gameplay 3D rendering")

# Before v12's raw gameplay early-return, age out gameplay mode when the game has
# stopped submitting 3D projection matrices. The first frontend mouse message
# after the timeout is therefore scaled immediately instead of being passed raw.
needle = '''    /* Front-end menus need physical client coordinates mapped into MVP's\n     * logical 800x600 UI. After the characteristic large 4:3 gameplay request,\n     * leave queued mouse coordinates untouched as a direct gameplay test. */\n    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0) {\n'''
replacement = '''    /* Front-end menus need physical client coordinates mapped into MVP's\n     * logical 800x600 UI. Gameplay needs raw client coordinates. Once gameplay\n     * has rendered 3D at least once, a sustained absence of 3D projection\n     * updates means we have returned to a frontend/menu state. */\n    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0 &&\n        InterlockedCompareExchange(&gameplay_render_seen, 0, 0) != 0) {\n        DWORD now = GetTickCount();\n        DWORD last = (DWORD)InterlockedCompareExchange(&gameplay_last_3d_tick, 0, 0);\n        if (last && (DWORD)(now - last) >= 750) {\n            if (InterlockedExchange(&gameplay_input_phase, 0) != 0) {\n                InterlockedExchange(&message_scale_log_count, 0);\n                if (InterlockedIncrement(&gameplay_phase_log_count) <= 12)\n                    log_line("frontend render phase detected; 800x600 mouse scaling restored\\n");\n            }\n        }\n    }\n\n    if (InterlockedCompareExchange(&gameplay_input_phase, 0, 0) != 0) {\n'''
replace_once(needle, replacement, "restore frontend mouse scaling after gameplay")


# ---- True borderless Alt-Tab -------------------------------------------------
# MVP 2005 is a fullscreen-era application and explicitly minimizes its window
# on focus loss. In true windowed/borderless mode that is unnecessary and causes
# the observed Alt-Tab bounce/refocus behavior. Hook ShowWindow and ignore only
# minimize variants for the tracked borderless HWND. Normal show/restore calls
# are untouched, so explicitly selecting MVP still restores/activates normally.
replace_once(
'''static void *volatile real_SetWindowPlacementPtr;\nstatic LONG window_guard_log_count;\n''',
'''static void *volatile real_SetWindowPlacementPtr;\nstatic void *volatile real_ShowWindowPtr;\nstatic LONG window_guard_log_count;\n''',
"ShowWindow hook global",
)

replace_once(
'''typedef BOOL (WINAPI *SetWindowPlacementWinGuardFn)(HWND hwnd,\n    const WINDOWPLACEMENT *placement);\n\n''',
'''typedef BOOL (WINAPI *SetWindowPlacementWinGuardFn)(HWND hwnd,\n    const WINDOWPLACEMENT *placement);\ntypedef BOOL (WINAPI *ShowWindowWinGuardFn)(HWND hwnd, int cmd_show);\n\n''',
"ShowWindow hook typedef",
)

marker = '''static void install_borderless_window_guard(void)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"ShowWindow guard insertion marker: expected exactly one match, found {text.count(marker)}")

showwindow_code = r'''static BOOL WINAPI fake_ShowWindow_guard(HWND hwnd, int cmd_show)
{
    ShowWindowWinGuardFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_ShowWindowPtr, NULL, NULL);
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;

    if (borderless_enabled && hwnd == borderless_window &&
        (cmd_show == SW_MINIMIZE || cmd_show == SW_SHOWMINIMIZED ||
         cmd_show == SW_SHOWMINNOACTIVE || cmd_show == SW_FORCEMINIMIZE)) {
        if (InterlockedIncrement(&window_guard_log_count) <= 48) {
            char buf[160];
            wsprintfA(buf, "window guard suppressed ShowWindow minimize cmd=%d\\n", cmd_show);
            log_line(buf);
        }
        return TRUE;
    }
    return fn(hwnd, cmd_show);
}

'''
text = text.replace(marker, showwindow_code + marker, 1)

replace_once(
'''    installed += install_probe_hook(user32, "SetWindowPlacement",\n        fake_SetWindowPlacement_guard, &real_SetWindowPlacementPtr);\n\n    wsprintfA(buf, "borderless window guard installed hooks=%d/4\\\\n", installed);\n''',
'''    installed += install_probe_hook(user32, "SetWindowPlacement",\n        fake_SetWindowPlacement_guard, &real_SetWindowPlacementPtr);\n    installed += install_probe_hook(user32, "ShowWindow",\n        fake_ShowWindow_guard, &real_ShowWindowPtr);\n\n    wsprintfA(buf, "borderless window guard installed hooks=%d/5\\\\n", installed);\n''',
"install ShowWindow borderless guard",
)

# Also suppress an explicit SC_MINIMIZE before the legacy/dgVoodoo WndProc sees
# it. This covers the common DefWindowProc path without interfering with Alt-Tab
# itself (Alt-Tab is not swallowed; only the minimize system command is).
needle = '''    LRESULT result;\n    WNDPROC previous = borderless_geometry_guard_original_proc;\n\n    /* Let MVP/dgVoodoo process the message first. For the CHANGING messages,\n'''
replacement = '''    LRESULT result;\n    WNDPROC previous = borderless_geometry_guard_original_proc;\n\n    if (borderless_enabled && hwnd == borderless_window &&\n        msg == WM_SYSCOMMAND && ((UINT)wparam & 0xfff0U) == SC_MINIMIZE) {\n        if (InterlockedIncrement(&borderless_geometry_guard_log_count) <= 96)\n            log_line("WndProc guard suppressed SC_MINIMIZE for borderless Alt-Tab\\n");\n        return 0;\n    }\n\n    /* Let MVP/dgVoodoo process the message first. For the CHANGING messages,\n'''
replace_once(needle, replacement, "suppress borderless SC_MINIMIZE")

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern frontend-return + true Alt-Tab fix v16")
