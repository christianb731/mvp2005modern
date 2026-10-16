from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
'''typedef HRESULT (WINAPI *SetVertexShaderConstantFn)(void *self, DWORD register_address,
''',
'''typedef BOOL (WINAPI *ScreenToClientFn)(HWND hwnd, LPPOINT point);
typedef BOOL (WINAPI *ClientToScreenFn)(HWND hwnd, LPPOINT point);
typedef HRESULT (WINAPI *SetVertexShaderConstantFn)(void *self, DWORD register_address,
''',
"mouse coordinate typedefs",
)

replace_once(
'''static ResetFn real_Reset;
static SetVertexShaderConstantFn real_SetVertexShaderConstant;
''',
'''static ResetFn real_Reset;
static void *volatile real_ScreenToClientPtr;
static void *volatile real_ClientToScreenPtr;
static SetVertexShaderConstantFn real_SetVertexShaderConstant;
''',
"mouse hook trampolines",
)

replace_once(
'''static HWND borderless_window;
static DWORD borderless_display_format;
static int debug_logging;
''',
'''static HWND borderless_window;
static DWORD borderless_display_format;
static UINT borderless_logical_width;
static UINT borderless_logical_height;
static LONG mouse_scale_log_count;
static int debug_logging;
''',
"borderless logical mouse state",
)

marker = '''static void install_save_fix(void)
'''
if text.count(marker) != 1:
    raise SystemExit(f"mouse hook insertion marker: expected exactly one match, found {text.count(marker)}")

mouse_code = r'''static BOOL WINAPI fake_ScreenToClient(HWND hwnd, LPPOINT point)
{
    ScreenToClientFn fn = NULL;
    void *target;
    BOOL ok;

    target = InterlockedCompareExchangePointer(&real_ScreenToClientPtr, NULL, NULL);
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;

    ok = fn(hwnd, point);
    if (ok && point && borderless_enabled && hwnd == borderless_window &&
        borderless_logical_width && borderless_logical_height) {
        RECT rc;
        if (GetClientRect(hwnd, &rc)) {
            int client_width = rc.right - rc.left;
            int client_height = rc.bottom - rc.top;
            if (client_width > 0 && client_height > 0 &&
                (client_width != (int)borderless_logical_width ||
                 client_height != (int)borderless_logical_height)) {
                LONG physical_x = point->x;
                LONG physical_y = point->y;
                point->x = MulDiv(point->x, (int)borderless_logical_width, client_width);
                point->y = MulDiv(point->y, (int)borderless_logical_height, client_height);
                if (InterlockedIncrement(&mouse_scale_log_count) <= 8) {
                    char buf[192];
                    wsprintfA(buf,
                        "mouse ScreenToClient %ld,%ld -> %ld,%ld client=%dx%d logical=%lux%lu\n",
                        physical_x, physical_y, point->x, point->y,
                        client_width, client_height,
                        (unsigned long)borderless_logical_width,
                        (unsigned long)borderless_logical_height);
                    log_line(buf);
                }
            }
        }
    }
    return ok;
}

static BOOL WINAPI fake_ClientToScreen(HWND hwnd, LPPOINT point)
{
    ClientToScreenFn fn = NULL;
    void *target;

    target = InterlockedCompareExchangePointer(&real_ClientToScreenPtr, NULL, NULL);
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return FALSE;

    if (point && borderless_enabled && hwnd == borderless_window &&
        borderless_logical_width && borderless_logical_height) {
        RECT rc;
        if (GetClientRect(hwnd, &rc)) {
            int client_width = rc.right - rc.left;
            int client_height = rc.bottom - rc.top;
            if (client_width > 0 && client_height > 0 &&
                (client_width != (int)borderless_logical_width ||
                 client_height != (int)borderless_logical_height)) {
                point->x = MulDiv(point->x, client_width, (int)borderless_logical_width);
                point->y = MulDiv(point->y, client_height, (int)borderless_logical_height);
            }
        }
    }

    return fn(hwnd, point);
}

static void install_borderless_mouse_fix(void)
{
    HMODULE user32;
    void *screen_to_client;
    void *client_to_screen;

    if (!borderless_enabled) return;
    user32 = GetModuleHandleA("user32.dll");
    if (!user32) return;

    screen_to_client = (void *)GetProcAddress(user32, "ScreenToClient");
    client_to_screen = (void *)GetProcAddress(user32, "ClientToScreen");

    log_line(hook_function(screen_to_client, fake_ScreenToClient, &real_ScreenToClientPtr) > 0 ?
        "ScreenToClient mouse scaling hook installed\n" :
        "ScreenToClient mouse scaling hook failed or conflicted\n");
    log_line(hook_function(client_to_screen, fake_ClientToScreen, &real_ClientToScreenPtr) > 0 ?
        "ClientToScreen mouse scaling hook installed\n" :
        "ClientToScreen mouse scaling hook failed or conflicted\n");
}

'''
text = text.replace(marker, mouse_code + marker, 1)

# Track the logical back-buffer dimensions independently of the physical
# borderless window. The menu starts at 640x480; gameplay may later Reset to
# the selected high-resolution mode, in which case scaling naturally becomes 1:1.
create_anchor = '''static void prepare_borderless_create(void *d3d, UINT adapter, HWND focus_window,
    void *presentation_parameters)
{
    D3DPresentParameters8Local *pp = (D3DPresentParameters8Local *)presentation_parameters;
'''
create_replacement = create_anchor + '''    /* logical coordinates used by MVP's menu/input code */
'''
replace_once(create_anchor, create_replacement, "CreateDevice logical-dimension anchor")

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

reset_anchor = '''static void prepare_borderless_reset(void *presentation_parameters)
{
    D3DPresentParameters8Local *pp = (D3DPresentParameters8Local *)presentation_parameters;
'''
if text.count(reset_anchor) != 1:
    raise SystemExit(f"Reset logical-dimension anchor: expected exactly one match, found {text.count(reset_anchor)}")

# This is the second occurrence of the same validation pattern; target it by
# operating only on the Reset function suffix.
reset_pos = text.index(reset_anchor)
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
    install_borderless_mouse_fix();
    patch_d3d8_iat_once();
''',
"install borderless mouse fix",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern borderless mouse coordinate scaling")
