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
'''typedef HRESULT (WINAPI *CreateDeviceFn)(void *self, UINT adapter, DWORD device_type, HWND focus_window,
    DWORD behavior_flags, void *presentation_parameters, void **returned_device);
typedef HRESULT (WINAPI *SetVertexShaderConstantFn)(void *self, DWORD register_address,
''',
'''typedef HRESULT (WINAPI *CreateDeviceFn)(void *self, UINT adapter, DWORD device_type, HWND focus_window,
    DWORD behavior_flags, void *presentation_parameters, void **returned_device);
typedef HRESULT (WINAPI *ResetFn)(void *self, void *presentation_parameters);
typedef struct D3DDisplayMode8Local {
    UINT Width;
    UINT Height;
    UINT RefreshRate;
    DWORD Format;
} D3DDisplayMode8Local;
typedef HRESULT (WINAPI *GetAdapterDisplayModeFn)(void *self, UINT adapter, D3DDisplayMode8Local *mode);
typedef struct D3DPresentParameters8Local {
    UINT BackBufferWidth;
    UINT BackBufferHeight;
    DWORD BackBufferFormat;
    UINT BackBufferCount;
    DWORD MultiSampleType;
    DWORD SwapEffect;
    HWND hDeviceWindow;
    BOOL Windowed;
    BOOL EnableAutoDepthStencil;
    DWORD AutoDepthStencilFormat;
    DWORD Flags;
    UINT FullScreen_RefreshRateInHz;
    UINT FullScreen_PresentationInterval;
} D3DPresentParameters8Local;
typedef HRESULT (WINAPI *SetVertexShaderConstantFn)(void *self, DWORD register_address,
''',
"D3D8 type declarations",
)

replace_once(
'''static void **real_device_vtbl;
static CreateDeviceFn real_CreateDevice;
static SetVertexShaderConstantFn real_SetVertexShaderConstant;
''',
'''static void **real_device_vtbl;
static CreateDeviceFn real_CreateDevice;
static ResetFn real_Reset;
static SetVertexShaderConstantFn real_SetVertexShaderConstant;
''',
"Reset function pointer",
)

replace_once(
'''static int aspect_enabled = 1;
static int save_fix_enabled = 1;
static int debug_logging;
''',
'''static int aspect_enabled = 1;
static int save_fix_enabled = 1;
static int borderless_enabled;
static HWND borderless_window;
static DWORD borderless_display_format;
static int debug_logging;
''',
"borderless state globals",
)

replace_once(
'''    aspect_enabled = GetPrivateProfileIntA("Aspect", "Enabled", 1, ini) != 0;
    save_fix_enabled = GetPrivateProfileIntA("SaveFix", "Enabled", 1, ini) != 0;
    {
''',
'''    aspect_enabled = GetPrivateProfileIntA("Aspect", "Enabled", 1, ini) != 0;
    save_fix_enabled = GetPrivateProfileIntA("SaveFix", "Enabled", 1, ini) != 0;
    borderless_enabled = GetPrivateProfileIntA("Borderless", "Enabled", 0, ini) != 0;
    {
''',
"borderless config load",
)

replace_once(
'''        wsprintfA(buf, "config aspect=%d scale=%08lx save=%d\\n",
            aspect_enabled, scale_bits, save_fix_enabled);
        log_line(buf);
    }
}
''',
'''        wsprintfA(buf, "config aspect=%d scale=%08lx save=%d borderless=%d\\n",
            aspect_enabled, scale_bits, save_fix_enabled, borderless_enabled);
        log_line(buf);
    }
}
''',
"config log",
)

marker = '''static HRESULT WINAPI fake_CreateDevice(void *self, UINT adapter, DWORD device_type, HWND focus_window,
    DWORD behavior_flags, void *presentation_parameters, void **returned_device)
{
'''
if text.count(marker) != 1:
    raise SystemExit(f"CreateDevice marker: expected exactly one match, found {text.count(marker)}")

helpers = r'''static void make_borderless_window(HWND hwnd)
{
    LONG style;
    LONG ex_style;
    HMONITOR monitor;
    MONITORINFO info;
    int width;
    int height;

    if (!hwnd || !IsWindow(hwnd)) return;

    monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
    if (!monitor) return;
    ZeroMemory(&info, sizeof(info));
    info.cbSize = sizeof(info);
    if (!GetMonitorInfoA(monitor, &info)) return;

    style = GetWindowLongA(hwnd, GWL_STYLE);
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU);
    style |= WS_POPUP | WS_VISIBLE;
    SetWindowLongA(hwnd, GWL_STYLE, style);

    ex_style = GetWindowLongA(hwnd, GWL_EXSTYLE);
    ex_style &= ~(WS_EX_WINDOWEDGE | WS_EX_CLIENTEDGE | WS_EX_DLGMODALFRAME);
    SetWindowLongA(hwnd, GWL_EXSTYLE, ex_style);

    width = info.rcMonitor.right - info.rcMonitor.left;
    height = info.rcMonitor.bottom - info.rcMonitor.top;
    SetWindowPos(hwnd, HWND_TOP,
        info.rcMonitor.left, info.rcMonitor.top, width, height,
        SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOOWNERZORDER);
}

static void prepare_borderless_create(void *d3d, UINT adapter, HWND focus_window,
    void *presentation_parameters)
{
    D3DPresentParameters8Local *pp = (D3DPresentParameters8Local *)presentation_parameters;
    D3DDisplayMode8Local mode;
    void **vtbl;
    GetAdapterDisplayModeFn get_mode = NULL;
    HWND hwnd;
    char buf[192];

    if (!borderless_enabled || !pp) return;

    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : focus_window;
    if (hwnd) {
        pp->hDeviceWindow = hwnd;
        borderless_window = hwnd;
    }

    ZeroMemory(&mode, sizeof(mode));
    if (d3d) {
        vtbl = *(void ***)d3d;
        if (vtbl) memcpy(&get_mode, &vtbl[8], sizeof(get_mode));
    }
    if (get_mode && SUCCEEDED(get_mode(d3d, adapter, &mode))) {
        pp->BackBufferFormat = mode.Format;
        borderless_display_format = mode.Format;
    }

    pp->Windowed = TRUE;
    pp->FullScreen_RefreshRateInHz = 0;

    make_borderless_window(hwnd);
    wsprintfA(buf, "borderless CreateDevice %lux%lu fmt=%lu hwnd=%p\\n",
        (unsigned long)pp->BackBufferWidth,
        (unsigned long)pp->BackBufferHeight,
        (unsigned long)pp->BackBufferFormat, hwnd);
    log_line(buf);
}

static void prepare_borderless_reset(void *presentation_parameters)
{
    D3DPresentParameters8Local *pp = (D3DPresentParameters8Local *)presentation_parameters;
    HWND hwnd;
    char buf[192];

    if (!borderless_enabled || !pp) return;

    hwnd = pp->hDeviceWindow ? pp->hDeviceWindow : borderless_window;
    if (hwnd) {
        pp->hDeviceWindow = hwnd;
        borderless_window = hwnd;
    }
    if (borderless_display_format) pp->BackBufferFormat = borderless_display_format;
    pp->Windowed = TRUE;
    pp->FullScreen_RefreshRateInHz = 0;

    make_borderless_window(hwnd);
    wsprintfA(buf, "borderless Reset %lux%lu fmt=%lu hwnd=%p\\n",
        (unsigned long)pp->BackBufferWidth,
        (unsigned long)pp->BackBufferHeight,
        (unsigned long)pp->BackBufferFormat, hwnd);
    log_line(buf);
}

static HRESULT WINAPI fake_Reset(void *self, void *presentation_parameters)
{
    HRESULT hr;
    prepare_borderless_reset(presentation_parameters);
    hr = real_Reset ? real_Reset(self, presentation_parameters) : E_FAIL;
    if (SUCCEEDED(hr) && borderless_enabled) make_borderless_window(borderless_window);
    return hr;
}

'''
text = text.replace(marker, helpers + marker, 1)

replace_once(
'''{
    HRESULT hr;

    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,
''',
'''{
    HRESULT hr;

    prepare_borderless_create(self, adapter, focus_window, presentation_parameters);
    hr = real_CreateDevice(self, adapter, device_type, focus_window, behavior_flags,
''',
"CreateDevice borderless preparation",
)

replace_once(
'''        void **vtbl = *(void ***)*returned_device;
        int shader_ok, constants_ok, stream_ok;
        log_line("CreateDevice intercepted; patching device vtable\\n");
        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);
''',
'''        void **vtbl = *(void ***)*returned_device;
        int reset_ok, shader_ok, constants_ok, stream_ok;
        log_line("CreateDevice intercepted; patching device vtable\\n");
        reset_ok = patch_vtable_slot(vtbl, 14, fake_Reset, (void **)&real_Reset);
        shader_ok = patch_vtable_slot(vtbl, 76, fake_SetVertexShader, (void **)&real_SetVertexShader);
''',
"Reset vtable hook",
)

replace_once(
'''        if (shader_ok && constants_ok && stream_ok) {
''',
'''        if (reset_ok && shader_ok && constants_ok && stream_ok) {
''',
"hook success condition",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern D3D8 borderless patch")
