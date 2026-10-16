from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v10 proved that SetWindowPos/Present-level enforcement is being undone before
# Windows commits the new geometry: a forced 2560x1440 request still emerges as
# an actual 1920x1440 client.  The most likely remaining path is the target
# window procedure (or dgVoodoo's subclass) rewriting WINDOWPOS during
# WM_WINDOWPOSCHANGING.  Subclass MVP's D3D HWND and enforce the monitor-sized
# rectangle *after* the previous window procedure has processed the message, so
# our values are the final ones Windows sees.
replace_once(
'''static volatile LONG gameplay_window_transition_seen;\nstatic LONG present_guard_log_count;\n''',
'''static volatile LONG gameplay_window_transition_seen;\nstatic LONG present_guard_log_count;\nstatic HWND borderless_geometry_guard_window;\nstatic WNDPROC borderless_geometry_guard_original_proc;\nstatic LONG borderless_geometry_guard_log_count;\n''',
"WndProc geometry guard globals",
)

marker = '''static void make_borderless_window(HWND hwnd)\n'''
if text.count(marker) != 1:
    raise SystemExit(f"make_borderless_window marker: expected exactly one match, found {text.count(marker)}")

code = r'''static void log_wndproc_geometry_guard(const char *what,
    int old_x, int old_y, int old_w, int old_h,
    int new_x, int new_y, int new_w, int new_h)
{
    if (InterlockedIncrement(&borderless_geometry_guard_log_count) <= 32) {
        char buf[288];
        wsprintfA(buf,
            "WndProc guard %s %d,%d %dx%d -> %d,%d %dx%d logical=%lux%lu\\n",
            what, old_x, old_y, old_w, old_h,
            new_x, new_y, new_w, new_h,
            (unsigned long)borderless_logical_width,
            (unsigned long)borderless_logical_height);
        log_line(buf);
    }
}

static LRESULT CALLBACK borderless_geometry_wndproc(HWND hwnd, UINT msg,
    WPARAM wparam, LPARAM lparam)
{
    LRESULT result;
    WNDPROC previous = borderless_geometry_guard_original_proc;

    /* Let MVP/dgVoodoo process the message first.  For the CHANGING messages,
     * Windows consumes the mutable structure only after the window proc returns,
     * so rewriting it here makes our geometry/style the final committed value. */
    result = previous ? CallWindowProcA(previous, hwnd, msg, wparam, lparam) :
        DefWindowProcA(hwnd, msg, wparam, lparam);

    if (!borderless_enabled || hwnd != borderless_window ||
        GetForegroundWindow() != hwnd) return result;

    if (msg == WM_WINDOWPOSCHANGING && lparam) {
        WINDOWPOS *wp = (WINDOWPOS *)lparam;
        RECT monitor;

        /* Do not fight an intentional minimize/hide transition. */
        if ((wp->flags & SWP_HIDEWINDOW) || wp->x <= -30000 || wp->y <= -30000)
            return result;

        if (get_borderless_monitor_rect(hwnd, &monitor)) {
            int old_x = wp->x;
            int old_y = wp->y;
            int old_w = wp->cx;
            int old_h = wp->cy;
            int new_w = monitor.right - monitor.left;
            int new_h = monitor.bottom - monitor.top;

            wp->x = monitor.left;
            wp->y = monitor.top;
            wp->cx = new_w;
            wp->cy = new_h;
            wp->flags &= ~(SWP_NOMOVE | SWP_NOSIZE);
            wp->flags |= SWP_NOOWNERZORDER;

            if (old_x != wp->x || old_y != wp->y ||
                old_w != wp->cx || old_h != wp->cy) {
                log_wndproc_geometry_guard("WM_WINDOWPOSCHANGING",
                    old_x, old_y, old_w, old_h,
                    wp->x, wp->y, wp->cx, wp->cy);
            }
        }
    } else if (msg == WM_STYLECHANGING && lparam) {
        STYLESTRUCT *styles = (STYLESTRUCT *)lparam;
        LONG before = styles->styleNew;
        LONG after = before;

        if ((int)wparam == GWL_STYLE) {
            after &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX |
                WS_MAXIMIZEBOX | WS_SYSMENU);
            after |= WS_POPUP | WS_VISIBLE;
        } else if ((int)wparam == GWL_EXSTYLE) {
            after &= ~(WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_DLGMODALFRAME);
        }

        if (after != before) {
            styles->styleNew = after;
            if (InterlockedIncrement(&borderless_geometry_guard_log_count) <= 32) {
                char buf[224];
                wsprintfA(buf,
                    "WndProc guard WM_STYLECHANGING index=%ld requested=%08lx forced=%08lx\\n",
                    (long)wparam, (unsigned long)before, (unsigned long)after);
                log_line(buf);
            }
        }
    }

    return result;
}

static void install_borderless_geometry_wndproc(HWND hwnd)
{
    LONG previous;
    DWORD err;

    if (!borderless_enabled || !hwnd || !IsWindow(hwnd)) return;
    if (borderless_geometry_guard_window == hwnd &&
        (WNDPROC)(LONG_PTR)GetWindowLongA(hwnd, GWL_WNDPROC) == borderless_geometry_wndproc)
        return;

    SetLastError(ERROR_SUCCESS);
    previous = SetWindowLongA(hwnd, GWL_WNDPROC,
        (LONG)(LONG_PTR)borderless_geometry_wndproc);
    err = GetLastError();
    if (previous || err == ERROR_SUCCESS) {
        borderless_geometry_guard_window = hwnd;
        borderless_geometry_guard_original_proc = (WNDPROC)(LONG_PTR)previous;
        log_line("final borderless WndProc geometry guard installed\\n");
    } else {
        log_line("final borderless WndProc geometry guard failed\\n");
    }
}

'''
text = text.replace(marker, code + marker, 1)

replace_once(
'''        log_line("borderless CreateDevice succeeded\\\\n");\n        make_borderless_window(borderless_window);\n''',
'''        log_line("borderless CreateDevice succeeded\\\\n");\n        make_borderless_window(borderless_window);\n        install_borderless_geometry_wndproc(borderless_window);\n''',
"install final geometry WndProc after CreateDevice",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern final WndProc geometry guard v11")
