from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v10 is applied after v9.  v9 proved that the gameplay transition explicitly
# requests a 1920x1440 (4:3) window on a 2560x1440 monitor.  Keep the Win32
# guards, but additionally verify/reassert the borderless monitor rectangle at
# IDirect3DDevice8::Present so no unobserved window path can leave the render
# window resized between frames.  Reset the bounded mouse diagnostics when that
# first 4:3 gameplay-size request is observed so the gameplay input path is
# visible in the next test log as well.
replace_once(
'''typedef HRESULT (WINAPI *ResetFn)(void *self, void *presentation_parameters);\ntypedef struct D3DDisplayMode8Local {\n''',
'''typedef HRESULT (WINAPI *ResetFn)(void *self, void *presentation_parameters);\ntypedef HRESULT (WINAPI *PresentFn)(void *self, const RECT *source_rect,\n    const RECT *dest_rect, HWND dest_window_override, const RGNDATA *dirty_region);\ntypedef struct D3DDisplayMode8Local {\n''',
"Present function type",
)

replace_once(
'''static ResetFn real_Reset;\nstatic void *volatile real_GetCursorPosPtr;\n''',
'''static ResetFn real_Reset;\nstatic PresentFn real_Present;\nstatic volatile LONG gameplay_window_transition_seen;\nstatic LONG present_guard_log_count;\nstatic void *volatile real_GetCursorPosPtr;\n''',
"Present guard globals",
)

# The v9 SetWindowPos hook sees MVP's 4:3 gameplay resize request.  Use that as
# a one-shot phase marker and reopen the bounded v7/v8 diagnostics so the log
# contains mouse/geometry evidence from gameplay, not only the front end.
replace_once(
'''        if (get_borderless_monitor_rect(hwnd, &monitor)) {\n            log_window_guard("SetWindowPos", x, y, cx, cy);\n            x = monitor.left;\n''',
'''        if (get_borderless_monitor_rect(hwnd, &monitor)) {\n            int monitor_width = monitor.right - monitor.left;\n            int monitor_height = monitor.bottom - monitor.top;\n            log_window_guard("SetWindowPos", x, y, cx, cy);\n            if (cx > 0 && cy > 0 &&\n                (cx != monitor_width || cy != monitor_height) &&\n                InterlockedCompareExchange(&gameplay_window_transition_seen, 1, 0) == 0) {\n                InterlockedExchange(&input_probe_log_count, 0);\n                InterlockedExchange(&geometry_probe_log_count, 0);\n                InterlockedExchange(&message_scale_log_count, 0);\n                log_line("gameplay window-size transition detected; input diagnostics reset\\n");\n            }\n            x = monitor.left;\n''',
"gameplay window transition marker",
)

marker = '''static HRESULT WINAPI fake_Reset(void *self, void *presentation_parameters)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"Present insertion marker: expected exactly one match, found {text.count(marker)}")

code = r'''static int borderless_window_matches_monitor(HWND hwnd, RECT *window_out,
    RECT *client_out, LONG *style_out)
{
    RECT monitor;
    RECT window_rect;
    RECT client_rect;
    LONG style;

    if (!hwnd || !IsWindow(hwnd) || !get_borderless_monitor_rect(hwnd, &monitor)) return 0;
    if (!GetWindowRect(hwnd, &window_rect) || !GetClientRect(hwnd, &client_rect)) return 0;
    style = GetWindowLongA(hwnd, GWL_STYLE);

    if (window_out) *window_out = window_rect;
    if (client_out) *client_out = client_rect;
    if (style_out) *style_out = style;

    if (window_rect.left != monitor.left || window_rect.top != monitor.top ||
        window_rect.right != monitor.right || window_rect.bottom != monitor.bottom)
        return 0;
    if ((client_rect.right - client_rect.left) != (monitor.right - monitor.left) ||
        (client_rect.bottom - client_rect.top) != (monitor.bottom - monitor.top))
        return 0;
    if (!(style & WS_POPUP) || (style & (WS_CAPTION | WS_THICKFRAME | WS_SYSMENU)))
        return 0;
    return 1;
}

static void enforce_borderless_at_present(void)
{
    RECT window_rect;
    RECT client_rect;
    LONG style = 0;

    if (!borderless_enabled || !borderless_window || !IsWindow(borderless_window)) return;
    if (borderless_window_matches_monitor(borderless_window,
        &window_rect, &client_rect, &style)) return;

    if (InterlockedIncrement(&present_guard_log_count) <= 24) {
        char buf[288];
        wsprintfA(buf,
            "Present borderless drift window=%ld,%ld %ldx%ld client=%ldx%ld style=%08lx logical=%lux%lu; reasserting\\n",
            window_rect.left, window_rect.top,
            window_rect.right - window_rect.left,
            window_rect.bottom - window_rect.top,
            client_rect.right - client_rect.left,
            client_rect.bottom - client_rect.top,
            (unsigned long)style,
            (unsigned long)borderless_logical_width,
            (unsigned long)borderless_logical_height);
        log_line(buf);
    }

    make_borderless_window(borderless_window);
}

static HRESULT WINAPI fake_Present(void *self, const RECT *source_rect,
    const RECT *dest_rect, HWND dest_window_override, const RGNDATA *dirty_region)
{
    enforce_borderless_at_present();
    return real_Present ? real_Present(self, source_rect, dest_rect,
        dest_window_override, dirty_region) : E_FAIL;
}

'''
text = text.replace(marker, code + marker, 1)

replace_once(
'''        int reset_ok, shader_ok, constants_ok, stream_ok;\n''',
'''        int reset_ok, present_ok, shader_ok, constants_ok, stream_ok;\n''',
"Present vtable success variable",
)

replace_once(
'''        reset_ok = patch_vtable_slot(vtbl, 14, fake_Reset, (void **)&real_Reset);\n        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);\n''',
'''        reset_ok = patch_vtable_slot(vtbl, 14, fake_Reset, (void **)&real_Reset);\n        present_ok = patch_vtable_slot(vtbl, 15, fake_Present, (void **)&real_Present);\n        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);\n''',
"Present vtable hook",
)

replace_once(
'''        if (reset_ok && shader_ok && constants_ok && stream_ok) {\n''',
'''        if (reset_ok && present_ok && shader_ok && constants_ok && stream_ok) {\n''',
"Present hook success condition",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern Present-time borderless guard v10")
