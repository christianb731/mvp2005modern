/* QA-only D3D8 windowed mode for the isolated smoke executable. */
static int smoke_display_windowed;
static DWORD smoke_display_format;
static HWND smoke_display_window;

static void load_smoke_display_mode(const char *ini)
{
    char mode[24], exe[MAX_PATH];
    DWORD length = GetModuleFileNameA(NULL, exe, sizeof(exe));
    const char *base = length && length < sizeof(exe) ? strrchr(exe, '\\') : NULL;
    if (base && !_stricmp(base + 1, "MVP2005Smoke.exe") && !borderless_enabled &&
        GetPrivateProfileStringA("DisplayTest", "Mode", "", mode, sizeof(mode), ini) &&
        !_stricmp(mode, "windowed"))
        smoke_display_windowed = 1;
}

static void prepare_smoke_windowed(void *d3d, UINT adapter, HWND focus, void *parameters)
{
    D3DPresentParameters8Local *pp = parameters;
    if (!smoke_display_windowed || !pp) return;
    if (d3d) {
        void **vtbl = *(void ***)d3d;
        GetAdapterDisplayModeFn get_mode = NULL;
        D3DDisplayMode8Local mode;
        if (vtbl) memcpy(&get_mode, &vtbl[8], sizeof(get_mode));
        if (get_mode && SUCCEEDED(get_mode(d3d, adapter, &mode)))
            smoke_display_format = mode.Format;
    }
    if (pp->hDeviceWindow) smoke_display_window = pp->hDeviceWindow;
    else if (focus) smoke_display_window = focus;
    if (smoke_display_window) pp->hDeviceWindow = smoke_display_window;
    if (smoke_display_format) pp->BackBufferFormat = smoke_display_format;
    pp->Windowed = TRUE;
    pp->FullScreen_RefreshRateInHz = 0;
    pp->FullScreen_PresentationInterval = 0;
}

static void finish_smoke_windowed(HRESULT hr, void *parameters, const char *operation)
{
    D3DPresentParameters8Local *pp = parameters;
    HWND hwnd = smoke_display_window;
    char window_class[64], line[160];
    RECT rect;
    MONITORINFO monitor;
    DWORD style, ex_style;
    int width, height, ok = 0;
    if (!smoke_display_windowed || !pp) return;
    if (SUCCEEDED(hr) && hwnd && GetClassNameA(hwnd, window_class, sizeof(window_class)) &&
        !strcmp(window_class, "MVP Baseball 2005") &&
        pp->BackBufferWidth && pp->BackBufferWidth <= 65535 &&
        pp->BackBufferHeight && pp->BackBufferHeight <= 65535) {
        style = ((DWORD)GetWindowLongA(hwnd, GWL_STYLE) & ~WS_POPUP) | WS_OVERLAPPEDWINDOW;
        ex_style = (DWORD)GetWindowLongA(hwnd, GWL_EXSTYLE);
        SetRect(&rect, 0, 0, (int)pp->BackBufferWidth, (int)pp->BackBufferHeight);
        monitor.cbSize = sizeof(monitor);
        if (AdjustWindowRectEx(&rect, style, FALSE, ex_style) &&
            GetMonitorInfoA(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), &monitor)) {
            width = rect.right - rect.left;
            height = rect.bottom - rect.top;
            SetWindowLongA(hwnd, GWL_STYLE, (LONG)style);
            ok = SetWindowPos(hwnd, NULL, monitor.rcWork.left + 32, monitor.rcWork.top + 32,
                width, height, SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
        }
    }
    snprintf(line, sizeof(line), "smoke windowed %s hr=%08lx hwnd=%p layout=%d\n",
        operation, (unsigned long)hr, hwnd, ok != 0);
    log_line(line);
}
