from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# Track MVP's logical D3D backbuffer size while the physical borderless client
# fills the monitor. Hook GetCursorPos rather than window messages because MVP's
# menu appears to poll the cursor directly.
replace_once(
'''static HWND borderless_window;
static DWORD borderless_display_format;
static int debug_logging;
''',
'''static HWND borderless_window;
static DWORD borderless_display_format;
static UINT borderless_logical_width;
static UINT borderless_logical_height;
static LONG borderless_getcursor_log_count;
static LONG borderless_setcursor_log_count;
static void *volatile real_GetCursorPosPtr;
static void *volatile real_SetCursorPosPtr;
static int debug_logging;
''',
"borderless mouse state globals",
)

marker = '''static void make_borderless_window(HWND hwnd)
'''
if text.count(marker) != 1:
    raise SystemExit(f"borderless window helper marker: expected exactly one match, found {text.count(marker)}")

mouse_code = r'''typedef BOOL (WINAPI *GetCursorPosFn)(LPPOINT point);
typedef BOOL (WINAPI *SetCursorPosFn)(int x, int y);

static BOOL WINAPI fake_GetCursorPos(LPPOINT point)
{
    GetCursorPosFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_GetCursorPosPtr, NULL, NULL);
    BOOL ok;

    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;

    ok = fn(point);
    if (ok && point && borderless_enabled && borderless_window &&
        GetForegroundWindow() == borderless_window &&
        borderless_logical_width && borderless_logical_height) {
        RECT rc;
        POINT origin;
        int client_width;
        int client_height;
        int local_x;
        int local_y;

        if (GetClientRect(borderless_window, &rc)) {
            client_width = rc.right - rc.left;
            client_height = rc.bottom - rc.top;
            origin.x = 0;
            origin.y = 0;
            if (client_width > 0 && client_height > 0 &&
                ClientToScreen(borderless_window, &origin)) {
                local_x = point->x - origin.x;
                local_y = point->y - origin.y;

                if (local_x >= 0 && local_y >= 0 &&
                    local_x < client_width && local_y < client_height &&
                    (client_width != (int)borderless_logical_width ||
                     client_height != (int)borderless_logical_height)) {
                    LONG physical_x = point->x;
                    LONG physical_y = point->y;

                    point->x = origin.x + MulDiv(local_x,
                        (int)borderless_logical_width, client_width);
                    point->y = origin.y + MulDiv(local_y,
                        (int)borderless_logical_height, client_height);

                    if (InterlockedIncrement(&borderless_getcursor_log_count) <= 12) {
                        char buf[224];
                        wsprintfA(buf,
                            "GetCursorPos %ld,%ld -> %ld,%ld client=%dx%d logical=%lux%lu origin=%ld,%ld\n",
                            physical_x, physical_y, point->x, point->y,
                            client_width, client_height,
                            (unsigned long)borderless_logical_width,
                            (unsigned long)borderless_logical_height,
                            origin.x, origin.y);
                        log_line(buf);
                    }
                }
            }
        }
    }

    return ok;
}

static BOOL WINAPI fake_SetCursorPos(int x, int y)
{
    SetCursorPosFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_SetCursorPosPtr, NULL, NULL);
    memcpy(&fn, &target, sizeof(fn));

    /* MVP's fullscreen code tries to warp the system cursor using its old
     * 640x480 coordinate space. In borderless mode that confines the real
     * cursor to the upper-left. Ignore those warps; GetCursorPos supplies MVP
     * with a scaled logical position instead. */
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

static void install_borderless_cursor_poll_fix(void)
{
    HMODULE user32;
    void *get_cursor;
    void *set_cursor;

    if (!borderless_enabled) return;
    user32 = GetModuleHandleA("user32.dll");
    if (!user32) return;

    get_cursor = (void *)GetProcAddress(user32, "GetCursorPos");
    set_cursor = (void *)GetProcAddress(user32, "SetCursorPos");

    log_line(hook_function(get_cursor, fake_GetCursorPos, &real_GetCursorPosPtr) > 0 ?
        "GetCursorPos borderless scaling hook installed\n" :
        "GetCursorPos borderless scaling hook failed or conflicted\n");
    log_line(hook_function(set_cursor, fake_SetCursorPos, &real_SetCursorPosPtr) > 0 ?
        "SetCursorPos borderless warp suppression installed\n" :
        "SetCursorPos borderless warp suppression failed or conflicted\n");
}

'''
text = text.replace(marker, mouse_code + marker, 1)

# Capture the logical dimensions from the presentation request before borderless
# changes the device to windowed mode.
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

replace_once(
'''    install_save_fix();
    patch_d3d8_iat_once();
''',
'''    install_save_fix();
    install_borderless_cursor_poll_fix();
    patch_d3d8_iat_once();
''',
"install borderless cursor polling fix",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern GetCursorPos mouse scaling and cursor-warp suppression")
