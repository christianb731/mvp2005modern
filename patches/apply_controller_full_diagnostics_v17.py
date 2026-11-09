from pathlib import Path
import re

RUNTIME = Path("src/runtime.c")
runtime = RUNTIME.read_text(encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"controller full diagnostics v17 {label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise SystemExit(f"controller full diagnostics v17 {label}: expected exactly one match, found {count}")
    return updated


# We are done guessing. This build is designed to get enough evidence from one
# gameplay session to distinguish: wrong file/profile, wrong DI index convention,
# false trigger activation, duplicate input/keyboard input, raw DirectInput vs
# XInput differences, and the exact logical button slot MVP responds to for B.

# Add stdio/stdarg for compact diagnostic formatting.
if '#include <stdio.h>\n' not in runtime:
    runtime = runtime.replace('#include <stdlib.h>\n', '#include <stdlib.h>\n#include <stdio.h>\n#include <stdarg.h>\n', 1)
elif '#include <stdarg.h>\n' not in runtime:
    runtime = runtime.replace('#include <stdio.h>\n', '#include <stdio.h>\n#include <stdarg.h>\n', 1)

# Extra Win32 file-hook typedefs and diagnostic globals live next to the existing
# controller hook globals.
runtime = replace_once(
    runtime,
    'static LONG controller_xinput_logged;\n',
    '''static LONG controller_xinput_logged;\n\n'''
    '''typedef HANDLE (WINAPI *ControllerCreateFileAFn)(LPCSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);\n'''
    '''typedef HANDLE (WINAPI *ControllerCreateFileWFn)(LPCWSTR, DWORD, DWORD, LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);\n'''
    '''typedef BOOL (WINAPI *ControllerReadFileFn)(HANDLE, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);\n'''
    '''typedef BOOL (WINAPI *ControllerCloseHandleFn)(HANDLE);\n'''
    '''static ControllerCreateFileAFn controller_diag_real_CreateFileA;\n'''
    '''static ControllerCreateFileWFn controller_diag_real_CreateFileW;\n'''
    '''static ControllerReadFileFn controller_diag_real_ReadFile;\n'''
    '''static ControllerCloseHandleFn controller_diag_real_CloseHandle;\n'''
    '''static HANDLE controller_diag_log_handle = INVALID_HANDLE_VALUE;\n'''
    '''static HANDLE controller_diag_cfg_handles[8];\n'''
    '''static DWORD controller_diag_cfg_logged[8];\n'''
    '''static int controller_diag_mode = 1;\n'''
    '''static int controller_diag_b_slot_override;\n'''
    '''static BYTE controller_diag_hotkey_prev[32];\n''',
    "diagnostic globals",
)

marker = 'static LONG controller_clamp_axis(LONG value)\n'
if runtime.count(marker) != 1:
    raise SystemExit(f"controller full diagnostics v17 helper marker: found {runtime.count(marker)}")

helpers = r'''static void controller_diag_write(const char *text)
{
    DWORD written;
    if (controller_diag_log_handle == INVALID_HANDLE_VALUE || !text) return;
    WriteFile(controller_diag_log_handle, text, lstrlenA(text), &written, NULL);
    FlushFileBuffers(controller_diag_log_handle);
}

static void controller_diag_logf(const char *fmt, ...)
{
    char buf[2048];
    char line[2160];
    va_list args;
    int n;
    va_start(args, fmt);
    n = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (n < 0) buf[0] = 0;
    buf[sizeof(buf) - 1] = 0;
    snprintf(line, sizeof(line), "%08lu %s\r\n", (unsigned long)GetTickCount(), buf);
    line[sizeof(line) - 1] = 0;
    controller_diag_write(line);
}

static int controller_diag_contains_ci_a(const char *haystack, const char *needle)
{
    const char *h;
    if (!haystack || !needle || !*needle) return 0;
    for (; *haystack; haystack++) {
        h = haystack;
        {
            const char *n = needle;
            while (*h && *n) {
                char a = *h;
                char b = *n;
                if (a >= 'A' && a <= 'Z') a = (char)(a + ('a' - 'A'));
                if (b >= 'A' && b <= 'Z') b = (char)(b + ('a' - 'A'));
                if (a != b) break;
                h++; n++;
            }
            if (!*n) return 1;
        }
    }
    return 0;
}

static int controller_diag_track_handle(HANDLE h)
{
    int i;
    if (h == INVALID_HANDLE_VALUE || !h) return -1;
    for (i = 0; i < 8; i++) {
        if (controller_diag_cfg_handles[i] == h) return i;
    }
    for (i = 0; i < 8; i++) {
        if (!controller_diag_cfg_handles[i]) {
            controller_diag_cfg_handles[i] = h;
            controller_diag_cfg_logged[i] = 0;
            return i;
        }
    }
    return -1;
}

static int controller_diag_find_handle(HANDLE h)
{
    int i;
    for (i = 0; i < 8; i++) if (controller_diag_cfg_handles[i] == h) return i;
    return -1;
}

static HANDLE WINAPI controller_diag_CreateFileA(LPCSTR name, DWORD access, DWORD share,
    LPSECURITY_ATTRIBUTES sa, DWORD disposition, DWORD flags, HANDLE template_file)
{
    HANDLE h = controller_diag_real_CreateFileA ?
        controller_diag_real_CreateFileA(name, access, share, sa, disposition, flags, template_file) : INVALID_HANDLE_VALUE;
    if (name && controller_diag_contains_ci_a(name, "controller.cfg")) {
        int slot = controller_diag_track_handle(h);
        controller_diag_logf("CFG OPEN A handle=%p slot=%d access=%08lx disp=%lu path=%s",
            h, slot, (unsigned long)access, (unsigned long)disposition, name);
    }
    return h;
}

static HANDLE WINAPI controller_diag_CreateFileW(LPCWSTR name, DWORD access, DWORD share,
    LPSECURITY_ATTRIBUTES sa, DWORD disposition, DWORD flags, HANDLE template_file)
{
    HANDLE h = controller_diag_real_CreateFileW ?
        controller_diag_real_CreateFileW(name, access, share, sa, disposition, flags, template_file) : INVALID_HANDLE_VALUE;
    if (name) {
        char path[1024];
        path[0] = 0;
        WideCharToMultiByte(CP_ACP, 0, name, -1, path, sizeof(path), NULL, NULL);
        path[sizeof(path) - 1] = 0;
        if (controller_diag_contains_ci_a(path, "controller.cfg")) {
            int slot = controller_diag_track_handle(h);
            controller_diag_logf("CFG OPEN W handle=%p slot=%d access=%08lx disp=%lu path=%s",
                h, slot, (unsigned long)access, (unsigned long)disposition, path);
        }
    }
    return h;
}

static BOOL WINAPI controller_diag_ReadFile(HANDLE h, LPVOID buffer, DWORD to_read,
    LPDWORD did_read, LPOVERLAPPED overlapped)
{
    BOOL ok = controller_diag_real_ReadFile ?
        controller_diag_real_ReadFile(h, buffer, to_read, did_read, overlapped) : FALSE;
    int slot = controller_diag_find_handle(h);
    if (ok && slot >= 0 && buffer && did_read && *did_read && !overlapped &&
        controller_diag_cfg_logged[slot] < 32768) {
        DWORD available = 32768 - controller_diag_cfg_logged[slot];
        DWORD amount = *did_read < available ? *did_read : available;
        controller_diag_logf("CFG READ handle=%p bytes=%lu offset_log=%lu BEGIN",
            h, (unsigned long)*did_read, (unsigned long)controller_diag_cfg_logged[slot]);
        if (amount) {
            DWORD written;
            WriteFile(controller_diag_log_handle, buffer, amount, &written, NULL);
            controller_diag_write("\r\n");
            controller_diag_cfg_logged[slot] += amount;
        }
        controller_diag_logf("CFG READ handle=%p END", h);
    }
    return ok;
}

static BOOL WINAPI controller_diag_CloseHandle(HANDLE h)
{
    int slot = controller_diag_find_handle(h);
    if (slot >= 0) {
        controller_diag_logf("CFG CLOSE handle=%p total_logged=%lu", h,
            (unsigned long)controller_diag_cfg_logged[slot]);
        controller_diag_cfg_handles[slot] = NULL;
        controller_diag_cfg_logged[slot] = 0;
    }
    return controller_diag_real_CloseHandle ? controller_diag_real_CloseHandle(h) : FALSE;
}

static void controller_diag_open_log(void)
{
    char path[MAX_PATH];
    if (!get_module_dir(path, sizeof(path)) || !append_path(path, sizeof(path), "mvp2005controller_diagnostic.log")) return;
    controller_diag_log_handle = CreateFileA(path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
        NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (controller_diag_log_handle != INVALID_HANDLE_VALUE) {
        controller_diag_write("MVP2005 Modern full controller diagnostics v17\r\n");
        controller_diag_logf("process=%p module=%p remap=%d initial_mode=%d",
            GetCurrentProcess(), GetModuleHandleA(NULL), controller_remap_enabled, controller_diag_mode);
    }
}

static void controller_diag_install_file_hooks(void)
{
    HMODULE k32 = GetModuleHandleA("kernel32.dll");
    if (!k32) return;
    hook_function((void *)GetProcAddress(k32, "CreateFileA"), controller_diag_CreateFileA,
        (void *volatile *)&controller_diag_real_CreateFileA);
    hook_function((void *)GetProcAddress(k32, "CreateFileW"), controller_diag_CreateFileW,
        (void *volatile *)&controller_diag_real_CreateFileW);
    hook_function((void *)GetProcAddress(k32, "ReadFile"), controller_diag_ReadFile,
        (void *volatile *)&controller_diag_real_ReadFile);
    hook_function((void *)GetProcAddress(k32, "CloseHandle"), controller_diag_CloseHandle,
        (void *volatile *)&controller_diag_real_CloseHandle);
    controller_diag_logf("file hooks installed A=%p W=%p Read=%p Close=%p",
        controller_diag_real_CreateFileA, controller_diag_real_CreateFileW,
        controller_diag_real_ReadFile, controller_diag_real_CloseHandle);
}

static const char *controller_diag_mode_name(int mode)
{
    switch (mode) {
    case 0: return "RAW_DIRECTINPUT";
    case 1: return "DI_BUTTON_REMAP_RAW_AXES";
    case 2: return "XINPUT_ONE_BASED";
    case 3: return "XINPUT_ZERO_BASED";
    case 4: return "DI_REMAP_TRIGGER_NEUTRAL";
    case 5: return "XINPUT_TRIGGER_NEUTRAL";
    default: return "UNKNOWN";
    }
}

static int controller_diag_hotkey_edge(int index, int vk)
{
    int down = (GetAsyncKeyState(vk) & 0x8000) != 0;
    int edge = down && !controller_diag_hotkey_prev[index];
    controller_diag_hotkey_prev[index] = (BYTE)down;
    return edge;
}

static void controller_diag_update_hotkeys(void)
{
    int ctrl = (GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0;
    int i;
    if (ctrl) {
        static const int fkeys[6] = {VK_F5, VK_F6, VK_F7, VK_F8, VK_F9, VK_F10};
        for (i = 0; i < 6; i++) {
            if (controller_diag_hotkey_edge(i, fkeys[i])) {
                controller_diag_mode = i;
                controller_diag_logf("MODE CHANGE -> %d %s", controller_diag_mode,
                    controller_diag_mode_name(controller_diag_mode));
            }
        }
        for (i = 0; i < 10; i++) {
            int vk = (i == 9) ? '0' : ('1' + i);
            if (controller_diag_hotkey_edge(8 + i, vk)) {
                controller_diag_b_slot_override = i + 1;
                controller_diag_logf("B SLOT OVERRIDE -> logical slot %d (trigger axis will be neutral during B)",
                    controller_diag_b_slot_override);
            }
        }
        if (controller_diag_hotkey_edge(20, VK_F11)) {
            controller_diag_b_slot_override = 0;
            controller_diag_logf("B SLOT OVERRIDE cleared");
        }
        if (controller_diag_hotkey_edge(21, VK_F12))
            controller_diag_logf("USER MARKER Ctrl+F12");
    } else {
        for (i = 0; i < 22; i++) controller_diag_hotkey_prev[i] = 0;
    }
}

static void controller_diag_format_buttons(const BYTE *buttons, char *out, size_t out_size)
{
    int i;
    size_t used = 0;
    if (!out_size) return;
    out[0] = 0;
    for (i = 0; i < 16; i++) {
        if (buttons[i] & 0x80) {
            int n = snprintf(out + used, out_size - used, "%s%d", used ? "," : "", i);
            if (n < 0 || (size_t)n >= out_size - used) break;
            used += (size_t)n;
        }
    }
    if (!used) lstrcpynA(out, "none", (int)out_size);
}

typedef struct ControllerDiagStateRec {
    void *self;
    BYTE raw[80];
    BYTE out[80];
    int have_raw;
    int have_out;
} ControllerDiagStateRec;

static ControllerDiagStateRec controller_diag_states[32];

static ControllerDiagStateRec *controller_diag_state_rec(void *self)
{
    int i;
    for (i = 0; i < 32; i++) if (controller_diag_states[i].self == self) return &controller_diag_states[i];
    for (i = 0; i < 32; i++) {
        if (!controller_diag_states[i].self) {
            controller_diag_states[i].self = self;
            return &controller_diag_states[i];
        }
    }
    return &controller_diag_states[0];
}

static void controller_diag_log_state(void *self, void *caller, const BYTE *raw, const BYTE *out, DWORD size)
{
    ControllerDiagStateRec *rec;
    char raw_buttons[128];
    char out_buttons[128];
    LONG *ra;
    LONG *oa;
    DWORD *rp;
    DWORD *op;
    int raw_changed;
    int out_changed;
    if (size != 80 || !raw || !out) return;
    rec = controller_diag_state_rec(self);
    raw_changed = !rec->have_raw || memcmp(rec->raw, raw, 80) != 0;
    out_changed = !rec->have_out || memcmp(rec->out, out, 80) != 0;
    if (!raw_changed && !out_changed) return;
    memcpy(rec->raw, raw, 80); rec->have_raw = 1;
    memcpy(rec->out, out, 80); rec->have_out = 1;
    controller_diag_format_buttons(raw + 48, raw_buttons, sizeof(raw_buttons));
    controller_diag_format_buttons(out + 48, out_buttons, sizeof(out_buttons));
    ra = (LONG *)raw; oa = (LONG *)out;
    rp = (DWORD *)(raw + 32); op = (DWORD *)(out + 32);
    controller_diag_logf(
        "STATE self=%p caller=%p mode=%d/%s bslot=%d RAW btn=[%s] axes=%ld,%ld,%ld,%ld,%ld,%ld pov=%08lx | OUT btn=[%s] axes=%ld,%ld,%ld,%ld,%ld,%ld pov=%08lx | keys Esc=%d Enter=%d",
        self, caller, controller_diag_mode, controller_diag_mode_name(controller_diag_mode),
        controller_diag_b_slot_override, raw_buttons,
        ra[0],ra[1],ra[2],ra[3],ra[4],ra[5],(unsigned long)rp[0],
        out_buttons, oa[0],oa[1],oa[2],oa[3],oa[4],oa[5],(unsigned long)op[0],
        (GetAsyncKeyState(VK_ESCAPE)&0x8000)!=0, (GetAsyncKeyState(VK_RETURN)&0x8000)!=0);
}

static void controller_diag_log_xinput(void)
{
    static ControllerXInputState last;
    static int have_last;
    ControllerXInputGetStateFn fn = controller_load_xinput_get_state();
    ControllerXInputState s;
    DWORD user;
    if (!fn) return;
    ZeroMemory(&s, sizeof(s));
    for (user = 0; user < 4; user++) if (fn(user, &s) == ERROR_SUCCESS) break;
    if (user >= 4) return;
    if (!have_last || memcmp(&last, &s, sizeof(s)) != 0) {
        controller_diag_logf("XINPUT user=%lu packet=%lu buttons=%04x LT=%u RT=%u LX=%d LY=%d RX=%d RY=%d",
            (unsigned long)user, (unsigned long)s.dwPacketNumber,
            (unsigned int)s.Gamepad.wButtons,
            (unsigned int)s.Gamepad.bLeftTrigger, (unsigned int)s.Gamepad.bRightTrigger,
            (int)s.Gamepad.sThumbLX, (int)s.Gamepad.sThumbLY,
            (int)s.Gamepad.sThumbRX, (int)s.Gamepad.sThumbRY);
        last = s;
        have_last = 1;
    }
}

static int controller_diag_xinput_b_down(void)
{
    ControllerXInputGetStateFn fn = controller_load_xinput_get_state();
    ControllerXInputState s;
    DWORD user;
    if (!fn) return 0;
    ZeroMemory(&s, sizeof(s));
    for (user = 0; user < 4; user++) {
        if (fn(user, &s) == ERROR_SUCCESS)
            return (s.Gamepad.wButtons & CXINPUT_B) != 0;
    }
    return 0;
}

'''
runtime = runtime.replace(marker, helpers + marker, 1)

# Replace the normalizer with six runtime-selectable modes. This makes one binary
# capable of testing every plausible translation without another compile.
runtime = replace_regex_once(
    runtime,
    r'''static void normalize_controller_buttons\(DWORD data_size, void \*data\)\n\{.*?\n\}\n\nstatic HRESULT WINAPI controller_fake_GetDeviceState''',
    r'''static void normalize_controller_buttons(DWORD data_size, void *data)
{
    BYTE original_buttons[32];
    LONG original_axes[6];
    BYTE *bytes = (BYTE *)data;
    LONG *axes = (LONG *)data;
    int i;

    if (!controller_remap_enabled || !data || data_size != 80) return;
    controller_diag_update_hotkeys();

    if (controller_diag_mode == 0) {
        /* Exact raw DirectInput passthrough. */
    } else if (controller_diag_mode == 2 || controller_diag_mode == 3 || controller_diag_mode == 5) {
        if (controller_write_xinput_state(data_size, data)) {
            if (controller_diag_mode == 3) {
                /* Compare the legacy zero-based hypothesis in the same run. */
                for (i = 0; i < 10; i++) bytes[48 + i] = bytes[48 + i + 1];
                bytes[48 + 10] = 0;
            }
            if (controller_diag_mode == 5) axes[2] = 32767;
        }
    } else {
        /* v13 behavior: calibrated physical DI buttons -> logical slots 1..10,
         * but leave the physical axes alone. This is the mode where the user
         * previously reported the face buttons and Start as working. */
        memcpy(original_axes, axes, sizeof(original_axes));
        memcpy(original_buttons, bytes + 48, sizeof(original_buttons));
        ZeroMemory(bytes + 48, sizeof(original_buttons));
        for (i = 0; i < 10; i++) {
            int source = controller_button_sources[i];
            if (source >= 0 && source < 32)
                bytes[48 + (i + 1)] = original_buttons[source];
        }
        if (controller_diag_mode == 4) axes[2] = 32767;
    }

    /* Optional pure B slot test. Ctrl+1..0 selects slots 1..10. While physical B
     * is held, suppress all other logical buttons and neutralize the trigger axis.
     * This tells us in one session which slot MVP actually treats as Throw First. */
    if (controller_diag_b_slot_override >= 1 && controller_diag_b_slot_override <= 10 &&
        controller_diag_xinput_b_down()) {
        ZeroMemory(bytes + 48, 32);
        bytes[48 + controller_diag_b_slot_override] = 0x80;
        axes[2] = 32767;
    }
}

static HRESULT WINAPI controller_fake_GetDeviceState''',
    "multi-mode normalizer",
)

# Log raw and final state on every transition, plus XInput changes. We preserve a
# raw copy before any runtime transformation so the log can prove exactly what
# Windows supplied and exactly what MVP consumed.
runtime = replace_regex_once(
    runtime,
    r'''static HRESULT WINAPI controller_fake_GetDeviceState\(void \*self, DWORD data_size, void \*data\)\n\{.*?\n\}\n\nstatic void controller_patch_device''',
    r'''static HRESULT WINAPI controller_fake_GetDeviceState(void *self, DWORD data_size, void *data)
{
    BYTE raw[256];
    void *caller = __builtin_return_address(0);
    HRESULT hr = controller_real_GetDeviceState ?
        controller_real_GetDeviceState(self, data_size, data) : E_FAIL;
    if (SUCCEEDED(hr) && data && data_size <= sizeof(raw)) {
        memcpy(raw, data, data_size);
        controller_diag_log_xinput();
        normalize_controller_buttons(data_size, data);
        controller_diag_log_state(self, caller, raw, (const BYTE *)data, data_size);
    }
    return hr;
}

static void controller_patch_device''',
    "state transition logger",
)

# Avoid repeatedly repatching a shared DirectInput device vtable. Also log every
# non-system controller object MVP creates so duplicate-device behavior is visible.
runtime = replace_once(
    runtime,
    '''    patch_vtable_slot(vtbl, 9, controller_fake_GetDeviceState,\n        (void **)&controller_real_GetDeviceState);\n''',
    '''    if (vtbl[9] != (void *)controller_fake_GetDeviceState)\n        patch_vtable_slot(vtbl, 9, controller_fake_GetDeviceState,\n            (void **)&controller_real_GetDeviceState);\n''',
    "shared state vtable guard",
)

runtime = replace_regex_once(
    runtime,
    r'''static HRESULT WINAPI controller_fake_CreateDevice\(void \*self, const GUID \*guid,\n    void \*\*returned_device, void \*outer\)\n\{.*?\n\}\n\nstatic HRESULT WINAPI controller_fake_DirectInputCreateA''',
    r'''static HRESULT WINAPI controller_fake_CreateDevice(void *self, const GUID *guid,
    void **returned_device, void *outer)
{
    HRESULT hr = controller_real_CreateDevice ?
        controller_real_CreateDevice(self, guid, returned_device, outer) : E_FAIL;
    if (SUCCEEDED(hr) && returned_device && *returned_device) {
        int system_device = controller_is_system_device(guid);
        if (guid) {
            controller_diag_logf("DI CREATE device=%p system=%d guid=%08lx-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x",
                *returned_device, system_device,
                (unsigned long)guid->Data1, guid->Data2, guid->Data3,
                guid->Data4[0],guid->Data4[1],guid->Data4[2],guid->Data4[3],
                guid->Data4[4],guid->Data4[5],guid->Data4[6],guid->Data4[7]);
        }
        if (!system_device) controller_patch_device(*returned_device);
    }
    return hr;
}

static HRESULT WINAPI controller_fake_DirectInputCreateA''',
    "device creation logger",
)

runtime = replace_once(
    runtime,
    '''    hr = fn(inst, version, returned_di, outer);\n''',
    '''    hr = fn(inst, version, returned_di, outer);\n    controller_diag_logf("DirectInputCreateA version=%08lx hr=%08lx returned=%p",\n        (unsigned long)version, (unsigned long)hr,\n        (returned_di && SUCCEEDED(hr)) ? *returned_di : NULL);\n''',
    "DirectInput creation logger",
)

# Open the dedicated log before MinHook is initialized, then install the file
# tracing hooks immediately after MinHook is ready. This should catch the exact
# controller.cfg path/content MVP reads during startup.
runtime = replace_once(
    runtime,
    '''    load_config();\n    log_line("mvp2005fix loaded\\n");\n''',
    '''    load_config();\n    controller_diag_open_log();\n    log_line("mvp2005fix loaded\\n");\n''',
    "open diagnostic log",
)

runtime = replace_once(
    runtime,
    '''    install_save_fix();\n    install_controller_runtime_remap();\n''',
    '''    controller_diag_install_file_hooks();\n    install_save_fix();\n    install_controller_runtime_remap();\n    controller_diag_logf("controller hooks requested; hotkeys: Ctrl+F5 raw DI, F6 DI remap/raw axes, F7 XInput 1-based, F8 XInput 0-based, F9 DI remap+neutral trigger, F10 XInput+neutral trigger; Ctrl+1..0 B-slot test, Ctrl+F11 clear B-slot, Ctrl+F12 marker");\n''',
    "install diagnostics",
)

RUNTIME.write_text(runtime, encoding="utf-8")
print("Applied MVP2005 Modern full controller diagnostics v17")
