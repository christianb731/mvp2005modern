from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v7 deliberately stops transforming mouse coordinates.  The only behavioral
# change retained is suppressing MVP's legacy SetCursorPos warps so the physical
# cursor remains free in the borderless window.  Everything else below is a
# bounded diagnostic probe.
replace_once(
'''static ResetFn real_Reset;\nstatic SetVertexShaderConstantFn real_SetVertexShaderConstant;\n''',
'''static ResetFn real_Reset;\nstatic void *volatile real_GetCursorPosPtr;\nstatic void *volatile real_SetCursorPosPtr;\nstatic void *volatile real_GetMessagePosPtr;\nstatic void *volatile real_PeekMessageAPtr;\nstatic void *volatile real_GetMessageAPtr;\nstatic void *volatile real_GetClientRectPtr;\nstatic void *volatile real_GetWindowRectPtr;\nstatic void *volatile real_ScreenToClientPtr;\nstatic void *volatile real_GetSystemMetricsPtr;\nstatic void *volatile real_ClipCursorPtr;\nstatic LONG input_probe_log_count;\nstatic LONG geometry_probe_log_count;\nstatic LONG setcursor_probe_log_count;\nstatic UINT borderless_logical_width;\nstatic UINT borderless_logical_height;\nstatic SetVertexShaderConstantFn real_SetVertexShaderConstant;\n''',
"input probe globals",
)

marker = '''static void make_borderless_window(HWND hwnd)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"input probe insertion marker: expected exactly one match, found {text.count(marker)}")

code = r'''typedef BOOL (WINAPI *GetCursorPosProbeFn)(LPPOINT point);
typedef BOOL (WINAPI *SetCursorPosProbeFn)(int x, int y);
typedef DWORD (WINAPI *GetMessagePosProbeFn)(void);
typedef BOOL (WINAPI *PeekMessageAProbeFn)(LPMSG msg, HWND hwnd, UINT min_msg, UINT max_msg, UINT remove_msg);
typedef BOOL (WINAPI *GetMessageAProbeFn)(LPMSG msg, HWND hwnd, UINT min_msg, UINT max_msg);
typedef BOOL (WINAPI *GetClientRectProbeFn)(HWND hwnd, LPRECT rect);
typedef BOOL (WINAPI *GetWindowRectProbeFn)(HWND hwnd, LPRECT rect);
typedef BOOL (WINAPI *ScreenToClientProbeFn)(HWND hwnd, LPPOINT point);
typedef int (WINAPI *GetSystemMetricsProbeFn)(int index);
typedef BOOL (WINAPI *ClipCursorProbeFn)(const RECT *rect);

static int is_mouse_message(UINT msg)
{
    return (msg >= WM_MOUSEFIRST && msg <= WM_MOUSELAST) ||
           msg == WM_NCMOUSEMOVE || msg == WM_NCLBUTTONDOWN || msg == WM_NCLBUTTONUP ||
           msg == WM_NCRBUTTONDOWN || msg == WM_NCRBUTTONUP ||
           msg == WM_NCMBUTTONDOWN || msg == WM_NCMBUTTONUP;
}

static void log_mouse_msg(const char *source, const MSG *msg)
{
    LONG n;
    int lx;
    int ly;
    char buf[256];

    if (!msg || !is_mouse_message(msg->message)) return;
    n = InterlockedIncrement(&input_probe_log_count);
    if (n > 60) return;

    lx = (SHORT)LOWORD(msg->lParam);
    ly = (SHORT)HIWORD(msg->lParam);
    wsprintfA(buf,
        "%s msg=%04x hwnd=%p lparam=%d,%d pt=%ld,%ld remove? logical=%lux%lu\\n",
        source, (unsigned int)msg->message, msg->hwnd, lx, ly,
        msg->pt.x, msg->pt.y,
        (unsigned long)borderless_logical_width,
        (unsigned long)borderless_logical_height);
    log_line(buf);
}

static BOOL WINAPI fake_GetCursorPos_probe(LPPOINT point)
{
    GetCursorPosProbeFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_GetCursorPosPtr, NULL, NULL);
    BOOL ok;
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;
    ok = fn(point);
    if (ok && point && borderless_enabled && borderless_window &&
        GetForegroundWindow() == borderless_window &&
        InterlockedIncrement(&geometry_probe_log_count) <= 40) {
        char buf[160];
        wsprintfA(buf, "probe GetCursorPos raw=%ld,%ld\\n", point->x, point->y);
        log_line(buf);
    }
    return ok;
}

static BOOL WINAPI fake_SetCursorPos_probe(int x, int y)
{
    SetCursorPosProbeFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_SetCursorPosPtr, NULL, NULL);
    memcpy(&fn, &target, sizeof(fn));

    if (borderless_enabled && borderless_window &&
        GetForegroundWindow() == borderless_window) {
        if (InterlockedIncrement(&setcursor_probe_log_count) <= 20) {
            char buf[144];
            wsprintfA(buf, "probe suppressed SetCursorPos %d,%d\\n", x, y);
            log_line(buf);
        }
        return TRUE;
    }
    return fn ? fn(x, y) : FALSE;
}

static DWORD WINAPI fake_GetMessagePos_probe(void)
{
    GetMessagePosProbeFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_GetMessagePosPtr, NULL, NULL);
    DWORD packed;
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return 0;
    packed = fn();
    if (borderless_enabled && borderless_window &&
        GetForegroundWindow() == borderless_window &&
        InterlockedIncrement(&input_probe_log_count) <= 60) {
        char buf[160];
        wsprintfA(buf, "probe GetMessagePos=%d,%d\\n",
            (int)(SHORT)LOWORD(packed), (int)(SHORT)HIWORD(packed));
        log_line(buf);
    }
    return packed;
}

static BOOL WINAPI fake_PeekMessageA_probe(LPMSG msg, HWND hwnd, UINT min_msg, UINT max_msg, UINT remove_msg)
{
    PeekMessageAProbeFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_PeekMessageAPtr, NULL, NULL);
    BOOL ok;
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;
    ok = fn(msg, hwnd, min_msg, max_msg, remove_msg);
    if (ok && borderless_enabled) log_mouse_msg("probe PeekMessageA", msg);
    return ok;
}

static BOOL WINAPI fake_GetMessageA_probe(LPMSG msg, HWND hwnd, UINT min_msg, UINT max_msg)
{
    GetMessageAProbeFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_GetMessageAPtr, NULL, NULL);
    BOOL ok;
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;
    ok = fn(msg, hwnd, min_msg, max_msg);
    if (ok > 0 && borderless_enabled) log_mouse_msg("probe GetMessageA", msg);
    return ok;
}

static BOOL WINAPI fake_GetClientRect_probe(HWND hwnd, LPRECT rect)
{
    GetClientRectProbeFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_GetClientRectPtr, NULL, NULL);
    BOOL ok;
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;
    ok = fn(hwnd, rect);
    if (ok && rect && hwnd == borderless_window &&
        InterlockedIncrement(&geometry_probe_log_count) <= 40) {
        char buf[192];
        wsprintfA(buf, "probe GetClientRect=%ld,%ld,%ld,%ld size=%ldx%ld logical=%lux%lu\\n",
            rect->left, rect->top, rect->right, rect->bottom,
            rect->right - rect->left, rect->bottom - rect->top,
            (unsigned long)borderless_logical_width,
            (unsigned long)borderless_logical_height);
        log_line(buf);
    }
    return ok;
}

static BOOL WINAPI fake_GetWindowRect_probe(HWND hwnd, LPRECT rect)
{
    GetWindowRectProbeFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_GetWindowRectPtr, NULL, NULL);
    BOOL ok;
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;
    ok = fn(hwnd, rect);
    if (ok && rect && hwnd == borderless_window &&
        InterlockedIncrement(&geometry_probe_log_count) <= 40) {
        char buf[192];
        wsprintfA(buf, "probe GetWindowRect=%ld,%ld,%ld,%ld size=%ldx%ld\\n",
            rect->left, rect->top, rect->right, rect->bottom,
            rect->right - rect->left, rect->bottom - rect->top);
        log_line(buf);
    }
    return ok;
}

static BOOL WINAPI fake_ScreenToClient_probe(HWND hwnd, LPPOINT point)
{
    ScreenToClientProbeFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_ScreenToClientPtr, NULL, NULL);
    BOOL ok;
    LONG old_x = point ? point->x : 0;
    LONG old_y = point ? point->y : 0;
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;
    ok = fn(hwnd, point);
    if (ok && point && hwnd == borderless_window &&
        InterlockedIncrement(&geometry_probe_log_count) <= 40) {
        char buf[180];
        wsprintfA(buf, "probe ScreenToClient %ld,%ld -> %ld,%ld\\n",
            old_x, old_y, point->x, point->y);
        log_line(buf);
    }
    return ok;
}

static int WINAPI fake_GetSystemMetrics_probe(int index)
{
    GetSystemMetricsProbeFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_GetSystemMetricsPtr, NULL, NULL);
    int value;
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return 0;
    value = fn(index);
    if (borderless_enabled && (index == SM_CXSCREEN || index == SM_CYSCREEN ||
        index == SM_CXFULLSCREEN || index == SM_CYFULLSCREEN) &&
        InterlockedIncrement(&geometry_probe_log_count) <= 40) {
        char buf[128];
        wsprintfA(buf, "probe GetSystemMetrics index=%d value=%d\\n", index, value);
        log_line(buf);
    }
    return value;
}

static BOOL WINAPI fake_ClipCursor_probe(const RECT *rect)
{
    ClipCursorProbeFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_ClipCursorPtr, NULL, NULL);
    memcpy(&fn, &target, sizeof(fn));
    if (borderless_enabled && InterlockedIncrement(&geometry_probe_log_count) <= 40) {
        char buf[192];
        if (rect) {
            wsprintfA(buf, "probe ClipCursor=%ld,%ld,%ld,%ld size=%ldx%ld\\n",
                rect->left, rect->top, rect->right, rect->bottom,
                rect->right - rect->left, rect->bottom - rect->top);
        } else {
            lstrcpyA(buf, "probe ClipCursor=NULL\\n");
        }
        log_line(buf);
    }
    return fn ? fn(rect) : FALSE;
}

static int install_probe_hook(HMODULE user32, const char *name, void *detour, void *volatile *real_ptr)
{
    void *target;
    if (!user32) return 0;
    target = (void *)GetProcAddress(user32, name);
    if (!target) return 0;
    return hook_function(target, detour, real_ptr) > 0;
}

static void install_borderless_input_probe(void)
{
    HMODULE user32;
    int installed = 0;
    char buf[160];

    if (!borderless_enabled) return;
    user32 = GetModuleHandleA("user32.dll");
    if (!user32) {
        log_line("input probe: user32.dll not loaded\\n");
        return;
    }

    installed += install_probe_hook(user32, "GetCursorPos", fake_GetCursorPos_probe, &real_GetCursorPosPtr);
    installed += install_probe_hook(user32, "SetCursorPos", fake_SetCursorPos_probe, &real_SetCursorPosPtr);
    installed += install_probe_hook(user32, "GetMessagePos", fake_GetMessagePos_probe, &real_GetMessagePosPtr);
    installed += install_probe_hook(user32, "PeekMessageA", fake_PeekMessageA_probe, &real_PeekMessageAPtr);
    installed += install_probe_hook(user32, "GetMessageA", fake_GetMessageA_probe, &real_GetMessageAPtr);
    installed += install_probe_hook(user32, "GetClientRect", fake_GetClientRect_probe, &real_GetClientRectPtr);
    installed += install_probe_hook(user32, "GetWindowRect", fake_GetWindowRect_probe, &real_GetWindowRectPtr);
    installed += install_probe_hook(user32, "ScreenToClient", fake_ScreenToClient_probe, &real_ScreenToClientPtr);
    installed += install_probe_hook(user32, "GetSystemMetrics", fake_GetSystemMetrics_probe, &real_GetSystemMetricsPtr);
    installed += install_probe_hook(user32, "ClipCursor", fake_ClipCursor_probe, &real_ClipCursorPtr);

    wsprintfA(buf, "borderless input probe installed hooks=%d/10\\n", installed);
    log_line(buf);
}

'''
text = text.replace(marker, code + marker, 1)

# Capture the logical D3D front-end size before borderless switches presentation
# mode.  Do not change the dimensions in this diagnostic build.
replace_once(
'''    if (!borderless_enabled || !pp) return;\n\n    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : focus_window;\n''',
'''    if (!borderless_enabled || !pp) return;\n\n    borderless_logical_width = pp->BackBufferWidth;\n    borderless_logical_height = pp->BackBufferHeight;\n\n    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : focus_window;\n''',
"capture CreateDevice logical dimensions",
)

reset_marker = '''static void prepare_borderless_reset(void *presentation_parameters)\n'''
if text.count(reset_marker) != 1:
    raise SystemExit(f"Reset marker: expected exactly one match, found {text.count(reset_marker)}")
reset_pos = text.index(reset_marker)
head = text[:reset_pos]
tail = text[reset_pos:]
old = '''    if (!borderless_enabled || !pp) return;\n\n    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : borderless_window;\n'''
new = '''    if (!borderless_enabled || !pp) return;\n\n    borderless_logical_width = pp->BackBufferWidth;\n    borderless_logical_height = pp->BackBufferHeight;\n\n    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : borderless_window;\n'''
if tail.count(old) != 1:
    raise SystemExit(f"capture Reset logical dimensions: expected exactly one match, found {tail.count(old)}")
tail = tail.replace(old, new, 1)
text = head + tail

replace_once(
'''    install_save_fix();\n    patch_d3d8_iat_once();\n''',
'''    install_save_fix();\n    install_borderless_input_probe();\n    patch_d3d8_iat_once();\n''',
"install borderless input probe",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern Win32 message/geometry input probe v7")
