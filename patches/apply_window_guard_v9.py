from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v9 is applied after the v7 probe + v8 queued-message scaler.  The gameplay
# transition does not call IDirect3DDevice8::Reset or create a new D3D8 device,
# so preserve the borderless HWND against legacy style/position changes instead.
replace_once(
'''static void *volatile real_ClipCursorPtr;\nstatic LONG input_probe_log_count;\n''',
'''static void *volatile real_ClipCursorPtr;\nstatic void *volatile real_SetWindowLongAPtr;\nstatic void *volatile real_SetWindowPosPtr;\nstatic void *volatile real_MoveWindowPtr;\nstatic void *volatile real_SetWindowPlacementPtr;\nstatic LONG window_guard_log_count;\nstatic LONG input_probe_log_count;\n''',
"window guard globals",
)

marker = '''static void make_borderless_window(HWND hwnd)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"window guard insertion marker: expected exactly one match, found {text.count(marker)}")

code = r'''typedef LONG (WINAPI *SetWindowLongAWinGuardFn)(HWND hwnd, int index, LONG value);
typedef BOOL (WINAPI *SetWindowPosWinGuardFn)(HWND hwnd, HWND insert_after,
    int x, int y, int cx, int cy, UINT flags);
typedef BOOL (WINAPI *MoveWindowWinGuardFn)(HWND hwnd, int x, int y,
    int width, int height, BOOL repaint);
typedef BOOL (WINAPI *SetWindowPlacementWinGuardFn)(HWND hwnd,
    const WINDOWPLACEMENT *placement);

static int get_borderless_monitor_rect(HWND hwnd, RECT *rect)
{
    HMONITOR monitor;
    MONITORINFO info;

    if (!hwnd || !rect) return 0;
    monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
    if (!monitor) return 0;
    ZeroMemory(&info, sizeof(info));
    info.cbSize = sizeof(info);
    if (!GetMonitorInfoA(monitor, &info)) return 0;
    *rect = info.rcMonitor;
    return 1;
}

static void log_window_guard(const char *what, int x, int y, int w, int h)
{
    if (InterlockedIncrement(&window_guard_log_count) <= 32) {
        char buf[224];
        wsprintfA(buf, "window guard %s request=%d,%d %dx%d logical=%lux%lu\\n",
            what, x, y, w, h,
            (unsigned long)borderless_logical_width,
            (unsigned long)borderless_logical_height);
        log_line(buf);
    }
}

static LONG WINAPI fake_SetWindowLongA_guard(HWND hwnd, int index, LONG value)
{
    SetWindowLongAWinGuardFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_SetWindowLongAPtr, NULL, NULL);
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return 0;

    if (borderless_enabled && hwnd == borderless_window) {
        LONG original = value;
        if (index == GWL_STYLE) {
            value &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX |
                WS_MAXIMIZEBOX | WS_SYSMENU);
            value |= WS_POPUP | WS_VISIBLE;
        } else if (index == GWL_EXSTYLE) {
            value &= ~(WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_DLGMODALFRAME);
        }
        if ((index == GWL_STYLE || index == GWL_EXSTYLE) && original != value &&
            InterlockedIncrement(&window_guard_log_count) <= 32) {
            char buf[224];
            wsprintfA(buf,
                "window guard SetWindowLongA index=%d requested=%08lx forced=%08lx\\n",
                index, (unsigned long)original, (unsigned long)value);
            log_line(buf);
        }
    }
    return fn(hwnd, index, value);
}

static BOOL WINAPI fake_SetWindowPos_guard(HWND hwnd, HWND insert_after,
    int x, int y, int cx, int cy, UINT flags)
{
    SetWindowPosWinGuardFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_SetWindowPosPtr, NULL, NULL);
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;

    if (borderless_enabled && hwnd == borderless_window) {
        RECT monitor;
        if (get_borderless_monitor_rect(hwnd, &monitor)) {
            log_window_guard("SetWindowPos", x, y, cx, cy);
            x = monitor.left;
            y = monitor.top;
            cx = monitor.right - monitor.left;
            cy = monitor.bottom - monitor.top;
            flags &= ~(SWP_NOMOVE | SWP_NOSIZE);
            flags |= SWP_NOOWNERZORDER;
        }
    }
    return fn(hwnd, insert_after, x, y, cx, cy, flags);
}

static BOOL WINAPI fake_MoveWindow_guard(HWND hwnd, int x, int y,
    int width, int height, BOOL repaint)
{
    MoveWindowWinGuardFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_MoveWindowPtr, NULL, NULL);
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;

    if (borderless_enabled && hwnd == borderless_window) {
        RECT monitor;
        if (get_borderless_monitor_rect(hwnd, &monitor)) {
            log_window_guard("MoveWindow", x, y, width, height);
            x = monitor.left;
            y = monitor.top;
            width = monitor.right - monitor.left;
            height = monitor.bottom - monitor.top;
        }
    }
    return fn(hwnd, x, y, width, height, repaint);
}

static BOOL WINAPI fake_SetWindowPlacement_guard(HWND hwnd,
    const WINDOWPLACEMENT *placement)
{
    SetWindowPlacementWinGuardFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_SetWindowPlacementPtr, NULL, NULL);
    WINDOWPLACEMENT forced;
    RECT monitor;
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;

    if (borderless_enabled && hwnd == borderless_window && placement &&
        get_borderless_monitor_rect(hwnd, &monitor)) {
        forced = *placement;
        forced.showCmd = SW_SHOWNORMAL;
        forced.rcNormalPosition = monitor;
        log_window_guard("SetWindowPlacement",
            placement->rcNormalPosition.left,
            placement->rcNormalPosition.top,
            placement->rcNormalPosition.right - placement->rcNormalPosition.left,
            placement->rcNormalPosition.bottom - placement->rcNormalPosition.top);
        return fn(hwnd, &forced);
    }
    return fn(hwnd, placement);
}

static void install_borderless_window_guard(void)
{
    HMODULE user32;
    int installed = 0;
    char buf[160];

    if (!borderless_enabled) return;
    user32 = GetModuleHandleA("user32.dll");
    if (!user32) return;

    installed += install_probe_hook(user32, "SetWindowLongA",
        fake_SetWindowLongA_guard, &real_SetWindowLongAPtr);
    installed += install_probe_hook(user32, "SetWindowPos",
        fake_SetWindowPos_guard, &real_SetWindowPosPtr);
    installed += install_probe_hook(user32, "MoveWindow",
        fake_MoveWindow_guard, &real_MoveWindowPtr);
    installed += install_probe_hook(user32, "SetWindowPlacement",
        fake_SetWindowPlacement_guard, &real_SetWindowPlacementPtr);

    wsprintfA(buf, "borderless window guard installed hooks=%d/4\\n", installed);
    log_line(buf);
}

'''
text = text.replace(marker, code + marker, 1)

replace_once(
'''    install_save_fix();\n    install_borderless_input_probe();\n''',
'''    install_save_fix();\n    install_borderless_input_probe();\n    install_borderless_window_guard();\n''',
"install persistent borderless window guard",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern persistent borderless window guard v9")
