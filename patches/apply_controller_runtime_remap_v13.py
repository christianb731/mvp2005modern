from pathlib import Path

RUNTIME = Path("src/runtime.c")
CONTROLLER = Path("src/controller_config.c")
runtime = RUNTIME.read_text(encoding="utf-8")
controller = CONTROLLER.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller runtime remap v13 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Launcher/controller configurator
# ---------------------------------------------------------------------------
# v0.10/v0.11 proved the physical Flydigi stream is DI[0..9], while the actual
# in-game symptoms prove MVP's controller.cfg button N lookup is effectively
# reading DI index N on this modern DirectInput path: L3 (DI8) triggers Start
# (controller.cfg button 8), X (DI2) triggers the button-2 action, etc.
#
# Writing button 0 directly is not a reliable solution for MVP's legacy parser.
# Instead keep controller.cfg in its conventional one-based 1..10 layout and
# normalize the physical DirectInput state inside the runtime DLL.

marker = '''static void button_value(char *out, DWORD out_size, int button)\n{\n    snprintf(out, out_size, "button %d", button);\n}\n\n'''
if controller.count(marker) != 1:
    raise SystemExit("controller runtime remap v13: button_value marker not found")

helpers = r'''static int get_controller_runtime_ini_path(char *path, DWORD path_size)
{
    char *slash;
    if (!GetModuleFileNameA(NULL, path, path_size)) return 0;
    path[path_size - 1] = 0;
    slash = path + lstrlenA(path);
    while (slash > path && slash[-1] != '\\' && slash[-1] != '/') slash--;
    *slash = 0;
    if (lstrlenA(path) + 16 >= (int)path_size) return 0;
    lstrcatA(path, "mvp2005fix.ini");
    return 1;
}

static void write_controller_source_index(const char *ini, const char *key, int one_based_value)
{
    char value[16];
    int source = one_based_value - 1;
    if (source < 0) source = 0;
    wsprintfA(value, "%d", source);
    WritePrivateProfileStringA("Controller", key, value, ini);
}

static void save_runtime_button_remap(const ButtonMap *m, int generic_layout)
{
    char ini[MAX_PATH];
    if (!m || !get_controller_runtime_ini_path(ini, sizeof(ini))) return;

    /* Generic/older DirectInput pads keep their direct controller.cfg path for
     * now. The runtime normalizer is for Xbox-style modern pads where the
     * one-position legacy mismatch has been observed and verified in-game. */
    WritePrivateProfileStringA("Controller", "RemapEnabled",
        generic_layout ? "0" : "1", ini);
    if (generic_layout) return;

    write_controller_source_index(ini, "A", m->cross);
    write_controller_source_index(ini, "B", m->circle);
    write_controller_source_index(ini, "X", m->square);
    write_controller_source_index(ini, "Y", m->triangle);
    write_controller_source_index(ini, "LB", m->l1);
    write_controller_source_index(ini, "RB", m->r1);
    write_controller_source_index(ini, "View", m->select);
    write_controller_source_index(ini, "Start", m->start);
    write_controller_source_index(ini, "L3", m->l3);
    write_controller_source_index(ini, "R3", m->r3);
}

'''
controller = controller.replace(marker, marker + helpers, 1)

# Xbox-style controller.cfg should describe a stable logical MVP pad (1..10).
# The learned physical IDs are now consumed by the runtime remapper instead.
for old, new, label in [
    ('button_value(cross, sizeof(cross), m->cross);',
     'button_value(cross, sizeof(cross), generic_layout ? m->cross : 1);', 'A logical slot'),
    ('button_value(circle, sizeof(circle), m->circle);',
     'button_value(circle, sizeof(circle), generic_layout ? m->circle : 2);', 'B logical slot'),
    ('button_value(square, sizeof(square), m->square);',
     'button_value(square, sizeof(square), generic_layout ? m->square : 3);', 'X logical slot'),
    ('button_value(triangle, sizeof(triangle), m->triangle);',
     'button_value(triangle, sizeof(triangle), generic_layout ? m->triangle : 4);', 'Y logical slot'),
    ('button_value(l1, sizeof(l1), m->l1);',
     'button_value(l1, sizeof(l1), generic_layout ? m->l1 : 5);', 'LB logical slot'),
    ('button_value(r1, sizeof(r1), m->r1);',
     'button_value(r1, sizeof(r1), generic_layout ? m->r1 : 6);', 'RB logical slot'),
    ('button_value(select, sizeof(select), m->select);',
     'button_value(select, sizeof(select), generic_layout ? m->select : 7);', 'View logical slot'),
    ('button_value(start, sizeof(start), m->start);',
     'button_value(start, sizeof(start), generic_layout ? m->start : 8);', 'Start logical slot'),
    ('button_value(l3, sizeof(l3), m->l3);',
     'button_value(l3, sizeof(l3), generic_layout ? m->l3 : 9);', 'L3 logical slot'),
    ('button_value(r3, sizeof(r3), m->r3);',
     'button_value(r3, sizeof(r3), generic_layout ? m->r3 : 10);', 'R3 logical slot'),
]:
    controller = replace_once(controller, old, new, label)

status = '''    controller_status("Saved controller.cfg. This controller is now MVP Player 1; other gamepad Player 1 profiles were left intact but deactivated.");\n'''
controller = replace_once(
    controller,
    status,
    '''    save_runtime_button_remap(&map, preset == 1);\n    controller_status(preset == 1 ?\n        "Saved controller.cfg using direct generic DirectInput bindings." :\n        "Saved controller.cfg and enabled MVP Modern runtime button normalization for this Xbox-style controller.");\n''',
    "save remap configuration",
)

# Explain what the learned values mean without asking the user to reason about
# the legacy one-position mismatch.
controller = controller.replace(
    '"MVP button"', '"Detected button"', 1)
controller = controller.replace(
    '"Recommended: press each named button when prompted. Calibration now uses the same legacy DirectInput path as MVP Baseball 2005, then writes MVP-compatible button numbers automatically."',
    '"Recommended: press each named button when prompted. MVP Modern learns the physical input, then normalizes it at runtime so MVP receives a clean logical controller layout."',
    1,
)

CONTROLLER.write_text(controller, encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime DirectInput normalization
# ---------------------------------------------------------------------------
runtime = replace_once(
    runtime,
    '''typedef HRESULT (WINAPI *SetVertexShaderConstantFn)(void *self, DWORD register_address,\n''',
    '''typedef HRESULT (WINAPI *ControllerDirectInputCreateAFn)(HINSTANCE inst, DWORD version, void **returned_di, void *outer);\ntypedef HRESULT (WINAPI *ControllerDICreateDeviceFn)(void *self, const GUID *guid, void **returned_device, void *outer);\ntypedef HRESULT (WINAPI *ControllerDIGetDeviceStateFn)(void *self, DWORD data_size, void *data);\ntypedef HRESULT (WINAPI *SetVertexShaderConstantFn)(void *self, DWORD register_address,\n''',
    "runtime typedefs",
)

runtime = replace_once(
    runtime,
    '''static ResetFn real_Reset;\n''',
    '''static ResetFn real_Reset;\nstatic int controller_remap_enabled;\nstatic int controller_button_sources[10] = {0,1,2,3,4,5,6,7,8,9};\nstatic void *volatile controller_real_DirectInputCreateA;\nstatic ControllerDICreateDeviceFn controller_real_CreateDevice;\nstatic ControllerDIGetDeviceStateFn controller_real_GetDeviceState;\n''',
    "runtime globals",
)

runtime = replace_once(
    runtime,
    '''    save_fix_enabled = GetPrivateProfileIntA("SaveFix", "Enabled", 1, ini) != 0;\n''',
    '''    save_fix_enabled = GetPrivateProfileIntA("SaveFix", "Enabled", 1, ini) != 0;\n    controller_remap_enabled = GetPrivateProfileIntA("Controller", "RemapEnabled", 0, ini) != 0;\n    if (controller_remap_enabled) {\n        static const char *keys[10] = {"A","B","X","Y","LB","RB","View","Start","L3","R3"};\n        int i;\n        for (i = 0; i < 10; i++) {\n            int source = GetPrivateProfileIntA("Controller", keys[i], i, ini);\n            if (source >= 0 && source < 32) controller_button_sources[i] = source;\n        }\n    }\n''',
    "load controller remap config",
)

insert_marker = '''static HRESULT WINAPI fake_CreateDevice(void *self, UINT adapter, DWORD device_type, HWND focus_window,\n'''
if runtime.count(insert_marker) != 1:
    raise SystemExit(f"controller runtime remap v13 runtime insertion marker: found {runtime.count(insert_marker)}")

runtime_code = r'''static int controller_is_system_device(const GUID *guid)
{
    static const GUID sys_mouse = {
        0x6F1D2B60, 0xD5A0, 0x11CF,
        {0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00}
    };
    static const GUID sys_keyboard = {
        0x6F1D2B61, 0xD5A0, 0x11CF,
        {0xBF, 0xC7, 0x44, 0x45, 0x53, 0x54, 0x00, 0x00}
    };
    if (!guid) return 0;
    return memcmp(guid, &sys_mouse, sizeof(GUID)) == 0 ||
        memcmp(guid, &sys_keyboard, sizeof(GUID)) == 0;
}

static void normalize_controller_buttons(DWORD data_size, void *data)
{
    BYTE original[32];
    BYTE *bytes = (BYTE *)data;
    int i;

    /* MVP uses the classic 80-byte DIJOYSTATE layout. rgbButtons starts at
     * byte 48. On the modern devices we have traced, controller.cfg "button N"
     * is consumed as rgbButtons[N], while community profiles are conventionally
     * written as buttons 1..10. Move the learned physical buttons into those
     * logical 1..10 slots and leave slot 0 unused. */
    if (!controller_remap_enabled || !data || data_size != 80) return;
    memcpy(original, bytes + 48, sizeof(original));
    ZeroMemory(bytes + 48, sizeof(original));
    for (i = 0; i < 10; i++) {
        int source = controller_button_sources[i];
        if (source >= 0 && source < 32)
            bytes[48 + (i + 1)] = original[source];
    }
}

static HRESULT WINAPI controller_fake_GetDeviceState(void *self, DWORD data_size, void *data)
{
    HRESULT hr = controller_real_GetDeviceState ?
        controller_real_GetDeviceState(self, data_size, data) : E_FAIL;
    if (SUCCEEDED(hr)) normalize_controller_buttons(data_size, data);
    return hr;
}

static void controller_patch_device(void *device)
{
    void **vtbl;
    if (!device) return;
    vtbl = *(void ***)device;
    if (!vtbl) return;
    patch_vtable_slot(vtbl, 9, controller_fake_GetDeviceState,
        (void **)&controller_real_GetDeviceState);
}

static HRESULT WINAPI controller_fake_CreateDevice(void *self, const GUID *guid,
    void **returned_device, void *outer)
{
    HRESULT hr = controller_real_CreateDevice ?
        controller_real_CreateDevice(self, guid, returned_device, outer) : E_FAIL;
    if (SUCCEEDED(hr) && returned_device && *returned_device &&
        !controller_is_system_device(guid))
        controller_patch_device(*returned_device);
    return hr;
}

static HRESULT WINAPI controller_fake_DirectInputCreateA(HINSTANCE inst, DWORD version,
    void **returned_di, void *outer)
{
    ControllerDirectInputCreateAFn fn = NULL;
    void *target = InterlockedCompareExchangePointer(&controller_real_DirectInputCreateA, NULL, NULL);
    HRESULT hr;
    memcpy(&fn, &target, sizeof(fn));
    if (!fn) return E_FAIL;
    hr = fn(inst, version, returned_di, outer);
    if (SUCCEEDED(hr) && returned_di && *returned_di) {
        void **vtbl = *(void ***)*returned_di;
        if (vtbl)
            patch_vtable_slot(vtbl, 3, controller_fake_CreateDevice,
                (void **)&controller_real_CreateDevice);
    }
    return hr;
}

static void install_controller_runtime_remap(void)
{
    HMODULE dinput;
    void *target;
    if (!controller_remap_enabled) return;
    dinput = GetModuleHandleA("dinput.dll");
    if (!dinput) return;
    target = (void *)GetProcAddress(dinput, "DirectInputCreateA");
    if (hook_function(target, controller_fake_DirectInputCreateA,
            &controller_real_DirectInputCreateA) > 0)
        log_line("controller runtime button normalization enabled\n");
}

'''
runtime = runtime.replace(insert_marker, runtime_code + insert_marker, 1)

runtime = replace_once(
    runtime,
    '''    install_save_fix();\n''',
    '''    install_save_fix();\n    install_controller_runtime_remap();\n''',
    "install controller remap",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern runtime controller button normalization v13")
