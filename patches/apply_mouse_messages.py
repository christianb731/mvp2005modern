from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# Track the logical Direct3D backbuffer independently from the physical
# borderless client area, and keep the original MVP window procedure.
replace_once(
'''static HWND borderless_window;
static DWORD borderless_display_format;
static int debug_logging;
''',
'''static HWND borderless_window;
static DWORD borderless_display_format;
static UINT borderless_logical_width;
static UINT borderless_logical_height;
static WNDPROC borderless_original_wndproc;
static LONG borderless_mouse_message_log_count;
static LONG borderless_setcursor_log_count;
static void *volatile real_SetCursorPosPtr;
static int debug_logging;
''',
"borderless mouse state globals",
)

# We also suppress MVP's legacy cursor warps while its borderless window is
# foreground. Those warps use the old 640x480 coordinate space and otherwise
# keep dragging the real Windows cursor back into the upper-left box.
marker = '''static void make_borderless_window(HWND hwnd)
'''
if text.count(marker) != 1:
    raise SystemExit(f"borderless window helper marker: expected exactly one match, found {text.count(marker)}")

mouse_code = r'''typedef BOOL (WINAPI *SetCursorPosFn)(int x, int y);

static LPARAM scale_borderless_mouse_lparam(HWND hwnd, LPARAM lparam)
{
    RECT rc;
    int client_width;
    int client_height;
    int physical_x;
    int physical_y;
    int logical_x;
    int logical_y;

    if (!hwnd || hwnd != borderless_window ||
        !borderless_logical_width || !borderless_logical_height) return lparam;
    if (!GetClientRect(hwnd, &rc)) return lparam;

    client_width = rc.right - rc.left;
    client_height = rc.bottom - rc.top;
    if (client_width <= 0 || client_height <= 0) return lparam;
    if (client_width == (int)borderless_logical_width &&
        client_height == (int)borderless_logical_height) return lparam;

    physical_x = (SHORT)LOWORD(lparam);
    physical_y = (SHORT)HIWORD(lparam);
    logical_x = MulDiv(physical_x, (int)borderless_logical_width, client_width);
    logical_y = MulDiv(physical_y, (int)borderless_logical_height, client_height);

    if (InterlockedIncrement(&borderless_mouse_message_log_count) <= 12) {
        char buf[224];
        wsprintfA(buf,
            "mouse message %d,%d -> %d,%d client=%dx%d logical=%lux%lu\n",
            physical_x, physical_y, logical_x, logical_y,
            client_width, client_height,
            (unsigned long)borderless_logical_width,
            (unsigned long)borderless_logical_height);
        log_line(buf);
    }

    return MAKELPARAM((WORD)(SHORT)logical_x, (WORD)(SHORT)logical_y);
}

static LRESULT CALLBACK borderless_mouse_wndproc(HWND hwnd, UINT msg, WPARAM wparam, LPARAM lparam)
{
    LPARAM forwarded = lparam;

    switch (msg) {
    case WM_MOUSEMOVE:
    case WM_LBUTTONDOWN:
    case WM_LBUTTONUP:
    case WM_LBUTTONDBLCLK:
    case WM_RBUTTONDOWN:
    case WM_RBUTTONUP:
    case WM_RBUTTONDBLCLK:
    case WM_MBUTTONDOWN:
    case WM_MBUTTONUP:
    case WM_MBUTTONDBLCLK:
    case WM_XBUTTONDOWN:
    case WM_XBUTTONUP:
    case WM_XBUTTONDBLCLK:
        forwarded = scale_borderless_mouse_lparam(hwnd, lparam);
        break;
    default:
        break;
    }

    if (borderless_original_wndproc)
        return CallWindowProcA(borderless_original_wndproc, hwnd, msg, wparam, forwarded);
    return DefWindowProcA(hwnd, msg, wparam, forwarded);
}

static void install_borderless_mouse_wndproc(HWND hwnd)
{
    LONG previous;
    DWORD err;

    if (!hwnd || !IsWindow(hwnd) || borderless_original_wndproc) return;

    SetLastError(ERROR_SUCCESS);
    previous = SetWindowLongA(hwnd, GWL_WNDPROC, (LONG)(LONG_PTR)borderless_mouse_wndproc);
    err = GetLastError();
    if (previous || err == ERROR_SUCCESS) {
        borderless_original_wndproc = (WNDPROC)(LONG_PTR)previous;
        log_line("borderless mouse window-message scaling installed\n");
    } else {
        log_line("borderless mouse window-message scaling failed\n");
    }
}

static BOOL WINAPI fake_SetCursorPos(int x, int y)
{
    SetCursorPosFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_SetCursorPosPtr, NULL, NULL);
    memcpy(&fn, &target, sizeof(fn));

    if (borderless_enabled && borderless_window &&
        GetForegroundWindow() == borderless_window) {
        if (InterlockedIncrement(&borderless_setcursor_log_count) <= 8) {
            char buf[128];
            wsprintfA(buf, "suppressed legacy SetCursorPos %d,%d in borderless mode\n", x, y);
            log_line(buf);
        }
        return TRUE;
    }

    return fn ? fn(x, y) : FALSE;
}

static void install_borderless_setcursor_fix(void)
{
    HMODULE user32;
    void *target;

    if (!borderless_enabled) return;
    user32 = GetModuleHandleA("user32.dll");
    if (!user32) return;
    target = (void *)GetProcAddress(user32, "SetCursorPos");
    log_line(hook_function(target, fake_SetCursorPos, &real_SetCursorPosPtr) > 0 ?
        "SetCursorPos borderless warp suppression installed\n" :
        "SetCursorPos borderless warp suppression failed or conflicted\n");
}

'''
text = text.replace(marker, mouse_code + marker, 1)

# Capture the original logical dimensions before changing presentation mode.
replace_once(
'''    if (!borderless_enabled || !pp) return;

    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : focus_window;
''',
'''    if (!borderless_enabled || !pp) return;

    borderless_logical_width = pp->BackBufferWidth;
    borderless_logical_height = pp->BackBufferHeight;

    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : focus_window;
''',
"CreateDevice logical dimensions",
)

reset_marker = '''static void prepare_borderless_reset(void *presentation_parameters)
'''
if text.count(reset_marker) != 1:
    raise SystemExit(f"Reset marker: expected exactly one match, found {text.count(reset_marker)}")
reset_pos = text.index(reset_marker)
head = text[:reset_pos]
tail = text[reset_pos:]
old = '''    if (!borderless_enabled || !pp) return;

    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : borderless_window;
'''
new = '''    if (!borderless_enabled || !pp) return;

    borderless_logical_width = pp->BackBufferWidth;
    borderless_logical_height = pp->BackBufferHeight;

    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : borderless_window;
'''
if tail.count(old) != 1:
    raise SystemExit(f"Reset logical dimensions: expected exactly one match, found {tail.count(old)}")
tail = tail.replace(old, new, 1)
text = head + tail

# Install the window subclass only after Direct3D has accepted borderless mode.
replace_once(
'''        log_line("borderless CreateDevice succeeded\\n");
        make_borderless_window(borderless_window);
''',
'''        log_line("borderless CreateDevice succeeded\\n");
        make_borderless_window(borderless_window);
        install_borderless_mouse_wndproc(borderless_window);
''',
"install mouse message scaling after CreateDevice",
)

# Install only the SetCursorPos suppression globally during startup. It is
# gated to MVP's foreground borderless window at runtime.
replace_once(
'''    install_save_fix();
    patch_d3d8_iat_once();
''',
'''    install_save_fix();
    install_borderless_setcursor_fix();
    patch_d3d8_iat_once();
''',
"install SetCursorPos suppression",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern window-message mouse scaling and cursor-warp suppression")
