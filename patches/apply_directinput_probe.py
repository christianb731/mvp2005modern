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
'''typedef HRESULT (WINAPI *DirectInputCreateAFn)(HINSTANCE inst, DWORD version, void **returned_di, void *outer);
typedef HRESULT (WINAPI *DICreateDeviceFn)(void *self, const GUID *guid, void **returned_device, void *outer);
typedef HRESULT (WINAPI *DIGetDeviceStateFn)(void *self, DWORD data_size, void *data);
typedef HRESULT (WINAPI *DIGetDeviceDataFn)(void *self, DWORD object_size, void *data, DWORD *count, DWORD flags);
typedef HRESULT (WINAPI *DISetDataFormatFn)(void *self, const void *format);
typedef HRESULT (WINAPI *DISetCooperativeLevelFn)(void *self, HWND hwnd, DWORD flags);
typedef struct DIDataFormatHeaderLocal {
    DWORD dwSize;
    DWORD dwObjSize;
    DWORD dwFlags;
    DWORD dwDataSize;
    DWORD dwNumObjs;
    const void *rgodf;
} DIDataFormatHeaderLocal;
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
static DISetCooperativeLevelFn real_DISetCooperativeLevel;
static LONG di_state_log_count;
static LONG di_data_log_count;
''',
"DirectInput globals",
)

marker = '''static HRESULT WINAPI fake_CreateDevice(void *self, UINT adapter, DWORD device_type, HWND focus_window,
'''
if text.count(marker) != 1:
    raise SystemExit(f"DirectInput insertion marker: expected exactly one match, found {text.count(marker)}")

probe = r'''static int is_sys_mouse_guid(const GUID *guid)
{
    static const GUID sys_mouse = {
        0x6F1D2B60, 0xD5A0, 0x11CF,
        {0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00}
    };
    return guid && memcmp(guid, &sys_mouse, sizeof(sys_mouse)) == 0;
}

static HRESULT WINAPI fake_DIGetDeviceState(void *self, DWORD data_size, void *data)
{
    HRESULT hr = real_DIGetDeviceState ? real_DIGetDeviceState(self, data_size, data) : E_FAIL;

    if (SUCCEEDED(hr) && data && data_size >= 12 &&
        InterlockedIncrement(&di_state_log_count) <= 40) {
        LONG *axis = (LONG *)data;
        char buf[192];
        wsprintfA(buf, "DirectInput GetDeviceState size=%lu x=%ld y=%ld z=%ld\\n",
            (unsigned long)data_size, axis[0], axis[1], axis[2]);
        log_line(buf);
    }
    return hr;
}

static HRESULT WINAPI fake_DIGetDeviceData(void *self, DWORD object_size, void *data,
    DWORD *count, DWORD flags)
{
    DWORD requested = count ? *count : 0;
    HRESULT hr = real_DIGetDeviceData ?
        real_DIGetDeviceData(self, object_size, data, count, flags) : E_FAIL;

    if (InterlockedIncrement(&di_data_log_count) <= 20) {
        char buf[192];
        wsprintfA(buf,
            "DirectInput GetDeviceData obj=%lu requested=%lu returned=%lu flags=%08lx hr=%08lx\\n",
            (unsigned long)object_size,
            (unsigned long)requested,
            (unsigned long)(count ? *count : 0),
            (unsigned long)flags,
            (unsigned long)hr);
        log_line(buf);
    }
    return hr;
}

static HRESULT WINAPI fake_DISetDataFormat(void *self, const void *format)
{
    HRESULT hr;
    if (format) {
        const DIDataFormatHeaderLocal *f = (const DIDataFormatHeaderLocal *)format;
        char buf[192];
        wsprintfA(buf,
            "DirectInput SetDataFormat flags=%08lx dataSize=%lu numObjs=%lu objSize=%lu\\n",
            (unsigned long)f->dwFlags,
            (unsigned long)f->dwDataSize,
            (unsigned long)f->dwNumObjs,
            (unsigned long)f->dwObjSize);
        log_line(buf);
    }
    hr = real_DISetDataFormat ? real_DISetDataFormat(self, format) : E_FAIL;
    return hr;
}

static HRESULT WINAPI fake_DISetCooperativeLevel(void *self, HWND hwnd, DWORD flags)
{
    char buf[160];
    wsprintfA(buf, "DirectInput SetCooperativeLevel hwnd=%p flags=%08lx\\n",
        hwnd, (unsigned long)flags);
    log_line(buf);
    return real_DISetCooperativeLevel ? real_DISetCooperativeLevel(self, hwnd, flags) : E_FAIL;
}

static void patch_directinput_mouse_device(void *device)
{
    void **vtbl;
    int state_ok, data_ok, format_ok, coop_ok;

    if (!device) return;
    vtbl = *(void ***)device;
    if (!vtbl) return;

    state_ok = patch_vtable_slot(vtbl, 9, fake_DIGetDeviceState, (void **)&real_DIGetDeviceState);
    data_ok = patch_vtable_slot(vtbl, 10, fake_DIGetDeviceData, (void **)&real_DIGetDeviceData);
    format_ok = patch_vtable_slot(vtbl, 11, fake_DISetDataFormat, (void **)&real_DISetDataFormat);
    coop_ok = patch_vtable_slot(vtbl, 13, fake_DISetCooperativeLevel, (void **)&real_DISetCooperativeLevel);

    if (state_ok && data_ok && format_ok && coop_ok)
        log_line("DirectInput mouse device probe hooks installed\\n");
    else
        log_line("DirectInput mouse device probe hooks incomplete\\n");
}

static HRESULT WINAPI fake_DICreateDevice(void *self, const GUID *guid,
    void **returned_device, void *outer)
{
    HRESULT hr = real_DICreateDevice ?
        real_DICreateDevice(self, guid, returned_device, outer) : E_FAIL;
    char buf[192];

    if (guid) {
        wsprintfA(buf,
            "DirectInput CreateDevice guid=%08lx-%04x-%04x mouse=%d hr=%08lx\\n",
            (unsigned long)guid->Data1,
            (unsigned int)guid->Data2,
            (unsigned int)guid->Data3,
            is_sys_mouse_guid(guid),
            (unsigned long)hr);
        log_line(buf);
    }

    if (SUCCEEDED(hr) && returned_device && *returned_device && is_sys_mouse_guid(guid))
        patch_directinput_mouse_device(*returned_device);
    return hr;
}

static HRESULT WINAPI fake_DirectInputCreateA(HINSTANCE inst, DWORD version,
    void **returned_di, void *outer)
{
    DirectInputCreateAFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&real_DirectInputCreateAPtr, NULL, NULL);
    HRESULT hr;
    char buf[160];

    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return E_FAIL;

    hr = fn(inst, version, returned_di, outer);
    wsprintfA(buf, "DirectInputCreateA version=%08lx hr=%08lx\\n",
        (unsigned long)version, (unsigned long)hr);
    log_line(buf);

    if (SUCCEEDED(hr) && returned_di && *returned_di) {
        void **vtbl = *(void ***)*returned_di;
        if (vtbl && patch_vtable_slot(vtbl, 3, fake_DICreateDevice, (void **)&real_DICreateDevice))
            log_line("DirectInput CreateDevice vtable probe installed\\n");
        else
            log_line("DirectInput CreateDevice vtable probe failed\\n");
    }
    return hr;
}

static void install_directinput_probe(void)
{
    HMODULE dinput;
    void *target;

    dinput = GetModuleHandleA("dinput.dll");
    if (!dinput) {
        log_line("DirectInput probe: dinput.dll not loaded\\n");
        return;
    }
    target = (void *)GetProcAddress(dinput, "DirectInputCreateA");
    log_line(hook_function(target, fake_DirectInputCreateA, &real_DirectInputCreateAPtr) > 0 ?
        "DirectInputCreateA probe hook installed\\n" :
        "DirectInputCreateA probe hook failed or conflicted\\n");
}

'''
text = text.replace(marker, probe + marker, 1)

replace_once(
'''    install_save_fix();
''',
'''    install_save_fix();
    install_directinput_probe();
''',
"install DirectInput probe",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern DirectInput mouse probe")
