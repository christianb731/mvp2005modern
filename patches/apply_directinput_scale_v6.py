from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


# v6 assumes apply_mouse_getcursor_v4.py has already run. That patch gives us:
#   borderless_window, borderless_logical_width/height, and SetCursorPos suppression.
replace_once(
'''typedef HRESULT (WINAPI *SetVertexShaderConstantFn)(void *self, DWORD register_address,
''',
'''typedef HRESULT (WINAPI *DirectInputCreateAFn)(HINSTANCE inst, DWORD version, void **returned_di, void *outer);
typedef HRESULT (WINAPI *DICreateDeviceFn)(void *self, const GUID *guid, void **returned_device, void *outer);
typedef HRESULT (WINAPI *DIGetDeviceStateFn)(void *self, DWORD data_size, void *data);
typedef HRESULT (WINAPI *DIGetDeviceDataFn)(void *self, DWORD object_size, void *data, DWORD *count, DWORD flags);
typedef HRESULT (WINAPI *DISetDataFormatFn)(void *self, const void *format);
typedef struct DIDataFormatHeaderLocal {
    DWORD dwSize;
    DWORD dwObjSize;
    DWORD dwFlags;
    DWORD dwDataSize;
    DWORD dwNumObjs;
    const void *rgodf;
} DIDataFormatHeaderLocal;
typedef struct DIDeviceObjectDataLocal {
    DWORD dwOfs;
    DWORD dwData;
    DWORD dwTimeStamp;
    DWORD dwSequence;
} DIDeviceObjectDataLocal;
typedef HRESULT (WINAPI *SetVertexShaderConstantFn)(void *self, DWORD register_address,
''',
"DirectInput typedefs",
)

replace_once(
'''static ResetFn real_Reset;
''',
'''static ResetFn real_Reset;
static void *volatile real_DirectInputCreateAPtr;
static DICreateDeviceFn real_DICreateDevice;
static DIGetDeviceStateFn real_DIGetDeviceState;
static DIGetDeviceDataFn real_DIGetDeviceData;
static DISetDataFormatFn real_DISetDataFormat;
static void *di_mouse_devices[8];
static LONG di_mouse_device_count;
static int di_mouse_relative;
static LONGLONG di_mouse_remainder_x;
static LONGLONG di_mouse_remainder_y;
static LONG di_mouse_scale_log_count;
''',
"DirectInput globals",
)

marker = '''static HRESULT WINAPI fake_CreateDevice(void *self, UINT adapter, DWORD device_type, HWND focus_window,
'''
if text.count(marker) != 1:
    raise SystemExit(f"DirectInput insertion marker: expected exactly one match, found {text.count(marker)}")

code = r'''static int is_sys_mouse_guid(const GUID *guid)
{
    static const GUID sys_mouse = {
        0x6F1D2B60, 0xD5A0, 0x11CF,
        {0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00}
    };
    return guid && memcmp(guid, &sys_mouse, sizeof(sys_mouse)) == 0;
}

static int is_known_mouse_device(void *self)
{
    LONG i;
    LONG count = InterlockedCompareExchange(&di_mouse_device_count, 0, 0);
    if (count > 8) count = 8;
    for (i = 0; i < count; i++) {
        if (di_mouse_devices[i] == self) return 1;
    }
    return 0;
}

static void remember_mouse_device(void *device)
{
    LONG i;
    LONG count;
    if (!device) return;
    count = InterlockedCompareExchange(&di_mouse_device_count, 0, 0);
    if (count > 8) count = 8;
    for (i = 0; i < count; i++) {
        if (di_mouse_devices[i] == device) return;
    }
    if (count < 8) {
        di_mouse_devices[count] = device;
        InterlockedExchange(&di_mouse_device_count, count + 1);
    }
}

static LONG scale_relative_axis(LONG delta, UINT logical_size, int physical_size, LONGLONG *remainder)
{
    LONGLONG numerator;
    LONGLONG result;

    if (!logical_size || physical_size <= 0 || logical_size == (UINT)physical_size)
        return delta;

    numerator = (LONGLONG)delta * (LONGLONG)logical_size + *remainder;
    result = numerator / (LONGLONG)physical_size;
    *remainder = numerator - result * (LONGLONG)physical_size;
    return (LONG)result;
}

static void scale_relative_mouse_delta(LONG *x, LONG *y)
{
    RECT rc;
    int client_width;
    int client_height;
    LONG old_x;
    LONG old_y;

    if (!x || !y || !borderless_enabled || !borderless_window ||
        !borderless_logical_width || !borderless_logical_height ||
        !di_mouse_relative) return;
    if (GetForegroundWindow() != borderless_window) return;
    if (!GetClientRect(borderless_window, &rc)) return;

    client_width = rc.right - rc.left;
    client_height = rc.bottom - rc.top;
    if (client_width <= 0 || client_height <= 0) return;

    old_x = *x;
    old_y = *y;
    *x = scale_relative_axis(*x, borderless_logical_width, client_width, &di_mouse_remainder_x);
    *y = scale_relative_axis(*y, borderless_logical_height, client_height, &di_mouse_remainder_y);

    if ((old_x || old_y) && InterlockedIncrement(&di_mouse_scale_log_count) <= 24) {
        char buf[224];
        wsprintfA(buf,
            "DirectInput mouse delta %ld,%ld -> %ld,%ld client=%dx%d logical=%lux%lu\\n",
            old_x, old_y, *x, *y,
            client_width, client_height,
            (unsigned long)borderless_logical_width,
            (unsigned long)borderless_logical_height);
        log_line(buf);
    }
}

static HRESULT WINAPI fake_DIGetDeviceState(void *self, DWORD data_size, void *data)
{
    HRESULT hr = real_DIGetDeviceState ? real_DIGetDeviceState(self, data_size, data) : E_FAIL;

    /* Standard DirectInput mouse format is DIMOUSESTATE: 3 LONG axes + 4 buttons = 16 bytes. */
    if (SUCCEEDED(hr) && data && data_size >= 12 && is_known_mouse_device(self)) {
        LONG *axis = (LONG *)data;
        scale_relative_mouse_delta(&axis[0], &axis[1]);
    }
    return hr;
}

static HRESULT WINAPI fake_DIGetDeviceData(void *self, DWORD object_size, void *data,
    DWORD *count, DWORD flags)
{
    HRESULT hr = real_DIGetDeviceData ?
        real_DIGetDeviceData(self, object_size, data, count, flags) : E_FAIL;

    if (SUCCEEDED(hr) && data && count && object_size >= sizeof(DIDeviceObjectDataLocal) &&
        is_known_mouse_device(self) && di_mouse_relative) {
        DWORD i;
        BYTE *cursor = (BYTE *)data;
        for (i = 0; i < *count; i++, cursor += object_size) {
            DIDeviceObjectDataLocal *obj = (DIDeviceObjectDataLocal *)cursor;
            if (obj->dwOfs == 0) {
                LONG x = (LONG)obj->dwData;
                LONG y = 0;
                scale_relative_mouse_delta(&x, &y);
                obj->dwData = (DWORD)x;
            } else if (obj->dwOfs == 4) {
                LONG x = 0;
                LONG y = (LONG)obj->dwData;
                scale_relative_mouse_delta(&x, &y);
                obj->dwData = (DWORD)y;
            }
        }
    }
    return hr;
}

static HRESULT WINAPI fake_DISetDataFormat(void *self, const void *format)
{
    HRESULT hr;

    if (format && is_known_mouse_device(self)) {
        const DIDataFormatHeaderLocal *f = (const DIDataFormatHeaderLocal *)format;
        /* DIDF_RELAXIS = 0x00000002, DIDF_ABSAXIS = 0x00000001. */
        di_mouse_relative = (f->dwFlags & 0x00000002UL) != 0;
        di_mouse_remainder_x = 0;
        di_mouse_remainder_y = 0;
        {
            char buf[192];
            wsprintfA(buf,
                "DirectInput mouse format flags=%08lx relative=%d dataSize=%lu numObjs=%lu\\n",
                (unsigned long)f->dwFlags,
                di_mouse_relative,
                (unsigned long)f->dwDataSize,
                (unsigned long)f->dwNumObjs);
            log_line(buf);
        }
    }

    hr = real_DISetDataFormat ? real_DISetDataFormat(self, format) : E_FAIL;
    return hr;
}

static void patch_directinput_mouse_device(void *device)
{
    void **vtbl;
    int state_ok = 1;
    int data_ok = 1;
    int format_ok = 1;

    if (!device) return;
    remember_mouse_device(device);
    vtbl = *(void ***)device;
    if (!vtbl) return;

    /* DirectInput devices share implementation vtables. Patch them once; all
     * non-mouse calls pass through unchanged because the hooks check self. */
    if (!real_DIGetDeviceState)
        state_ok = patch_vtable_slot(vtbl, 9, fake_DIGetDeviceState, (void **)&real_DIGetDeviceState);
    if (!real_DIGetDeviceData)
        data_ok = patch_vtable_slot(vtbl, 10, fake_DIGetDeviceData, (void **)&real_DIGetDeviceData);
    if (!real_DISetDataFormat)
        format_ok = patch_vtable_slot(vtbl, 11, fake_DISetDataFormat, (void **)&real_DISetDataFormat);

    if (state_ok && data_ok && format_ok)
        log_line("DirectInput relative mouse scaling hooks installed\\n");
    else
        log_line("DirectInput relative mouse scaling hooks incomplete\\n");
}

static HRESULT WINAPI fake_DICreateDevice(void *self, const GUID *guid,
    void **returned_device, void *outer)
{
    HRESULT hr = real_DICreateDevice ?
        real_DICreateDevice(self, guid, returned_device, outer) : E_FAIL;

    if (SUCCEEDED(hr) && returned_device && *returned_device && is_sys_mouse_guid(guid)) {
        log_line("DirectInput system mouse created\\n");
        patch_directinput_mouse_device(*returned_device);
    }
    return hr;
}

static HRESULT WINAPI fake_DirectInputCreateA(HINSTANCE inst, DWORD version,
    void **returned_di, void *outer)
{
    DirectInputCreateAFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_DirectInputCreateAPtr, NULL, NULL);
    HRESULT hr;

    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return E_FAIL;

    hr = fn(inst, version, returned_di, outer);
    if (SUCCEEDED(hr) && returned_di && *returned_di) {
        void **vtbl = *(void ***)*returned_di;
        if (vtbl && !real_DICreateDevice &&
            patch_vtable_slot(vtbl, 3, fake_DICreateDevice, (void **)&real_DICreateDevice))
            log_line("DirectInput CreateDevice hook installed\\n");
    }
    return hr;
}

static void install_directinput_mouse_scaler(void)
{
    HMODULE dinput;
    void *target;

    if (!borderless_enabled) return;
    dinput = GetModuleHandleA("dinput.dll");
    if (!dinput) {
        log_line("DirectInput scaler: dinput.dll not loaded\\n");
        return;
    }
    target = (void *)GetProcAddress(dinput, "DirectInputCreateA");
    log_line(hook_function(target, fake_DirectInputCreateA, &real_DirectInputCreateAPtr) > 0 ?
        "DirectInput relative mouse scaler installed\\n" :
        "DirectInput relative mouse scaler failed or conflicted\\n");
}

'''
text = text.replace(marker, code + marker, 1)

replace_once(
'''    install_save_fix();
    install_borderless_cursor_poll_fix();
''',
'''    install_save_fix();
    install_borderless_cursor_poll_fix();
    install_directinput_mouse_scaler();
''',
"install DirectInput relative mouse scaler",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern DirectInput relative mouse scaling")
