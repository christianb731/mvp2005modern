from pathlib import Path

RUNTIME = Path("src/runtime.c")
text = RUNTIME.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller runtime probe v9 {label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
'''typedef HRESULT (WINAPI *SetVertexShaderConstantFn)(void *self, DWORD register_address,\n''',
'''typedef HRESULT (WINAPI *DirectInputCreateAFn)(HINSTANCE inst, DWORD version, void **returned_di, void *outer);\ntypedef HRESULT (WINAPI *DICreateDeviceFn)(void *self, const GUID *guid, void **returned_device, void *outer);\ntypedef HRESULT (WINAPI *DIGetDeviceStateFn)(void *self, DWORD data_size, void *data);\ntypedef HRESULT (WINAPI *DISetDataFormatFn)(void *self, const void *format);\ntypedef struct DIDataFormatHeaderControllerProbe {\n    DWORD dwSize;\n    DWORD dwObjSize;\n    DWORD dwFlags;\n    DWORD dwDataSize;\n    DWORD dwNumObjs;\n    const void *rgodf;\n} DIDataFormatHeaderControllerProbe;\ntypedef struct ControllerProbeDevice {\n    void *device;\n    GUID guid;\n    DWORD format_size;\n    DWORD format_objects;\n    DWORD previous_buttons;\n    int previous_valid;\n} ControllerProbeDevice;\ntypedef HRESULT (WINAPI *SetVertexShaderConstantFn)(void *self, DWORD register_address,\n''',
"typedefs",
)

# RC1 has ResetFn globals from the borderless patch. Keep the diagnostic state
# separate from normal Debug logging so the user does not need to change config.
replace_once(
'''static ResetFn real_Reset;\n''',
'''static ResetFn real_Reset;\nstatic void *volatile controller_probe_real_DirectInputCreateA;\nstatic DICreateDeviceFn controller_probe_real_CreateDevice;\nstatic DIGetDeviceStateFn controller_probe_real_GetDeviceState;\nstatic DISetDataFormatFn controller_probe_real_SetDataFormat;\nstatic ControllerProbeDevice controller_probe_devices[8];\nstatic LONG controller_probe_device_count;\nstatic LONG controller_probe_log_initialized;\n''',
"globals",
)

marker = '''static HRESULT WINAPI fake_CreateDevice(void *self, UINT adapter, DWORD device_type, HWND focus_window,\n'''
if text.count(marker) != 1:
    raise SystemExit(f"controller runtime probe v9 insertion marker: expected one match, found {text.count(marker)}")

probe = r'''static int controller_probe_guid_equal(const GUID *a, const GUID *b)
{
    return a && b && memcmp(a, b, sizeof(GUID)) == 0;
}

static int controller_probe_is_system_device(const GUID *guid)
{
    static const GUID sys_mouse = {
        0x6F1D2B60, 0xD5A0, 0x11CF,
        {0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00}
    };
    static const GUID sys_keyboard = {
        0x6F1D2B61, 0xD5A0, 0x11CF,
        {0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00}
    };
    return controller_probe_guid_equal(guid, &sys_mouse) ||
        controller_probe_guid_equal(guid, &sys_keyboard);
}

static void controller_probe_log(const char *text)
{
    char path[MAX_PATH];
    HANDLE file;
    DWORD written;
    DWORD disposition;

    if (!get_module_dir(path, sizeof(path)) ||
        !append_path(path, sizeof(path), "mvp2005controller.log")) return;

    disposition = InterlockedCompareExchange(&controller_probe_log_initialized, 1, 0) == 0 ?
        CREATE_ALWAYS : OPEN_ALWAYS;
    file = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL, disposition, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    if (disposition == OPEN_ALWAYS) SetFilePointer(file, 0, NULL, FILE_END);
    WriteFile(file, text, lstrlenA(text), &written, NULL);
    CloseHandle(file);
}

static ControllerProbeDevice *controller_probe_find(void *device)
{
    LONG count = InterlockedCompareExchange(&controller_probe_device_count, 0, 0);
    LONG i;
    if (count > 8) count = 8;
    for (i = 0; i < count; i++)
        if (controller_probe_devices[i].device == device) return &controller_probe_devices[i];
    return NULL;
}

static ControllerProbeDevice *controller_probe_add(void *device, const GUID *guid)
{
    LONG index;
    ControllerProbeDevice *slot;
    if (!device || !guid) return NULL;
    slot = controller_probe_find(device);
    if (slot) return slot;
    index = InterlockedIncrement(&controller_probe_device_count) - 1;
    if (index < 0 || index >= 8) return NULL;
    slot = &controller_probe_devices[index];
    ZeroMemory(slot, sizeof(*slot));
    slot->device = device;
    slot->guid = *guid;
    return slot;
}

static void controller_probe_log_buttons(ControllerProbeDevice *slot,
    DWORD data_size, const BYTE *data)
{
    DWORD mask = 0;
    DWORD i;
    char buf[512];
    int pos;

    /* Both DIJOYSTATE and DIJOYSTATE2 place the button array at byte 48.
     * MVP's normal controller format is DIJOYSTATE-sized (80 bytes). */
    if (!slot || !data || data_size < 80) return;
    for (i = 0; i < 32 && 48 + i < data_size; i++) {
        if (data[48 + i] & 0x80) mask |= (1UL << i);
    }
    if (slot->previous_valid && mask == slot->previous_buttons) return;
    slot->previous_valid = 1;
    slot->previous_buttons = mask;

    pos = snprintf(buf, sizeof(buf), "buttons size=%lu pressed=",
        (unsigned long)data_size);
    if (!mask) {
        snprintf(buf + pos, sizeof(buf) - pos, "none\r\n");
    } else {
        int first = 1;
        for (i = 0; i < 32; i++) {
            if (mask & (1UL << i)) {
                int wrote = snprintf(buf + pos, sizeof(buf) - pos,
                    "%sDI[%lu]/MVP[%lu]", first ? "" : ",",
                    (unsigned long)i, (unsigned long)(i + 1));
                if (wrote <= 0 || (DWORD)wrote >= sizeof(buf) - pos) break;
                pos += wrote;
                first = 0;
            }
        }
        snprintf(buf + pos, sizeof(buf) - pos, "\r\n");
    }
    controller_probe_log(buf);
}

static HRESULT WINAPI controller_probe_GetDeviceState(void *self, DWORD data_size, void *data)
{
    HRESULT hr = controller_probe_real_GetDeviceState ?
        controller_probe_real_GetDeviceState(self, data_size, data) : E_FAIL;
    ControllerProbeDevice *slot = controller_probe_find(self);
    if (SUCCEEDED(hr) && slot && data)
        controller_probe_log_buttons(slot, data_size, (const BYTE *)data);
    return hr;
}

static HRESULT WINAPI controller_probe_SetDataFormat(void *self, const void *format)
{
    ControllerProbeDevice *slot = controller_probe_find(self);
    if (slot && format) {
        const DIDataFormatHeaderControllerProbe *f =
            (const DIDataFormatHeaderControllerProbe *)format;
        char buf[256];
        slot->format_size = f->dwDataSize;
        slot->format_objects = f->dwNumObjs;
        wsprintfA(buf,
            "controller SetDataFormat dataSize=%lu numObjs=%lu objSize=%lu flags=%08lx\r\n",
            (unsigned long)f->dwDataSize,
            (unsigned long)f->dwNumObjs,
            (unsigned long)f->dwObjSize,
            (unsigned long)f->dwFlags);
        controller_probe_log(buf);
    }
    return controller_probe_real_SetDataFormat ?
        controller_probe_real_SetDataFormat(self, format) : E_FAIL;
}

static void controller_probe_patch_device(void *device, const GUID *guid)
{
    void **vtbl;
    ControllerProbeDevice *slot;
    int state_ok, format_ok;
    char buf[256];

    if (!device || !guid || controller_probe_is_system_device(guid)) return;
    slot = controller_probe_add(device, guid);
    if (!slot) return;
    vtbl = *(void ***)device;
    if (!vtbl) return;

    state_ok = patch_vtable_slot(vtbl, 9, controller_probe_GetDeviceState,
        (void **)&controller_probe_real_GetDeviceState);
    format_ok = patch_vtable_slot(vtbl, 11, controller_probe_SetDataFormat,
        (void **)&controller_probe_real_SetDataFormat);

    wsprintfA(buf,
        "controller CreateDevice guid=%08lx-%04x-%04x hooks state=%d format=%d self=%p\r\n",
        (unsigned long)guid->Data1,
        (unsigned int)guid->Data2,
        (unsigned int)guid->Data3,
        state_ok, format_ok, device);
    controller_probe_log(buf);
}

static HRESULT WINAPI controller_probe_CreateDevice(void *self, const GUID *guid,
    void **returned_device, void *outer)
{
    HRESULT hr = controller_probe_real_CreateDevice ?
        controller_probe_real_CreateDevice(self, guid, returned_device, outer) : E_FAIL;
    if (SUCCEEDED(hr) && returned_device && *returned_device && guid)
        controller_probe_patch_device(*returned_device, guid);
    return hr;
}

static HRESULT WINAPI controller_probe_DirectInputCreateA(HINSTANCE inst, DWORD version,
    void **returned_di, void *outer)
{
    DirectInputCreateAFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(
        &controller_probe_real_DirectInputCreateA, NULL, NULL);
    HRESULT hr;
    char buf[192];

    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return E_FAIL;
    hr = fn(inst, version, returned_di, outer);
    wsprintfA(buf, "DirectInputCreateA version=%08lx hr=%08lx\r\n",
        (unsigned long)version, (unsigned long)hr);
    controller_probe_log(buf);

    if (SUCCEEDED(hr) && returned_di && *returned_di) {
        void **vtbl = *(void ***)*returned_di;
        int ok = vtbl && patch_vtable_slot(vtbl, 3,
            controller_probe_CreateDevice, (void **)&controller_probe_real_CreateDevice);
        controller_probe_log(ok ?
            "DirectInput CreateDevice hook installed\r\n" :
            "DirectInput CreateDevice hook FAILED\r\n");
    }
    return hr;
}

static void install_controller_runtime_probe(void)
{
    HMODULE dinput = GetModuleHandleA("dinput.dll");
    void *target;
    controller_probe_log("MVP2005 Modern controller runtime probe v9 starting\r\n");
    if (!dinput) {
        controller_probe_log("dinput.dll not loaded when probe installed\r\n");
        return;
    }
    target = (void *)GetProcAddress(dinput, "DirectInputCreateA");
    controller_probe_log(hook_function(target, controller_probe_DirectInputCreateA,
        &controller_probe_real_DirectInputCreateA) > 0 ?
        "DirectInputCreateA hook installed\r\n" :
        "DirectInputCreateA hook FAILED\r\n");
}

'''

text = text.replace(marker, probe + marker, 1)

replace_once(
'''    install_save_fix();\n''',
'''    install_save_fix();\n    install_controller_runtime_probe();\n''',
"install probe",
)

RUNTIME.write_text(text, encoding="utf-8")
print("Applied MVP2005 Modern in-game DirectInput controller runtime probe v9")
